"""Zip security scanning and user blacklist management."""

import json
import re
from pathlib import Path

import aiohttp

from astrbot.api import logger

from ._utils import BLACKLIST_EXTS, DANGEROUS_CMDS


def _clean_fn(name: str) -> str:
    """Sanitize filename: strip leading whitespace, trailing spaces/dots, control chars."""
    cleaned = name.lstrip().rstrip(" .")
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", cleaned)
    return cleaned


async def download_zip(file_url: str, zip_path: Path, timeout_sec: int = 120):
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(file_url) as resp:
            if resp.status != 200:
                raise ConnectionError(f"HTTP {resp.status}")
            with open(zip_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(65536):
                    f.write(chunk)


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
            fn = info.filename
            cleaned = _clean_fn(fn)
            if (
                cleaned == ""
                or cleaned.startswith("/")
                or cleaned.startswith("..")
                or "/../" in cleaned
                or "\\..\\" in cleaned
                or re.search(r"(?:^|[/\\])\.{2,}[/\\]", cleaned)
            ):
                blacklisted.append(fn)
                continue
            ext = Path(cleaned).suffix.lower()
            if ext in BLACKLIST_EXTS:
                blacklisted.append(info.filename)
            elif ext == ".json":
                try:
                    raw = zf.read(info)
                    content = raw.decode("utf-8", errors="replace")
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
            if info.is_dir():
                continue
            filename = _clean_fn(info.filename)
            if not filename or re.search(r"(?:^|/)\.{2,}/", filename):
                continue
            ext = Path(filename).suffix.lower()
            if ext not in (".log", ".txt", ".json"):
                continue
            if info.file_size > MAX_FILE_SIZE:
                raise ValueError(f"文件过大: {filename}")
            total_size += info.file_size
            if total_size > MAX_EXTRACT_SIZE:
                raise ValueError("解压总大小超限")
            target = (extract_dir / filename).resolve()
            if not str(target).startswith(str(extract_dir.resolve())):
                raise ValueError(f"无效路径: {filename}")
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
