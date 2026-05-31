"""Error detail extraction, enrichment, and local solution matching."""

import re
from typing import Optional


from ._utils import (
    RE_JAR_PATH,
    RE_JAR_NAME,
    RE_MOD_FILE,
    RE_DUP_SECTION,
    RE_EXIT_CODE,
    RE_STACK,
    RE_COORDS,
    RE_MEMORY,
    RE_SERVER,
    RE_PATH,
    RE_JAVA,
    RE_OS,
    RE_MOD_ID,
    RE_EXCEPTION,
    RE_ERROR_CLS,
    SKIP_STACK,
    SKIP_MOD_ID,
)


def extract_report_details(error_text: str) -> list[str]:
    details = []

    jar_paths = RE_JAR_PATH.findall(error_text)
    if jar_paths:
        details.append("涉及文件：" + "、".join(set(jar_paths[:3])))

    mod_names = RE_MOD_FILE.findall(error_text)
    if mod_names and not jar_paths:
        details.append("涉及模组：" + ", ".join(set(mod_names[:3])))

    mod_ids = set()
    for m in RE_MOD_ID.findall(error_text):
        parts = m.split(":")
        if parts[0] not in SKIP_MOD_ID:
            mod_ids.add(m)
    mod_id_list = sorted(mod_ids)[:4]
    if mod_id_list:
        details.append("涉及模组 ID：" + "、".join(mod_id_list))

    dup_section = RE_DUP_SECTION.search(error_text)
    if dup_section:
        dup_files = RE_JAR_NAME.findall(dup_section.group(1))
        if dup_files:
            details.append("重复模组：" + "、".join(set(dup_files[:5])))

    exit_code = RE_EXIT_CODE.search(error_text)
    if exit_code:
        details.append("退出代码：Exit Code " + exit_code.group(1))

    exception = RE_EXCEPTION.search(error_text)
    if exception:
        msg = exception.group(1).strip()
        if msg and len(msg) < 120:
            details.append("错误信息：{}".format(msg))

    error_keyword = RE_ERROR_CLS.search(error_text)
    if error_keyword:
        ex_type = error_keyword.group(1).split(".")[-1]
        ex_msg = error_keyword.group(2).strip()[:80] if error_keyword.group(2) else ""
        if ex_msg:
            details.append("异常：{} - {}".format(ex_type, ex_msg))
        else:
            details.append("异常：{}".format(ex_type))

    all_stacks = RE_STACK.findall(error_text)
    meaningful = [s for s in all_stacks if not s[0].startswith(SKIP_STACK)]
    if meaningful:
        details.append("异常位置：{} ({})".format(meaningful[0][0], meaningful[0][1]))

    coords = RE_COORDS.findall(error_text)
    if coords:
        details.append("坐标：({}, {}, {})".format(coords[0][0], coords[0][1], coords[0][2]))

    memory = RE_MEMORY.findall(error_text)
    if memory:
        details.append("内存：{} {}".format(memory[0][0], memory[0][1]))

    servers = RE_SERVER.findall(error_text)
    if servers:
        details.append("服务器：{}".format(servers[0]))

    paths = RE_PATH.findall(error_text)
    if paths:
        details.append("路径：{}".format(paths[0]))

    java_versions = RE_JAVA.findall(error_text)
    if java_versions:
        details.append("Java 版本：{}".format(java_versions[0]))

    os_info = RE_OS.findall(error_text)
    if os_info:
        details.append("系统：{}".format(os_info[0].strip()))

    return details


