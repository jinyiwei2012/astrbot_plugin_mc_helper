# Changelog

## v1.1.1 (2026-06-01)

### 🔧 Bug 修复
- **`_duplicate_mods.py` 捕获组缺失**：正则缺少 `()` 导致 `group(1)` 运行时崩溃（`IndexError`）
- **`_security.py` ZipFile 传参错误**：`ZipFile.read()` 第二参数为密码而非字节数，大 JSON 文件必崩
- **`_security.py` JSON 扫描**：仅扫描头部 256KB 可被绕过，改为头尾各半采样
- **`_security.py` DNS 无超时**：`getaddrinfo` 卡死时无超时，加 `asyncio.wait_for(..., timeout=10)`
- **`_security.py` Unicode 同形字绕过**：文件名后缀检查可通过全角字符绕过，加 `unicodedata.normalize("NFKC")`
- **`_handlers.py` uid 不一致**：`record_malicious` 用消毒 uid 但 `is_blacklisted` 查原始 uid，黑名单永不命中
- **`_handlers.py` 配置键错位**：`mc_config` 用原始 uid 存储但 `_save_report` 用消毒 uid 读取，配置永久降级

### 🛠 重构与优化
- **移除 `main.py:ask_ai` 薄包装**：`_handlers.py` 直调 `lib._ai.ask_ai`
- **`_collect_files` 抽取**：`on_message` 和 `_find_file` 复用相同文件提取逻辑
- **`_PinnedResolver` 死字段**：移除未使用的 `loop` 参数
- **`_file_utils.py` 死代码**：移除从未被调用的 `cleanup_old_files`
- **`_renderer.py` XSS 防护**：降级路径和 `md_to_html` 添加 `html.escape`
- **`_save_report` 扁平存储**：丢失子目录结构改为保留相对路径

### 📚 文档
- **全面中文注释**：所有模块、类、函数、关键逻辑添加中文注释
- **`CHANGELOG.md`**：补充本轮修复记录

## v1.1.0 (2026-06-01)

### ✨ 新功能
- **AI 优先分析**：全程调用 LLM 进行分析，AI 不可用时自动降级为本地知识库兜底
- **CME 崩溃分析**：检测 `ConcurrentModificationException` 时，自动引导安装 CMESuckMyDuck 模组并生成 JVM 参数；已存在 CMESuckMyDuck.log 时直接分析冲突模组
- **重复模组检测**：自动识别同一模组的多个版本/别名（Rubidium + Embeddium 等），列出冲突文件并给出清理步骤
- **日志位置定位**：从崩溃报告中提取坐标、Java 版本、内存、系统信息等，生成针对性解决指引
- **PCLCE 格式支持**：同时支持 PCL（`YYYY-M-D`）和 PCLCE（`MM-DD-YYYY`）两种日期格式
- **群聊白名单**：通过配置 `whitelist_groups` 限制仅特定群聊可使用本插件

### 🔒 安全增强
- **文件类型白名单**：只提取 `.log` / `.txt` / 安全 `.json`，其余文件静默跳过
- **黑名单拦截**：`.exe` `.dll` `.sh` `.vbs` `.js` 等可执行文件直接拒绝整个压缩包
- **Zip Bomb 防护**：文件数 ≤ 1000、单文件 ≤ 10MB、总量 ≤ 50MB
- **下载大小限制**：`download_zip` 增加 200MB 上限，防磁盘 DoS
- **路径穿越防护**：文件名 `/../` + `resolve()` 双重校验
- **JSON 内容扫描**：解压前扫描 11 种危险命令关键词；超大 JSON 分段读取防 OOM
- **用户黑名单**：多次上传恶意文件自动拉黑（可配置阈值，默认 3 次）
- **SSRF 防护**：DNS 预解析 + Private IP 拦截 + DNS Pinning（`_PinnedResolver`）
- **流式下载**：改用 `iter_chunked(65536)` 替代 `resp.read()`，防 OOM

### 🛠 重构与优化
- **模块化拆分**：从单文件 900+ 行拆分为 `lib/` 下 10 个独立模块
- **正则模块级常量**：所有正则提取为模块级 `_RE_*` 常量，消除运行时重复编译
- **`copy.deepcopy`**：替代 `json.loads(json.dumps())` 深拷贝
- **`asyncio.Lock`**：替代 `threading.Lock` 适配异步框架
- **统一消息格式**：所有分析结果使用 `**🤖 AI 分析结果**` Markdown 格式 + 截图发送
- **CSS 纯文本模板**：替换 f-string `{{}}` 转义，消除静态分析误报
- **`_recent_files` LRU 淘汰**：上限 200 条，保留最近 100 条
- **`_load_json` 提取**：`load_db` / `load_duplicate_mods` 共用 `_load_json` 消除重复
- **`enrich_solution` 重构**：拆分为 10 个职责单一的辅助函数 + `_TIP_RULES` 配置表

### 🔧 Bug 修复
- **JAR 正则**：`\d` 改为可选 `(?:\d[\w.+]*)?`，`MyMod.jar` 等纯字母 mod 文件可被匹配
- **Mod ID 正则**：`[a-z_]+` → `[a-z0-9_]+`，支持含数字的 Mod ID（如 `3dskinlayers`）
- **堆栈正则**：`[\w.]+` → `[\w.$]+`，支持内部类堆栈（`Outer$Inner`）
- **SKIP_MOD_ID**：移除 `com`/`org`/`net` 等 Java 包名前缀，消除极低概率的误过滤
- **重复模组检测**：`found_by_name` 结果去重，避免列表中出现重复名称
- **双分隔符**：`enrich_solution` 合并两个连续 `---` 为单个
- **用户配置写盘**：`set_user_cfg` 改为延迟写（`_config_dirty`），`terminate` 时落盘

### 📦 依赖变更
- 新增 `markdown>=3.0.0`（用于 Markdown → HTML 渲染）
- 移除 `Pillow`（改用 AstrBot 内置 `html_render` 截图）

### 📚 文档
- 更新 README.md：完善功能说明、安全矩阵、CME 分析流程、模块文件结构
