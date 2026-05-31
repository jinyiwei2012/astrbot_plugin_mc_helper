"""Solution database CRUD operations."""

import json
from pathlib import Path
from typing import Optional

from astrbot.api import logger


def load_db(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return dict(json.load(f))
        except Exception as e:
            logger.error(f"加载方案库失败: {e}")
    return {}


def load_duplicate_mods(path: Path) -> dict:
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return dict(json.load(f))
    except Exception as e:
        logger.error(f"加载重复模组对照表失败: {e}")
    return {"mod_groups": []}


def get_solution(db: dict, key: str) -> Optional[str]:
    for entries in db.values():
        if key in entries:
            entry = entries[key]
            return entry["solution"] if isinstance(entry, dict) else entry
    return None


def count_solutions(db: dict) -> int:
    count = 0
    for v in db.values():
        count += len(v) if isinstance(v, dict) else 1
    return count
