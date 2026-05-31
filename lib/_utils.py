"""模块级常量和预编译正则表达式，供各模块共享"""

import re

# ── Jar 文件名模式 ──
# 匹配类似 "OptiFine_1.20.1.jar" 或 "sodium-fabric-mc1.20.1-0.5.8.jar" 的文件名
JAR_RE = r"[\w\-+]+(?:mc[\w\-+.]+)?(?:\d[\w.+]*)?\.jar"
# 匹配 mods/ 目录下的 jar 路径
RE_JAR_PATH = re.compile(
    r"(?:^|[\s\\/])mods[\\/]" + JAR_RE,
    re.IGNORECASE,
)
# 匹配任意位置的裸 jar 文件名
RE_JAR_NAME = re.compile(JAR_RE, re.IGNORECASE)
# 匹配 "Mod: filename.jar" 或 "File: filename.jar" 行
RE_MOD_FILE = re.compile(
    r"(?:Mod|Mod File|File):\s*" + JAR_RE,
    re.IGNORECASE,
)

# ── 错误报告提取模式 ──
RE_DUP_SECTION = re.compile(
    r"Duplicate\s*Mod[s]?[:\s]*\n((?:.{0,300}\n?){0,15})",
    re.IGNORECASE,
)
RE_EXIT_CODE = re.compile(r"Exit Code[:\s]*(-?\d+)")
RE_STACK = re.compile(r"at\s+([\w.$]+)\(([^:]+:\d+)\)")
RE_COORDS = re.compile(r"(?:Tile Entity at|Block at|Position)\s*\[?(-?\d+)[,; ]\s*(-?\d+)[,; ]\s*(-?\d+)\]?")
RE_MEMORY = re.compile(r"(\d+)\s*(MB|GB|MiB|GiB)", re.IGNORECASE)
RE_SERVER = re.compile(
    r"(?:^|\n)(?:Server|Server IP|Host|Server Address)[:\s]*([\w.\-]+(?::\d+)?)",
    re.IGNORECASE,
)
RE_PATH = re.compile(
    r"(?:\.minecraft[\\/](?!libraries)[\w\\/.\-]+(?:\.log|\.txt|\.json|\.jar|\.zip|\.mca))",
    re.IGNORECASE,
)
RE_JAVA = re.compile(r"Java\s*(?:Version|VM|Runtime)[:\s]*([\d.]+)", re.IGNORECASE)
RE_OS = re.compile(r"Operating\s+System[:\s]*([^\n]+)", re.IGNORECASE)
RE_MOD_ID = re.compile(r"([a-z_][a-z0-9_]*:[a-z_][a-z0-9_]*)")
RE_EXCEPTION = re.compile(r"(?:Caused by|Description)[:\s]*([^\n]+)")
RE_ERROR_CLS = re.compile(
    r"(java\.\w+(?:\.\w+)+Error|java\.\w+(?:\.\w+)+Exception|"
    r"IllegalStateException|NullPointerException|"
    r"ConcurrentModificationException)[:\s]*([^\n]*)"
)

# ── 跳过滤列表 ──
# 定位 mod 相关崩溃时忽略的框架调用栈
SKIP_STACK = (
    "cpw.mods.modlauncher",
    "cpw.mods.bootstraplauncher",
    "java.lang",
    "jdk.internal",
    "sun.reflect",
    "net.minecraft.launchwrapper",
    "org.spongepowered.asm",
    "net.minecraftforge.fml.loading",
)
# 始终存在且不可能是根因的模组 ID
SKIP_MOD_ID = {
    "minecraft",
    "java",
    "cpw",
}

# AI 调用失败时的返回前缀，用于判断是否降级到本地方案
FAIL_PREFIXES = (
    "无法获取 AI 模型",
    "AI 未能生成有效的解决方案",
    "AI 分析调用失败",
)

# ── 安全限制 ──
# 上传压缩包中禁止出现的文件扩展名
BLACKLIST_EXTS = {
    ".exe", ".com", ".msi", ".scr", ".sh", ".bin",
    ".dll", ".so", ".dylib", ".vbs", ".js", ".cmd",
    ".ps1", ".jar",
}
# 扫描 .json 文件时查找的危险命令关键字
DANGEROUS_CMDS = {
    "powershell", "curl", "wget", "certutil", "format",
    "reg ", "mshta", "rundll32", "wmic", "cscript", "schtasks",
}

MAX_ZIP_FILES = 1000
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_EXTRACT_SIZE = 50 * 1024 * 1024
MAX_RECENT_FILES = 200
RECENT_FILES_KEEP = 100
