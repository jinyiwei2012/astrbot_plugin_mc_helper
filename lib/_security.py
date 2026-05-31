"""Zip security scanning and user blacklist management."""

import ipaddress
import json
import re
import stat
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from astrbot.api import logger

from ._utils import BLACKLIST_EXTS, DANGEROUS_CMDS

_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]
_ALLOWED_SCHEMES = {"http", "https"}
_JSON_SCAN_MAX_BYTES = 256 * 1024
_RATE_WINDOW = 60
_RATE_MAX_UPLOADS = 5
_RE_TRAVERSAL = re.compile(r"(?:^|[/\\])\.{2,}[/\\]")


def _clean_fn(name: str) -> str:
    cleaned = name.lstrip().rstrip(" .")
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    return cleaned


def _validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("不允许的 URL 协议")
    host = parsed.hostname
    if not host:
        raise ValueError("无法解析 URL 主机名")
    if host.lower() == "localhost":
        raise ValueError("不允许访问此主机")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        import socket

        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except Exception:
            raise ValueError("DNS 解析失败")
    for net in _PRIVATE_RANGES:
        if ip in net:
            raise ValueError("不允许访问内网地址")
    return parsed.geturl()


async def download_zip(file_url: str, zip_path: Path, timeout_sec: int = 120):
    safe_url = _validate_url(file_url)
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(safe_url) as resp:
            if resp.status != 200:
                raise ConnectionError(f"HTTP {resp.status}")
            with open(zip_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)


def _is_symlink(info) -> bool:
    try:
        mode = info.external_attr >> 16
        return stat.S_ISLNK(mode)
    except (AttributeError, TypeError):
        return False


def scan_zip(zip_path: Path) -> list[str]:
    import zipfile

    blacklisted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > 1000:
            return ["__too_many_files__"]

        for info in infos:
            if info.is_dir():
                continue
            if _is_symlink(info):
                blacklisted.append(info.filename)
                continue
            fn = info.filename
            cleaned = _clean_fn(fn)
            if (
                cleaned == ""
                or cleaned.startswith("/")
                or cleaned.startswith("..")
                or "/../" in cleaned
                or "\\..\\" in cleaned
                or _RE_TRAVERSAL.search(cleaned)
            ):
                blacklisted.append(fn)
                continue
            ext = Path(cleaned).suffix.lower()
            if ext in BLACKLIST_EXTS:
                blacklisted.append(info.filename)
            elif ext == ".json":
                try:
                    raw = zf.read(info)
                    if len(raw) > _JSON_SCAN_MAX_BYTES:
                        head = raw[: _JSON_SCAN_MAX_BYTES // 2]
                        tail = raw[-_JSON_SCAN_MAX_BYTES // 2 :]
                        combined = head + b"\n" + tail
                    else:
                        combined = raw
                    content = combined.decode("utf-8", errors="replace")
                except Exception:
                    content = ""
                if any(kw in content.lower() for kw in DANGEROUS_CMDS):
                    blacklisted.append(fn)
    return blacklisted


def extract_safe_files(zip_path: Path, extract_dir: Path) -> int:
    import zipfile
    from ._utils import MAX_FILE_SIZE, MAX_EXTRACT_SIZE

    total_size = 0
    extracted = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir() or _is_symlink(info):
                continue
            filename = _clean_fn(info.filename)
            if not filename or _RE_TRAVERSAL.search(filename):
                continue
            ext = Path(filename).suffix.lower()
            if ext not in (".log", ".txt", ".json"):
                continue
            if info.file_size > MAX_FILE_SIZE:
                raise ValueError("文件过大")
            total_size += info.file_size
            if total_size > MAX_EXTRACT_SIZE:
                raise ValueError("解压总大小超限")
            target = (extract_dir / filename).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise ValueError("无效路径")
            zf.extract(info, extract_dir)
            extracted += 1
    return extracted


class UserBlacklist:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict = self._load()

    def _load(self) -> dict:
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as f:
                    return dict(json.load(f))
        except Exception as e:
            logger.error(f"加载用户黑名单失败: {e}")
        return {}

    def _save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存用户黑名单失败: {e}")

    def is_blacklisted(self, uid: str) -> bool:
        entry = self.data.get(uid)
        return entry is not None and entry.get("blacklisted", False)

    def record_malicious(self, uid: str, max_allowed: int = 3):
        entry = self.data.get(uid, {"count": 0, "blacklisted": False})
        entry["count"] = entry.get("count", 0) + 1
        if entry["count"] >= max_allowed:
            entry["blacklisted"] = True
            logger.warning(f"用户 {uid} 已因多次上传恶意文件被自动拉黑")
        self.data[uid] = entry
        self._save()


class RateLimiter:
    def __init__(self):
        self._windows: dict[str, list[float]] = {}

    def allow(self, uid: str) -> bool:
        now = time.monotonic()
        window = self._windows.get(uid, [])
        window = [t for t in window if now - t < _RATE_WINDOW]
        if len(window) >= _RATE_MAX_UPLOADS:
            self._windows[uid] = window
            return False
        window.append(now)
        self._windows[uid] = window
        if len(self._windows) > 5000:
            self._windows = {k: v for k, v in self._windows.items() if v and now - v[-1] < _RATE_WINDOW}
        return True
