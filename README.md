# 🧬 devPartner - 全能 MCP 数据服务 v3.0

> **AI-Client-Driven 架构**：MCP 提供数据，AI 客户端自己的 LLM 做分析
> 比本地 Ollama 7B 模型强大 100 倍，支持远程部署

## ✨ 核心特性

| 能力 | 描述 | 版本 |
|------|------|------|
| 🛠️ **工具聚合** | 文件/GitHub/SQLite/Git/URL/思考/记忆/Context7 | v1.0 |
| 📝 **对话日志** | 自动记录/每日总结/间隙检测/客户端追踪 | v1.0 |
| 💬 **跨AI对话** | CodeBuddy ↔ Trae ↔ devPartner 三方圆桌 | v1.0 |
| 🧠 **思维导图** | Mermaid 格式生成、HTML 渲染 | v1.0 |
| 🔄 **涡轮效应** | 系统自改进、自动优化配置 | v1.0 |
| 🔍 **MCP发现** | 自动扫描/测试/集成新MCP服务 | v1.0 |
| 🧬 **自我进化** | 代码自更新/热重载/备份回滚 | v1.0 |
| 📊 **AI分析接口** | 提供原始数据给AI客户端自行分析 ★ | **v3.0 新增** |
| 🆔 **身份识别** | CodeBuddy/Trae/Cursor 自动检测与注册 | v2.0 |
| ☁️ **云盘同步** | 坚果云/阿里云盘 WAL防冲突 SQLite存储 | v2.0 |
| 🧙 **配置向导** | 智能环境扫描/路径检测/引导配置 | v2.0 |
| 🎯 **AI优化** | 客户端MCP/Rules分析/冗余检测/配置建议 | v2.0 |

## 🎯 v3.0 架构理念

```
┌─────────────────────────────────────────────────────────┐
│                    v2.0 (旧架构)                          │
│  AI客户端 → MCP工具 → 本地 Ollama 分析 → 结果             │
│  问题：Ollama太慢、无法远程部署、7B模型分析质量差            │
├─────────────────────────────────────────────────────────┤
│                    v3.0 (新架构)                          │
│  AI客户端调用 get_daily_work_data() 获取原始数据            │
│         ↓                                                │
│  AI客户端用自己的 LLM（Claude/GPT）分析数据                 │
│         ↓                                                │
│  调用 save_daily_analysis() 保存结果                       │
│                                                          │
│  优势：                                                   │
│  ✅ 分析质量：LLM >>>> 本地 Ollama 7B                      │
│  ✅ 速度：无需等待本地推理                                   │
│  ✅ 部署：支持 ModelScope/Railway/Render 远程部署            │
│  ✅ 免费：MCP 服务 + AI客户端 LLM = 全免费                   │
└─────────────────────────────────────────────────────────┘
```

## 🚀 快速开始

### 前置要求
- Python 3.10+
- Node.js (用于部分 npm MCP 服务，可选)
- Git (用于 git 工具)

### 安装与运行

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动服务
python server.py

# 或使用批处理
start.bat
```

### Docker 部署

```bash
docker build -t devpartner .
docker run -d -p 5000:5000 --name devpartner devpartner
```

### ModelScope 部署

详见 [MODELSCOPE_DEPLOY.md](./MODELSCOPE_DEPLOY.md)

## 📋 AI 客户端连接配置

### CodeBuddy

编辑 `%USERPROFILE%\.codebuddy\mcp.json`：

```json
{
  "mcpServers": {
    "devpartner": {
      "type": "sse",
      "url": "http://localhost:5000/sse"
    }
  }
}
```

### Trae

编辑项目目录下 `.trae/mcp.json`，配置同上。

### 远程部署

将 URL 替换为部署地址：
```json
{
  "type": "sse",
  "url": "https://your-app.modelscope.cn/sse"
}
```

## 📊 AI-Client-Driven 工作流

### 每日总结流程

AI 客户端（CodeBuddy）使用以下 MCP 工具完成每日总结：

```
Step 1: get_work_schema_guide()
         → 了解数据结构和分析指南

Step 2: get_daily_work_data("2026-06-26")
         → 获取今日所有工作数据（对话记录、日志、统计、思考历程）

Step 3: AI 用自己的 LLM 分析数据
         → 总结今日工作、提炼经验教训、识别危险信号、规划明日

Step 4: save_daily_analysis(analysis_json)
         → 将分析结果保存到数据库 + 生成 Markdown 报告
```

### 周度总结

```
get_weekly_work_data()
  → 获取最近 7 天的汇总数据
  → AI 分析趋势和模式
  → save_daily_analysis() 保存周报
