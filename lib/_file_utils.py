"""File utilities for log collection and cleanup."""

import shutil
import time
from pathlib import Path

from astrbot.api import logger


def collect_logs(extract_dir: Path) -> str:
    logs = []
    for f in extract_dir.rglob("*"):
        if f.is_file() and f.suffix in (".log", ".txt", ".json"):
            try:
                c = f.read_text(encoding="utf-8", errors="ignore")
                if c.strip():
                    logs.append(f"=== {f.name} ===\n{c}\n")
            except Exception as e:
                logger.error(f"读取 {f.name} 失败: {e}")
    return "\n".join(logs)


def collect_latest_log(extract_dir: Path) -> str:
    for name, path in [
        ("游戏崩溃前的输出.txt", extract_dir / "游戏崩溃前的输出.txt"),
        ("latest.log", extract_dir / "logs" / "latest.log"),
    ]:
        if path.is_file():
            try:
                c = path.read_text(encoding="utf-8", errors="ignore")
                if c.strip():
                    return c
            except Exception as e:
                logger.error(f"读取 {name} 失败: {e}")
    for f in extract_dir.rglob("latest.log"):
        if f.is_file():
            try:
                return f.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                logger.error(f"读取 {f.name} 失败: {e}")
                return ""
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
