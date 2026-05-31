"""压缩包安全扫描、安全下载和用户黑名单管理"""

import asyncio
import ipaddress
import json
import re
import socket
import stat
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from astrbot.api import logger

from ._utils import BLACKLIST_EXTS, DANGEROUS_CMDS

# RFC 1918 等私有/回环地址段
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
    """正规化 Unicode 并移除文件名中的控制字符"""
    cleaned = name.lstrip().rstrip(" .")
    # NFKC 会将全角字符正规化（如 ．jar → .jar），防止同形字绕过
    cleaned = unicodedata.normalize("NFKC", cleaned)
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    return cleaned


async def _validate_url(url: str) -> tuple[str, str, str]:
    """验证下载 URL：检查协议、域名、DNS 和内网地址（SSRF 防护）

    返回 (sanitized_url, hostname, pinned_ip)
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        raise ValueError("不允许的 URL 协议")
    host = parsed.hostname
    if not host:
        raise ValueError("无法解析 URL 主机名")
    if host.lower() == "localhost":
        raise ValueError("不允许访问此主机")
    # 解析域名到 IP，拒绝内网地址（SSRF 防护）
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            loop = asyncio.get_running_loop()
            addrinfo = await asyncio.wait_for(loop.getaddrinfo(host, None), timeout=10)
        except (OSError, asyncio.TimeoutError, RuntimeError):
            raise ValueError("DNS 解析失败")
        if not addrinfo:
            raise ValueError("DNS 解析失败")
        ip = ipaddress.ip_address(addrinfo[0][4][0])
    for net in _PRIVATE_RANGES:
        if ip in net:
            raise ValueError("不允许访问内网地址")
    pinned_ip = str(ip)
    return parsed.geturl(), host, pinned_ip


class _PinnedResolver:
    """aiohttp DNS 解析器，将主机名固定到预解析的 IP（DNS 重绑定防御）"""

    def __init__(self, hostname: str, ip: str):
        self._hostname = hostname
        self._ip = ip
        self._family = socket.AF_INET6 if ":" in ip else socket.AF_INET

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        if host == self._hostname:
            return [
                {
                    "hostname": host,
                    "host": self._ip,
                    "port": port,
                    "family": self._family,
                    "proto": 6,
                    "flags": socket.AI_NUMERICHOST,
                }
            ]
        # 对意外重定向的目标回退
        af = socket.AF_INET6 if ":" in host else socket.AF_INET
        return [{"hostname": host, "host": host, "port": port, "family": af, "proto": 6, "flags": 0}]


_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


async def download_zip(file_url: str, zip_path: Path, timeout_sec: int = 120):
    """下载压缩包到磁盘，包含 SSRF 防护和大小限制"""
    safe_url, hostname, pinned_ip = await _validate_url(file_url)
    resolver = _PinnedResolver(hostname, pinned_ip)
    connector = aiohttp.TCPConnector(resolver=resolver)
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        async with session.get(safe_url) as resp:
            if resp.status != 200:
                raise ConnectionError(f"HTTP {resp.status}")
            downloaded = 0
            with open(zip_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    downloaded += len(chunk)
                    if downloaded > _MAX_DOWNLOAD_BYTES:
                        raise ValueError("下载文件过大")
                    f.write(chunk)


def _is_symlink(info) -> bool:
    """通过外部属性检测 zip 中的符号链接条目"""
    try:
        mode = info.external_attr >> 16
        return stat.S_ISLNK(mode)
    except (AttributeError, TypeError):
        return False


def scan_zip(zip_path: Path) -> list[str]:
    """扫描压缩包中的危险内容

    返回黑名单文件名列表（空列表表示干净）。
    预定义标记 ``["__too_many_files__"]`` 表示文件数超限被拒绝。
    """
    import zipfile

    blacklisted = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        infos = zf.infolist()
        if len(infos) > 1000:
            return ["__too_many_files__"]

        for info in infos:
            if info.is_dir():
                continue
            # 拒绝符号链接（可能用于任意文件读取）
            if _is_symlink(info):
                blacklisted.append(info.filename)
                continue
            fn = info.filename
            cleaned = _clean_fn(fn)
            # 路径穿越检查
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
            # 禁止危险扩展名
            if ext in BLACKLIST_EXTS:
                blacklisted.append(info.filename)
            # 扫描 .json 文件中是否包含危险命令关键字
            elif ext == ".json":
                try:
                    with zf.open(info) as f:
                        raw = f.read()
                    content = raw.decode("utf-8", errors="replace")
                    # 取头尾各半采样，防止关键字被放在文件中间绕过
                    half = _JSON_SCAN_MAX_BYTES // 2
                    if len(content) > _JSON_SCAN_MAX_BYTES:
                        content = content[:half] + "\n" + content[-half:]
                except (UnicodeDecodeError, ValueError):
                    content = ""
                if any(kw in content.lower() for kw in DANGEROUS_CMDS):
                    blacklisted.append(fn)
    return blacklisted


def extract_safe_files(zip_path: Path, extract_dir: Path) -> int:
    """从压缩包中仅提取 .log/.txt/.json 文件，并执行大小限制

    返回提取的文件数。
    """
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
            # 防止解压到目标目录之外（与路径穿越检查冗余）
            target = (extract_dir / filename).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise ValueError("无效路径")
            zf.extract(info, extract_dir)
            extracted += 1
    return extracted


class UserBlacklist:
    """持久化的用户黑名单，用于多次上传恶意文件后自动封禁"""

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
        """恶意上传计数 +1，达到阈值后自动拉黑"""
        entry = self.data.get(uid, {"count": 0, "blacklisted": False})
        entry["count"] = entry.get("count", 0) + 1
        if entry["count"] >= max_allowed:
            entry["blacklisted"] = True
            logger.warning(f"用户 {uid} 已因多次上传恶意文件被自动拉黑")
        self.data[uid] = entry
        self._save()


class RateLimiter:
    """基于滑动窗口的内存速率限制器"""

    def __init__(self):
        self._windows: dict[str, list[float]] = {}

    def allow(self, uid: str) -> bool:
        now = time.monotonic()
        window = self._windows.get(uid, [])
        # 移除过期时间戳
        window = [t for t in window if now - t < _RATE_WINDOW]
        if len(window) >= _RATE_MAX_UPLOADS:
            self._windows[uid] = window
            return False
        window.append(now)
        self._windows[uid] = window
        # 表太大时执行批量清理
        if len(self._windows) > 5000:
            cutoff = now - _RATE_WINDOW
            self._windows = {k: [t for t in v if t > cutoff] for k, v in self._windows.items() if any(t > cutoff for t in v)}
        return True
