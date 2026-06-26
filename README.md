# 🧬 devPartner v2.0.0 - MCP 双服务架构

> **纯工具 + 智能管家**：彻底分离关注点，工具层无状态，管家层有记忆
> 保留全部自我迭代、规则引擎、进化引擎等核心能力

## 🏗️ v2.0 架构理念

```
┌──────────────────────────────────────────────────────────────┐
│                      v2.0.0 (新架构)                          │
│                                                              │
│  ┌─────────────────────┐    ┌─────────────────────────────┐  │
│  │  devpartner-tools   │    │     devpartner-agent        │  │
│  │  ─────────────────  │    │  ─────────────────────────  │  │
│  │  📦 纯工具层         │◄───│  🧠 智能管家层               │  │
│  │  · 无状态            │    │  · 有状态（DB/日志/记忆）    │  │
│  │  · 无副作用          │    │  · 自我迭代引擎              │  │
│  │  · 即用即弃          │    │  · 规则引擎（自动触发）      │  │
│  │  · 25 个纯函数       │    │  · 进化引擎（代码自更新）    │  │
│  │  · 输入→处理→输出    │    │  · 43 个 Agent 工具         │  │
│  └─────────────────────┘    └─────────────────────────────┘  │
│                                                              │
│  原则：                                                       │
│  ✅ 工具层不存数据，只做处理                                    │
│  ✅ 管家层负责状态管理、记忆、进化                               │
│  ✅ 清晰的职责边界，易维护、易扩展                               │
└──────────────────────────────────────────────────────────────┘
```

## ✨ 核心特性

| 层 | 能力 | 工具数 | 原则 |
|----|------|--------|------|
| 🔧 **tools** | 文件/Git/HTTP/推理/系统/发现 | 25 个纯工具 | 无状态、无副作用 |
| 🧠 **agent** | 对话日志/跨AI对话/自我迭代/规则引擎/进化引擎/云同步 | 42 个 Agent 工具 | 有状态、有记忆 |
| 🌟 **自我迭代** | 数据收集→AI分析→代码变更→Git提交→PR | 闭环 | 核心保留 |
| 🔄 **规则引擎** | 自动触发+动态注册+执行 | 5 条内置规则 | 核心保留 |
| 🧬 **进化引擎** | 代码自更新/备份/回滚/热重载 | 安全升级 | 核心保留 |

## 🚀 快速开始

### 前置要求
- Python 3.10+
- Node.js（可选，用于部分 MCP 服务）

### 安装

```bash
# 安装 tools 层依赖
pip install -r devpartner-tools/requirements.txt

# 安装 agent 层依赖
pip install -r devpartner-agent/requirements.txt
```

### 启动

```bash
# 方式一：仅启动纯工具层（轻量，25个工具）
python devpartner-tools/server.py

# 方式二：仅启动智能管家层（完整功能，15个Agent工具）
python devpartner-agent/server.py

# 方式三：同时启动（推荐，完整功能）
# 终端1 - 工具层
python devpartner-tools/server.py

# 终端2 - 管家层
python devpartner-agent/server.py
```

### MCP 客户端配置

```json
{
  "mcpServers": {
    "devpartner-tools": {
      "command": "python",
      "args": ["<PATH>/devpartner-tools/server.py"],
      "transport": "stdio"
    },
    "devpartner-agent": {
      "command": "python",
      "args": ["<PATH>/devpartner-agent/server.py"],
      "transport": "stdio"
    }
  }
}
```

## 📁 项目结构

