# Changelog

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
- **路径穿越防护**：文件名 `/../` + `resolve()` 双重校验
- **JSON 内容扫描**：解压前扫描 11 种危险命令关键词
- **用户黑名单**：多次上传恶意文件自动拉黑（可配置阈值，默认 3 次）
- **流式下载**：改用 `iter_chunked(65536)` 替代 `resp.read()`，防 OOM

### 🛠 重构与优化
- **模块化拆分**：从单文件 900+ 行拆分为 `lib/` 下 10 个独立模块
- **正则模块级常量**：所有正则提取为模块级 `_RE_*` 常量，消除运行时重复编译
- **`copy.deepcopy`**：替代 `json.loads(json.dumps())` 深拷贝
- **`asyncio.Lock`**：替代 `threading.Lock` 适配异步框架
- **统一消息格式**：所有分析结果使用 `**🤖 AI 分析结果**` Markdown 格式 + 截图发送
- **CSS 纯文本模板**：替换 f-string `{{}}` 转义，消除静态分析误报
- **`_recent_files` LRU 淘汰**：上限 200 条，保留最近 100 条

### 📦 依赖变更
- 新增 `markdown>=3.0.0`（用于 Markdown → HTML 渲染）
- 移除 `Pillow`（改用 AstrBot 内置 `html_render` 截图）

### 📚 文档
- 更新 README.md：完善功能说明、安全矩阵、CME 分析流程、模块文件结构
