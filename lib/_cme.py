"""CME (ConcurrentModificationException) crash analysis with CMESuckMyDuck."""

import re
from pathlib import Path

from ._utils import RE_STACK, SKIP_STACK


def analyze_cme_log(log_path: Path) -> str | None:
    try:
        content = log_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeDecodeError):
        return None

    mod_traces = {}
    thread_traces = {}

    for line in content.split("\n"):
        m = re.search(r"at TRANSFORMER/([\w$]+).*?/([\w.$]+)", line)
        if m:
            mod = m.group(1)
            cls = m.group(2)
            mod_traces.setdefault(mod, set()).add(cls)

        m = re.search(r"\[([^\]]+)\].*?(?:modified|accessed|changed)", line, re.IGNORECASE)
        if m:
            key = m.group(1).strip()
            thread_traces.setdefault(key, 0)
            thread_traces[key] += 1

    if not mod_traces and not thread_traces:
        return None

    result = "**🦆 CMESuckMyDuck 分析结果**\n\n"
    result += "根据 CMESuckMyDuck.log 中的容器修改历史，检测到以下活动：\n\n"

    if thread_traces:
        sorted_threads = sorted(thread_traces.items(), key=lambda x: -x[1])
        result += "**涉及线程（按操作次数排序）：**\n"
        for t, c in sorted_threads[:5]:
            result += f"- `{t}` ({c} 次操作)\n"
        result += "\n"

    if mod_traces:
        result += "**操作涉及模组：**\n"
        for mod, classes in sorted(mod_traces.items(), key=lambda x: -len(x[1]))[:8]:
            result += f"- `{mod}` ({len(classes)} 个类)\n"

    result += (
        "\n**排查建议**\n"
        "1. 上述模组中，操作次数最多的线程和模组最可能是冲突源头\n"
        "2. 尝试禁用操作最频繁的模组，或更新到最新版\n"
        "3. 如果无法确定，将上述列表中的模组逐个禁用排查\n"
    )
    return result


def generate_cme_guide(error_text: str) -> str | None:
    stacks = RE_STACK.findall(error_text)
    meaningful = [s for s in stacks if not s[0].startswith(SKIP_STACK)]
    if not meaningful:
        return None

    target_class = meaningful[0][0].replace(".", "/")
    return (
        "**🦆 检测到并发修改异常 (CME)**\n\n"
        "标准的崩溃日志无法定位此类错误的具体来源，"
        "因为 CME 涉及多个线程同时操作，单一线程的调用栈无法反映全局。\n\n"
        "---\n\n"
        "**为解决此问题，请按以下步骤操作：**\n\n"
        "### 1. 安装 CMESuckMyDuck\n"
        "下载 [CMESuckMyDuck](https://www.mcmod.cn/class/17502.html) 模组，放入 mods 文件夹\n\n"
        "### 2. 添加 JVM 启动参数\n"
        "在 PCL 启动器中找到「设置」→「Java 虚拟机参数」，添加：\n\n"
        f"```\n-javaagent:mods/CMESuckMyDuck-<版本>.jar={target_class};<字段名>;<容器类型>;<static或nonstatic>\n```\n\n"
        f"根据崩溃调用栈，建议监视的类为 **`{target_class}`**\n\n"
        "其中：\n"
        "- `<字段名>`：请查看该类源码或反编译，找到被并发修改的容器字段名\n"
        "- `<容器类型>`：`List` / `Set` / `Map` / `Iterator` 等\n"
        "- `<static或nonstatic>`：取决于字段是否为静态成员\n\n"
        "### 3. 重现崩溃\n"
        "保存参数后启动游戏，再次触发崩溃\n\n"
        "### 4. 发送新生成的 CMESuckMyDuck.log\n"
        "将游戏目录下的 `CMESuckMyDuck.log` 发送给我，即可分析出冲突模组\n\n"
        "---\n\n"
        "**常见示例：**\n"
        "- Forge 1.20.1 SoundEngine CME：\n"
        "  `-javaagent:mods/CMESuckMyDuck-1.1.2.jar="
        "net/minecraft/client/audio/SoundEngine;f_217942_m_;Map;nonstatic`\n"
        "- 如需更详细的说明，请查阅 [MC百科页面](https://www.mcmod.cn/class/17502.html)\n"
    )