def enrich_solution(solution: str, error_text: str) -> str:
    details = extract_report_details(error_text)
    result = solution + "\n\n---"
    tips = []

    if details:

        def _val(d):
            return d.split("：", 1)[1] if "：" in d else ""

        rules = [
            (
                ("涉及文件", "涉及模组"),
                lambda d: (
                    f"打开 .minecraft/mods 文件夹，找到上面对应的文件，"
                    f"{'、'.join([f for f in _val(d).replace('、', ' ').split() if '.jar' in f.lower()][:3])}"
                    f"。检查是否需要删除旧版或解决冲突。"
                ),
            ),
            (
                ("坐标",),
                lambda d: (
                    f"前往坐标 {_val(d)} 检查。如果是方块实体崩溃，拆掉该位置的方块；"
                    f"如果是实体崩溃，用 /kill @e 清除附近的实体。"
                ),
            ),
            (
                ("内存",),
                lambda d: (
                    f"当前内存分配为 {_val(d)}。如果游戏卡顿或内存不足，"
                    f"在 PCL 设置中将内存调大（如 4096MB 或 6144MB）。"
                ),
            ),
            (
                ("Java 版本",),
                lambda d: (
                    f"当前 Java 版本为 {_val(d)}。如果遇到不兼容错误，"
                    f"在 PCL 设置中更换 Java 版本（MC 1.17+ 需要 Java 17 或 21）。"
                ),
            ),
            (
                ("服务器",),
                lambda d: (f"服务器地址：{_val(d)}。如果是连接问题，检查地址是否正确、服务器是否开启、网络是否正常。"),
            ),
            (
                ("退出代码",),
                lambda d: (
                    f"退出代码 {_val(d)}。请对照本地方案库中的 Exit Code 相关条目排查，"
                    f"通常与内存、显卡驱动或 Java 配置有关。"
                ),
            ),
            (
                ("重复模组",),
                lambda d: (
                    "检测到重复模组！打开 .minecraft/mods 文件夹，搜到上面对应的文件名，只保留一个版本，删除其余。"
                ),
            ),
        ]

        for d in details:
            for prefixes, handler in rules:
                if d.startswith(prefixes):
                    t = handler(d)
                    if t:
                        tips.append(t)
                    break
            else:
                if d.startswith("路径") and ".mca" in d:
                    tips.append(
                        "发现区块文件(.mca)损坏，用 MCA Selector 打开该文件，"
                        "找到损坏的区块并删除（游戏会自动重新生成）。"
                    )
                elif d.startswith("路径") and ".json" in d:
                    tips.append("发现配置文件(.json)异常，尝试删除该配置文件（游戏会自动重建默认配置）。")
                elif d.startswith("异常位置"):
                    try:
                        loc = _val(d)
                        cls = loc.split("(")[0].strip() if "(" in loc else loc
                        short = cls.split(".")[-1] if "." in cls else cls
                        tips.append(f"错误出现在 {short} 类中。如果该类和模组相关，尝试更新或删除对应的模组。")
                    except Exception:
                        pass
                elif d.startswith("系统"):
                    if "linux" in _val(d).lower() or "mac" in _val(d).lower():
                        tips.append("你正在使用非 Windows 系统，某些模组可能不兼容。检查模组是否支持你的操作系统。")

    result += "\n\n---"
    if details:
        result += "\n\n**📋 错误详情**"
        for d in details:
            result += "\n- " + d

    if tips:
        result += "\n\n**🔧 定位解决**"
        for t in tips[:5]:
            result += "\n- " + t

    return result


def search_local_solutions(solutions_db: dict, error_text: str) -> Optional[str]:
    for category, entries in solutions_db.items():
        for pattern, entry in entries.items():
            solution = entry["solution"] if isinstance(entry, dict) else entry
            if re.search(re.escape(pattern), error_text, re.IGNORECASE):
                return solution

    exit_code_match = re.search(r"Exit Code[:\s]*(-?\d+)", error_text)
    if exit_code_match:
        ec = exit_code_match.group(1)
        for category, entries in solutions_db.items():
            for pattern, entry in entries.items():
                solution = entry["solution"] if isinstance(entry, dict) else entry
                if f"Exit Code {ec}" in pattern:
                    return solution

    return None


def extract_error_key(error_text: str) -> Optional[str]:
    match = re.search(
        r"(?:Caused by:\s*)?(java\.\w+(?:\.\w+)+Error|java\.\w+(?:\.\w+)+Exception"
        r"|Exit Code[:\s]*-?\d+|Couldn't\s+\w+|Failed to \w+"
        r"|Connection \w+|Internal Exception|Missing \w+)",
        error_text,
    )
    if match:
        return match.group(1).strip()

    for line in error_text.split("\n"):
        line = line.strip()
        if line.startswith("java.") or "Exception" in line or "Error" in line:
            words = line.split()[:5]
            key = " ".join(words)
            if len(key) > 10:
                return key

    return None
