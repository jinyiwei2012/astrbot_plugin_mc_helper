"""Module-level constants and compiled regex patterns."""

import re

# Jar file patterns
RE_JAR_PATH = re.compile(
    r"(?:^|[\s\\/])mods[\\/]([\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar)",
    re.IGNORECASE,
)
RE_JAR_NAME = re.compile(r"[\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar", re.IGNORECASE)
RE_MOD_FILE = re.compile(
    r"(?:Mod|Mod File|File):\s*([\w\-+]+(?:mc[\w\-+.]+)?\d[\w.+]*\.jar)",
    re.IGNORECASE,
)

# Error report patterns
RE_DUP_SECTION = re.compile(
    r"Duplicate\s*Mod[s]?[:\s]*\n((?:.{0,300}\n?){0,15})",
    re.IGNORECASE,
)
RE_EXIT_CODE = re.compile(r"Exit Code[:\s]*(-?\d+)")
RE_STACK = re.compile(r"at\s+([\w.]+)\(([^:]+:\d+)\)")
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
RE_MOD_ID = re.compile(r"([a-z_]+:[a-z_]+)")
RE_EXCEPTION = re.compile(r"(?:Caused by|Description)[:\s]*([^\n]+)")
RE_ERROR_CLS = re.compile(
    r"(java\.\w+(?:\.\w+)+Error|java\.\w+(?:\.\w+)+Exception|"
    r"IllegalStateException|NullPointerException|"
    r"ConcurrentModificationException)[:\s]*([^\n]*)"
)

# Skip lists
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
SKIP_MOD_ID = {
    "minecraft",
    "java",
    "net",
    "com",
    "org",
    "cpw",
    "it",
    "de",
    "fr",
    "io",
    "pl",
}

FAIL_PREFIXES = (
    "无法获取 AI 模型",
    "AI 未能生成有效的解决方案",
    "AI 分析调用失败",
)

# Security
BLACKLIST_EXTS = {
    ".exe",
    ".com",
    ".msi",
    ".scr",
    ".sh",
    ".bin",
    ".dll",
    ".so",
    ".dylib",
    ".vbs",
    ".js",
    ".cmd",
    ".ps1",
    ".jar",
}
DANGEROUS_CMDS = (
    "powershell",
    "curl",
    "wget",
    "certutil",
    "format",
    "reg ",
    "mshta",
    "rundll32",
    "wmic",
    "cscript",
    "schtasks",
)

# Limits
MAX_ZIP_FILES = 1000
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_EXTRACT_SIZE = 50 * 1024 * 1024
MAX_RECENT_FILES = 200
RECENT_FILES_KEEP = 100
