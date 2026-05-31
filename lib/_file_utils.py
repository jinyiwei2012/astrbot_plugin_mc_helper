"""文件工具—从解压目录中安全收集日志"""

from pathlib import Path

from astrbot.api import logger


def _safe_read(path: Path, extract_dir: Path) -> str:
    """仅在文件位于允许的解压目录内时才读取"""
    resolved = path.resolve()
    if not str(resolved).startswith(str(extract_dir.resolve())):
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"读取 {path.name} 失败: {e}")
        return ""


def _is_safe_symlink(path: Path, extract_dir: Path) -> bool:
    """检查符号链接是否解析到解压目录内的路径"""
    try:
        resolved = path.resolve()
        return str(resolved).startswith(str(extract_dir.resolve()))
    except (OSError, RuntimeError):
        return False


def collect_logs(extract_dir: Path) -> str:
    """将解压目录中所有 .log/.txt/.json 文件拼接成一个字符串"""
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
    """尝试读取主崩溃日志（游戏崩溃前的输出.txt / latest.log）"""
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