```
devPartner/
│
├── devpartner-tools/            # 🔧 纯工具层（无状态）
│   ├── server.py               # MCP 入口（25个工具注册）
│   ├── config.yaml              # 工具层配置（极少配置项）
│   ├── requirements.txt         # 最小依赖（fastmcp + httpx）
│   └── tools/                   # 6 大类工具模块
│       ├── filesystem.py        # 文件系统（5个：读/写/列表/搜索文件/搜索内容）
│       ├── git_operations.py    # Git 操作（3个：status/log/diff）
│       ├── web_requests.py      # 网络请求（4个：fetch/github搜索/context7）
│       ├── reasoning.py         # 推理分析（4个：链式思考/思维导图）
│       ├── system_utils.py      # 系统工具（4个：命令/客户端检测/环境扫描/路径验证）
│       └── discovery.py         # 服务发现（5个：MCP发现/测试/配置生成）
│
├── devpartner-agent/            # 🧠 智能管家层（有状态）
│   ├── server.py               # MCP 入口（15个Agent工具注册）
│   ├── config.yaml              # 管家层配置（服务开关、数据目录等）
│   ├── requirements.txt         # 依赖（fastmcp + pyyaml + watchdog）
│   │
│   ├── core/                    # 核心引擎（保留原有逻辑）
│   │   ├── rule_engine.py      # 规则引擎（自动触发+动态注册）
│   │   ├── evolution.py        # 进化引擎（代码自更新+热重载）
│   │   ├── identity.py         # 身份管理（多客户端配置）
│   │   ├── database.py         # 数据存储（SQLite+共享DB）
│   │   └── cloud_sync.py       # 云同步（数据备份恢复）
│   │
│   ├── services/                # 业务服务（保留原有逻辑）
│   │   ├── log_service.py      # 日志服务（对话记录+分析）
│   │   ├── dialogue_service.py # 跨AI对话服务（消息传递）
│   │   ├── discovery_service.py# 服务发现
│   │   └── ai_optimizer.py     # AI优化器（提示词优化）
│   │
│   ├── skills/                  # 技能模块（🌟 核心保留）
│   │   ├── self_iterate.py     # 自我迭代引擎（34KB，最核心）
│   │   └── daily_summary.py    # 每日总结分析（24KB）
│   │
│   ├── tools_bridge/            # 工具桥接（保留旧工具代码）
│   │   ├── filesystem.py
│   │   ├── native_tools.py
│   │   └── subprocess_tools.py
│   │
│   └── data/                    # 运行时数据（自动创建）
│       ├── databases/           # SQLite 数据库
│       ├── logs/                # 对话日志
│       ├── memories/            # 知识记忆
│       ├── backups/             # 进化备份
│       └── temp/                # 临时协同文件
│
└── README.md                    # 本文件
```

## 🔧 工具清单

### devpartner-tools（25 个纯工具）

| 分类 | 工具 | 数量 |
|------|------|------|
| 📁 文件系统 | `read_file` `write_file` `list_directory` `search_files` `search_content` | 5 |
| 🔀 Git | `git_status` `git_log` `git_diff` | 3 |
| 🌐 网络 | `fetch_url` `github_search_code` `github_search_repositories` `context7_search` | 4 |
| 🧠 推理 | `sequential_think` `generate_mindmap` `generate_mindmap_from_tree` `list_mindmaps` | 4 |
| ⚙️ 系统 | `execute_system_command` `detect_client` `environment_scan` `validate_path` | 4 |
| 🔍 发现 | `discover_mcp_servers` `list_known_mcp_servers` `test_mcp_server` `get_rules_summary` `generate_config_snippet` | 5 |

### devpartner-agent（43 个 Agent 工具）

| 分类 | 工具 | 数量 |
|------|------|------|
| 📝 对话日志 | `log_conversation` `get_daily_summary` `read_daily_log` `list_logs` `check_log_gaps` `cleanup_old_data` | 6 |
| 💬 跨AI对话 | `send_agent_message` `check_agent_messages` `decompose_task` `cross_ai_review` | 4 |
| 🌟 自我迭代 | `self_iterate` `self_upgrade` `self_create_file` | 3 |
| 📐 规则引擎 | `get_rules` `trigger_rule` `detect_rules` | 3 |
| 🗄️ 数据库 | `query_database` `search_conversations` `get_db_stats` | 3 |
| 🎯 AI优化 | `optimize_prompt` | 1 |
| ☁️ 云同步 | `sync_to_cloud` `restore_from_cloud` | 2 |
| 📊 每日总结 | `get_daily_work_data` `save_daily_analysis` `get_weekly_work_data` `get_work_schema_guide` | 4 |
| 🔄 数据迁移 | `import_daily_log_to_db` `sync_all_logs_to_db` | 2 |
| 🩺 系统诊断 | `get_system_status` `self_diagnose` `get_evolution_history` `get_pending_improvements` | 4 |
| 🔍 MCP发现 | `list_recommended_mcp_servers` `scan_new_mcp_servers` `get_discovery_status` | 3 |
| 🛡️ 安全审计 | `run_security_audit` | 1 |
| 🔧 系统 | `hot_reload_module` `setup_devpartner` `get_identity_info` 等 | 7 |

