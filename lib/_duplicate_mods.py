"""重复模组检测—对照已知别名库交叉引用错误文本"""

import re

from ._utils import JAR_RE


def check_duplicate_mods(duplicate_mods_data: dict, error_text: str) -> str | None:
    """扫描错误文本中的重复模组实例，找到后生成清理指南

    查找属于同一模组族的多个 jar 文件或路径引用
    （如 OptiFine + OptiFabric），然后生成清理提示。
    """
    found_jars: list[str] = []
    found_paths: list[str] = []

    # 从错误文本中收集所有 jar 文件名和 mods 路径引用
    for m in re.finditer(JAR_RE, error_text, re.IGNORECASE):
        found_jars.append(m.group(0))
    for m in re.finditer(r"(?:^|[\s\\/])mods[\\/](" + JAR_RE + r")", error_text, re.IGNORECASE):
        found_paths.append(m.group(1))

    # 也尝试解析 "Duplicate Mods:" 区段
    ds = re.search(r"Duplicate\s*Mod[s]?[:\s]*\n((?:.{0,300}\n?){0,15})", error_text, re.IGNORECASE)
    if ds and not found_paths:
        sec = ds.group(1)
        found_paths = re.findall(r"(?:^|[\s\\/])mods[\\/](" + JAR_RE + r")", sec, re.IGNORECASE)
        if not found_paths:
            found_paths = re.findall(JAR_RE, sec, re.IGNORECASE)

    for group in duplicate_mods_data.get("mod_groups", []):
        current = group.get("current", "")
        aliases = group.get("aliases", [])
        all_names = [s.lower() for s in ([current] + aliases)]
        matched_jars, matched_paths = [], []

        for j in found_jars:
            if any(n in j.lower() for n in all_names):
                matched_jars.append(j)
        for p in found_paths:
            if any(n in p.lower() for n in all_names):
                matched_paths.append(p)

        # 也按单词边界检查名称提及，避免子串误匹配
        found_by_name = []
        for n in ([current] + aliases):
            if not n:
                continue
            if re.search(r"(?<!\w)" + re.escape(n.lower()) + r"(?!\w)", error_text.lower()):
                found_by_name.append(n)

        if len(set(matched_jars)) >= 2 or len(set(matched_paths)) >= 2:
            matched = set(matched_paths) or set(matched_jars)
            fl = "\n".join(f"- `{x}`" for x in list(matched)[:5])
        elif len(set(found_by_name)) >= 2:
            matched = set()
            fl = ""
        else:
            continue

        result = f"**⚠️ 检测到同一类模组出现多个：{', '.join(dict.fromkeys(found_by_name))}**\n\n"
        result += f"{group.get('note', '')}\n"
        if matched:
            result += f"\n**检测到的冲突文件：**\n{fl}\n"
        result += (
            f"\n**如何清理**\n"
            f"1. 打开 `.minecraft/mods` 文件夹（PCL 里点「设置」→「模组文件夹」）\n"
            f"2. 搜索上面提到的文件名，把旧版/别名版删掉，只保留 `{current}`\n"
            f"3. 删完重启游戏\n\n"
            f"👉 {group.get('recommendation', '只保留一个')}\n\n"
            f"**常见文件名示例：**\n"
        )
        result += "\n".join(f"- `{e}`" for e in group.get("examples", [])[:3])
        return result
    return None
