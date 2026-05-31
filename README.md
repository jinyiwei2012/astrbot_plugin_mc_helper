# MC Helper — Minecraft 错误报告分析插件

自动检测 PCL/PCLCE 导出的错误报告压缩包，解压读取崩溃日志，**优先调用 AI 分析**，辅以本地知识库兜底。

## 功能

- **自动检测**：用户发送 `错误报告-2026-5-31_18.30.06.zip` 格式的压缩包，自动下载、解压、分析
- **AI 优先**：全程调用 LLM 分析 `latest.log`（最多 2MB）并返回 Markdown 格式解决方案，截图发送
- **本地知识库**：内置 100+ 条常见 Minecraft 错误解决方案，按分类组织，AI 无法使用时自动兜底
- **自动学习**：AI 生成的解决方案自动入库，下次同类错误直接命中
- **重复模组检测**：自动识别 logger 中同一模组的多个版本/别名（Rubidium + Embeddium 等），指出冲突文件并给出清理步骤
- **日志位置定位**：从崩溃报告中提取坐标、Java 版本、内存、系统信息等，生成针对性解决指引
- **手动查询**：`/mc_check <错误信息>` 手动分析任意错误文本
- **知识库管理**：`/mc_add_solution <关键词> <解决方案>` 手动添加方案（支持含空格的完整描述）
- **群聊白名单**：可选限制仅特定群聊可使用本插件（通过配置 `whitelist_groups`）

## 安装

1. 将 `astrbot_plugin_mc_helper` 目录放入 AstrBot 的 `data/plugins/` 下
2. 在 AstrBot WebUI 的插件管理页点击「重载插件」
3. 确认日志输出：`MC Helper 插件已加载，本地方案库共 XX 条`

依赖：`aiohttp`、`markdown`（插件市场安装时会自动安装）

## 使用方法

### 分析错误报告

1. 在 PCL / PCLCE 启动器中点击「导出错误报告」
2. 将生成的 `错误报告-2026-5-31_18.30.06.zip` 发送给机器人
3. 机器人自动下载、解压、优先调用 AI 分析，结果以截图形式回复
4. 若 AI 不可用，自动降级为本地知识库匹配

### 指令

| 指令 | 说明 |
|------|------|
| `/mc_help` | 查看帮助 |
| `/mc_check` | 手动分析错误文本（直接发送错误报告压缩包即可自动分析） |
| `/mc_add_solution <关键词> <解决方案>` | 添加解决方案到知识库（解决方案支持含空格） |

## 配置

在 AstrBot WebUI → 插件管理 → 点击插件卡片上的「配置」按钮，可调整以下参数：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ai_model_provider` | 指定用于分析的 LLM 提供商（留空则使用当前会话的模型） | 空 |
| `latest_log_max_bytes` | 发送给 AI 的 latest.log 上限 | 2000000 |
| `ai_result_max_chars` | AI 回复显示长度 | 2000 |
| `ai_source_fallback_chars` | 无 latest.log 时发送的其他日志上限 | 100000 |
| `auto_save_category` | AI 方案自动入库的分类名 | AI生成 |
| `download_timeout` | 下载压缩包超时（秒） | 120 |
| `whitelist_groups` | 白名单群聊 ID 列表（空则不限制） | [] |
| `max_malicious_uploads` | 用户上传恶意压缩包达到此次数后自动拉黑 | 3 |

## 安全

插件内置多层安全防护：

| 防护层 | 说明 |
|--------|------|
| **文件类型白名单** | 只提取 `.log` / `.txt` / 安全 `.json`，其余文件静默跳过 |
| **黑名单拦截** | `.exe` `.dll` `.sh` `.vbs` `.js` 等可执行文件直接拒绝整个压缩包 |
| **Zip Bomb 防护** | 单文件 ≤ 10MB，总量 ≤ 50MB，文件数 ≤ 1000 |
| **路径穿越防护** | 文件名以 `/` 开头或含 `/../` 立即拒绝 |
| **JSON 内容扫描** | 解压前扫描 `.json` 内容，含危险命令（powershell、wget 等）则拒绝 |
| **用户黑名单** | 多次上传恶意文件的用户自动拉黑（默认 3 次触发），拦截所有后续请求 |
| **文件定期清理** | 7 天前的解压文件自动删除 |

## 文件结构

```
astrbot_plugin_mc_helper/
├── metadata.yaml            # 插件元数据
├── main.py                  # 主逻辑（877 行）
├── _conf_schema.json        # 插件配置
├── requirements.txt         # 依赖
├── data/
│   ├── solutions.json       # 本地解决方案知识库（100+ 条）
│   └── duplicate_mods.json  # 常见重复/冲突模组对照表（26 组）
```

运行时产生的数据：

```
{get_astrbot_data_path()}/plugin_data/astrbot_plugin_mc_helper/
├── solutions.json           # 运行时方案库（含 AI 自动保存的条目）
├── user_blacklist.json      # 用户黑名单数据
├── screenshots/             # 截图缓存（自动清理）
└── 错误报告/                 # 下载的错误报告（7 天自动清理）
```

## 本地知识库

内置知识库位于 `data/solutions.json`，按分类组织：

- 内存/性能
- 网络连接
- 模组问题
- Java/环境
- 存档/世界
- 显卡/渲染
- 实体/方块
- 并发/冲突
- 登录/验证
- 启动/崩溃
- 文件/IO
- 其他

重复模组对照表位于 `data/duplicate_mods.json`，涵盖 26 组常见的同名不同分支/改名模组（如 Rubidium→Embeddium、Hydrogen→FerriteCore 等）。

## 数据存储

- **方案库**：`data/plugin_data/astrbot_plugin_mc_helper/solutions.json`
- **重复模组对照表**：从插件目录 `data/duplicate_mods.json` 加载
- **用户黑名单**：`data/plugin_data/astrbot_plugin_mc_helper/user_blacklist.json`
- **错误报告截图**：`data/plugin_data/astrbot_plugin_mc_helper/screenshots/`

卸载插件前建议备份以上目录。
