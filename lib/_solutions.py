"""Solution database CRUD operations."""

import json
from pathlib import Path
from typing import Optional

from astrbot.api import logger


def _load_json(path: Path, label: str, fallback: dict) -> dict:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return dict(json.load(f))
    except Exception as e:
        logger.error(f"加载{label}失败: {e}")
    return fallback


def load_db(path: Path) -> dict:
    return _load_json(path, "方案库", {})


def load_duplicate_mods(path: Path) -> dict:
    return _load_json(path, "重复模组对照表", {"mod_groups": []})


def get_solution(db: dict, key: str) -> Optional[str]:
    for entries in db.values():
        if key in entries:
            entry = entries[key]
            return entry["solution"] if isinstance(entry, dict) else entry
    return None


def count_solutions(db: dict) -> int:
    count = 0
    for v in db.values():
        if isinstance(v, dict):
            count += len(v)
        elif isinstance(v, (list, str)):
            count += 1
    return count
