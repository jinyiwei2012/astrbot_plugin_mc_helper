# MC Helper — Minecraft 错误报告分析插件

自动检测 PCL/PCLCE 导出的错误报告压缩包，解压读取崩溃日志，匹配本地知识库或调用 AI 给出解决方案。

## 功能

- **自动检测**：用户发送命名格式为 `错误报告-2026-5-31_18.30.06.zip` 的压缩包，自动下载、解压、分析
- **本地知识库**：内置 96+ 条常见 Minecraft 错误解决方案，按分类组织
- **AI 增强**：本地无匹配时，调用 LLM 分析 `latest.log`（最多 2MB）并返回详细方案
- **自动学习**：AI 生成的解决方案自动入库，下次同类错误直接命中
- **手动查询**：`/mc_check <错误信息>` 手动分析任意错误文本
- **知识库管理**：`/mc_add_solution <关键词> <方案>` 手动添加方案

## 安装

1. 将 `astrbot_plugin_mc_helper` 目录放入 AstrBot 的 `data/plugins/` 下
2. 在 AstrBot WebUI 的插件管理页点击「重载插件」
3. 确认日志输出：`MC Helper 插件已加载，本地方案库共 XX 条`

依赖：`aiohttp`（插件会自动安装）

## 使用方法

### 分析错误报告

1. 在 PCL / PCLCE 启动器中点击「导出错误报告」
2. 将生成的 `错误报告-2026-5-31_18.30.06.zip` 发送给机器人
3. 机器人回复提示信息后，**引用该压缩包**并发送 `/mc_check`
4. 机器人自动下载、解压、分析并返回解决方案

### 指令

| 指令 | 说明 |
|------|------|
| `/mc_help` | 查看帮助 |
| `/mc_check`（引用压缩包） | 分析引用的错误报告 |
| `/mc_check <错误文本>` | 手动分析错误文本 |
| `/mc_add_solution <关键词> <方案>` | 添加解决方案到知识库 |

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

## 文件结构

```
astrbot_plugin_mc_helper/
├── metadata.yaml            # 插件元数据
├── main.py                  # 主逻辑
├── _conf_schema.json        # 插件配置
├── requirements.txt         # 依赖
└── data/
    ├── solutions.json       # 本地解决方案知识库
    └── 错误报告/             # 下载的错误报告存档
```

## 本地知识库

知识库位于 `data/plugin_data/astrbot_plugin_mc_helper/solutions.json`，按分类组织：

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
- AI生成（自动保存的 AI 分析结果）

## 数据存储

- **解决方案库**：`data/plugin_data/astrbot_plugin_mc_helper/solutions.json`
- **错误报告存档**：`data/plugin_data/astrbot_plugin_mc_helper/错误报告/`

卸载插件前建议备份以上目录。