## 🌟 保留的核心自我迭代能力

```
┌─────────────────────────────────────────────────────────┐
│                  自我迭代闭环（完整保留）                  │
│                                                         │
│  Step 1: 收集系统数据                                     │
│    ├── 使用频率统计（哪些工具被调用最多）                    │
│    ├── 错误日志分析（哪些错误频繁出现）                      │
│    ├── 用户反馈（对话中的问题/建议）                         │
│    └── 性能指标（响应时间、内存占用）                        │
│                                                         │
│  Step 2: AI 分析生成改进建议                               │
│    ├── 代码优化建议                                       │
│    ├── 配置调整建议                                       │
│    ├── 新功能建议                                         │
│    └── 安全漏洞检测                                       │
│                                                         │
│  Step 3: 识别可自动执行的代码变更                           │
│    ├── 简单参数调整（自动执行）                             │
│    ├── 代码重构（需审批）                                  │
│    └── 架构变更（仅建议）                                  │
│                                                         │
│  Step 4: 安全执行变更（evolution.py）                      │
│    ├── 备份原文件                                         │
│    ├── 写入新内容                                         │
│    ├── 语法验证（Python）                                 │
│    ├── 失败自动回滚                                       │
│    └── 记录进化日志                                       │
│                                                         │
│  Step 5: Git 集成（可选）                                 │
│    ├── 创建功能分支                                       │
│    ├── 提交变更                                           │
│    └── 创建 PR                                           │
└─────────────────────────────────────────────────────────┘
```

### 内置规则（rule_engine.py）

| 规则 | 优先级 | 自动触发 | 说明 |
|------|--------|----------|------|
| auto-log-conversation | 1 | ✅ | 每次实质性对话自动记录 |
| cross-agent-dialogue | 1 | ✅ | 多AI实例间消息传递 |
| turbo-effect | 2 | ✅ | 每次总结后自动优化配置 |
| security-audit | 2 | ✅ | 代码变更后自动扫描安全问题 |
| self-reflection | 3 | ✅ | 重要决策后自动反思 |

## 🆓 完全免费方案

| 组件 | 费用 | 说明 |
|------|------|------|
| devPartner MCP | 免费 | 开源，可自部署 |
| Python 运行时 | 免费 | 标准 Python 3.10+ |
| SQLite 存储 | 免费 | 内置，无需额外安装 |
| AI客户端 LLM | 免费 | Trae/CodeBuddy/Cursor 自带 |
| 总计 | **$0** | 全免费技术栈 |

## 📝 版本历史

- **v2.0.0** (2026-06-27): 🏗️ **双服务架构重构 - 正式版**
  - ✅ 拆分为 `devpartner-tools`（纯工具层，25个无状态工具）
  - ✅ 拆分为 `devpartner-agent`（智能管家层，42个有状态工具）
  - ✅ 保留全部自我迭代、规则引擎、进化引擎核心逻辑
  - ✅ 补回全部缺失的 MCP 工具（日志管理、每日总结、数据迁移、系统诊断等）
  - ✅ 修复所有 Bug（语法错误、导入路径、缺失方法）
  - ✅ 统一导入路径为绝对导入
  - ✅ 删除所有老版代码，项目结构干净整洁

## 📄 许可

MIT License - 开源免费
