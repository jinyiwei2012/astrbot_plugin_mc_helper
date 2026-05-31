"""File utilities for log collection and cleanup."""

import shutil
import time
from pathlib import Path

from astrbot.api import logger


def _safe_read(path: Path, extract_dir: Path) -> str:
    resolved = path.resolve()
    if not str(resolved).startswith(str(extract_dir.resolve())):
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"读取 {path.name} 失败: {e}")
        return ""


def _is_safe_symlink(path: Path, extract_dir: Path) -> bool:
    try:
        resolved = path.resolve()
        return str(resolved).startswith(str(extract_dir.resolve()))
    except Exception:
        return False


def collect_logs(extract_dir: Path) -> str:
    root = extract_dir.resolve()
    logs = []
    for f in extract_dir.rglob("*"):
        if not f.is_file() or f.suffix not in (".log", ".txt", ".json"):
            continue
        if f.is_symlink() and not _is_safe_symlink(f, root):
            continue
        c = _safe_read(f, root)
        if c.strip():
            logs.append(f"=== {f.name} ===\n{c}\n")
    return "\n".join(logs)


def collect_latest_log(extract_dir: Path) -> str:
    root = extract_dir.resolve()
    for name, path in [
        ("游戏崩溃前的输出.txt", extract_dir / "游戏崩溃前的输出.txt"),
        ("latest.log", extract_dir / "logs" / "latest.log"),
    ]:
        if not path.is_file():
            continue
        if path.is_symlink() and not _is_safe_symlink(path, root):
            continue
        c = _safe_read(path, root)
        if c.strip():
            return c
    for f in extract_dir.rglob("latest.log"):
        if f.is_file():
            if f.is_symlink() and not _is_safe_symlink(f, root):
                continue
            c = _safe_read(f, root)
            if c.strip():
                return c
    return ""


def cleanup_old_files(data_path: Path, max_age_days: int):
    try:
        rd = data_path / "错误报告"
        if not rd.is_dir():
            return
        cutoff = time.time() - max_age_days * 86400
        for item in rd.iterdir():
            try:
                if item.stat().st_mtime < cutoff:
                    if item.is_dir():
                        shutil.rmtree(item, ignore_errors=True)
                    else:
                        item.unlink(missing_ok=True)
                    logger.info(f"清理旧报告: {item.name}")
            except Exception as e:
                logger.debug(f"清理 {item.name} 出错: {e}")
    except Exception as e:
        logger.debug(f"清理旧文件出错: {e}")