```

## 📁 项目结构

```
devPartner/
├── server.py                    # 主入口 - FastMCP 服务 (70+ 工具, 18 分类)
├── config.yaml                  # 配置文件 (v3.0 移除Ollama)
├── requirements.txt             # Python 依赖 (v3.0 移除Ollama相关)
├── Dockerfile                   # Docker 镜像构建 ★v3.0
├── MODELSCOPE_DEPLOY.md         # ModelScope 部署指南 ★v3.0
├── start.bat                    # Windows 启动脚本
├── README.md                    # 本文件
│
├── core/                        # 核心引擎
│   ├── config.py               # 配置管理 (YAML + 环境变量 + 热重载)
│   ├── database.py             # SQLite (WAL模式 + 客户端追踪)
│   ├── identity.py             # 多AI身份识别
│   ├── cloud_sync.py           # 云盘同步存储
│   ├── rule_engine.py          # 规则引擎 (嵌入式 + 触发检测)
│   └── evolution.py            # 自我进化引擎 (更新 + 热重载)
│
├── tools/                       # 工具层
│   ├── filesystem.py           # 原生文件系统 (读/写/搜索/列表)
│   ├── native_tools.py         # 原生工具 (Git/SQLite/URL/记忆/命令)
│   └── subprocess_tools.py     # Subprocess 代理 (GitHub/Context7)
│
├── services/                    # 服务层
│   ├── log_service.py          # 日志记录与管理
│   ├── dialogue_service.py     # 跨AI对话管理
│   ├── mindmap_service.py      # 思维导图生成
│   ├── discovery_service.py    # MCP 服务自动发现
│   ├── setup_service.py        # 配置向导
│   └── ai_optimizer.py         # AI配置优化建议
│
├── skills/                      # 技能模块
│   ├── daily_summary.py        # ★v3.0 数据驱动每日总结
│   └── self_iterate.py         # ★v3.0 数据驱动自我迭代
│
└── data/                        # 运行时数据 (自动创建)
    ├── devpartner.db            # 本地数据库
    ├── daily_logs/              # 每日日志
    ├── mindmaps/                # 思维导图输出
    └── backups/                 # 代码备份
```

## 🔧 工具清单 (70+ 工具, 18 个分类)

### 1-5: 基础工具聚合
- **文件系统** (5): `fs_read_file`, `fs_write_file`, `fs_list_directory`, `fs_search_files`, `fs_search_content`
- **Git操作** (3): `git_status`, `git_log`, `git_diff`
- **网络数据库** (2): `fetch_url`, `db_query`
- **思考记忆** (4): `sequential_think`, `save_memory`, `get_memory`, `list_memories`
- **外部搜索** (3): `github_search_code`, `github_search_repositories`, `context7_search`

### 6-8: 日志与协作
- **对话日志** (4): `log_conversation`, `read_daily_log`, `list_logs`, `check_log_gaps`
- **跨AI对话** (5): `check_cross_dialogue`, `read_cross_dialogue`, `write_cross_dialogue`, `reply_cross_dialogue`, `mark_dialogue_read`
- **思维导图** (3): `generate_mindmap`, `generate_mindmap_from_tree`, `list_mindmaps`

### 9: ★ AI分析数据接口 (v3.0 新增，替代 Ollama)
- `get_daily_work_data` - 获取每日工作原始数据
- `save_daily_analysis` - 保存 AI 分析结果
- `get_weekly_work_data` - 获取周度汇总数据
- `get_work_schema_guide` - 获取数据分析和保存指南

### 10-14: 系统管理
- **自我迭代** (2): `run_self_iterate`, `get_pending_improvements`
- **MCP发现** (3): `discover_mcp_servers`, `list_known_mcp_servers`, `test_mcp_server`
- **自我进化** (6): `self_upgrade`, `self_create_file`, `self_hot_reload`, `self_diagnose`, `get_system_status`, `get_evolution_history`
- **规则引擎** (3): `get_rules_summary`, `detect_rules`, `execute_system_command`
- **数据查询** (2): `get_db_stats`, `search_conversations`

### 15-18: v2.0 新增
- **身份识别** (4): `devpartner_register`, `devpartner_whoami`, `devpartner_list_clients`, `devpartner_detect_client`
- **配置向导** (5): `devpartner_setup`, `devpartner_scan`, `devpartner_apply_config`, `devpartner_generate_mcp_snippet`, `devpartner_validate_path`
- **云同步** (3): `devpartner_cloud_info`, `devpartner_check_sync_status`
- **AI优化** (2): `devpartner_analyze_ai`, `devpartner_get_suggestions`

## 🔄 与 CodeBuddy 本地配置的关系

devPartner 作为远程 MCP 服务，可**完全替代**以下本地配置：

| 本地配置 | devPartner MCP 工具 |
|---------|-------------------|
| `process_daily.py` (Ollama总结) | `get_daily_work_data` + AI LLM → `save_daily_analysis` |
| `hook_log_writer.py` (日志写入) | `log_conversation` 工具 |
| `cross_dialogue_hub.py` (对话检测) | `check_cross_dialogue` / `read_cross_dialogue` |
| `auto-log-conversation` rule | 规则引擎 + `log_conversation` 工具 |
| `turbo-effect` rule | `run_self_iterate` 工具 |
| Ollama 本地模型 | ❌ 不再需要！AI客户端LLM替代 |

## 🆓 完全免费方案

| 组件 | 费用 | 说明 |
|------|------|------|
| devPartner MCP | 免费 | 开源，可自部署 |
| ModelScope 部署 | 免费 | 测试环境 |
| AI客户端 LLM | 免费 | CodeBuddy/Trae 自带 |
| 坚果云同步 | 免费 | 数据多设备同步 |
| 总计 | **$0** | 全免费技术栈 |

## 📝 版本历史

- v3.0.0 (2026-06-26): ★ **AI-Client-Driven 架构**
  - ❌ 移除 Ollama 依赖（太慢、不支持远程部署）
  - ✅ 新增 4 个 AI分析数据接口工具
  - ✅ 适配 ModelScope 远程部署 (Dockerfile + 部署文档)
  - ✅ 数据驱动 self_iterate（不再依赖Ollama）
  - ✅ 架构理念：MCP=数据层，AI客户端LLM=分析层
- v2.0.0 (2026-06-26): 多AI身份识别 + 云盘同步 + 配置向导 + AI优化
- v1.0.0 (2026-06-26): 初始版本 - 50+ MCP工具，14个分类
