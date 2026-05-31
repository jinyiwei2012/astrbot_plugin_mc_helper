"""Duplicate mod detection."""

import re


def check_duplicate_mods(duplicate_mods_data: dict, error_text: str) -> str | None:
    found_jars: list[str] = []
    found_paths: list[str] = []

    for m in re.finditer(r"[\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar", error_text, re.IGNORECASE):
        found_jars.append(m.group(0))
    for m in re.finditer(r"(?:^|[\s\\/])mods[\\/]([\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar)", error_text, re.IGNORECASE):
        found_paths.append(m.group(1))

    ds = re.search(r"Duplicate\s*Mod[s]?[:\s]*\n((?:.{0,300}\n?){0,15})", error_text, re.IGNORECASE)
    if ds and not found_paths:
        sec = ds.group(1)
        found_paths = re.findall(r"(?:^|[\s\\/])mods[\\/]([\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar)", sec, re.IGNORECASE)
        if not found_paths:
            found_paths = re.findall(r"[\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar", sec, re.IGNORECASE)

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

        found_by_name = [n for n in ([current] + aliases) if n.lower() in error_text.lower()]

        if len(set(matched_jars)) >= 2 or len(set(matched_paths)) >= 2:
            matched = set(matched_paths) or set(matched_jars)
            fl = "\n".join(f"- `{x}`" for x in list(matched)[:5])
        elif len(set(found_by_name)) >= 2:
            matched = set()
            fl = ""
        else:
            continue

        result = f"**⚠️ 检测到同一类模组出现多个：{', '.join(found_by_name)}**\n\n"
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
