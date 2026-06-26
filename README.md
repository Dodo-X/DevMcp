# 🧬 devPartner - 自我进化的全能 MCP 服务 v2.0

> **一个可以在对话中自我更新、自我完善的 AI 编程伙伴服务**
> v2.0 新增：多AI身份识别、云盘同步存储、配置向导、AI配置优化

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
| 💭 **自我反省** | Ollama AI 决策复盘 | v1.0 |
| 🆔 **身份识别** | CodeBuddy/Trae/Cursor 自动检测与注册 | **v2.0 新增** |
| ☁️ **云盘同步** | 坚果云/阿里云盘 WAL防冲突 SQLite存储 | **v2.0 新增** |
| 🧙 **配置向导** | 智能环境扫描/路径检测/引导配置 | **v2.0 新增** |
| 🎯 **AI优化** | 客户端MCP/Rules分析/冗余检测/配置建议 | **v2.0 新增** |

## 🚀 快速开始

### 前置要求
- Python 3.10+
- Node.js (用于部分 npm MCP 服务)
- Ollama (用于 AI 分析功能，可选)
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

### 首次运行配置向导

启动后，让 AI 调用 `devpartner_setup` 完成自动配置：

```
AI 调用 devpartner_setup
  → 扫描云盘（坚果云/阿里云盘/OneDrive）
  → 检测 AI 客户端（CodeBuddy/Trae/Cursor）
  → 推荐数据存储路径
  → 生成 MCP 连接配置
```

### ☁️ 多设备数据同步（坚果云/阿里云盘）

devPartner v2.0 专为云盘同步设计：

1. **设置 data_root 到云盘文件夹**：
   ```yaml
   # config.yaml
   cloud_sync:
     data_root: "D:/Nutstore/devPartner-data"  # 坚果云
     # 或 "D:/阿里云盘/devPartner-data"
   ```

2. **SQLite WAL 模式**：`.db-wal` 和 `.db-shm` 临时文件不参与云盘同步，避免冲突

3. **自动设备发现**：devPartner 自动检测并注册不同设备上的 AI 客户端

服务启动后：
- **SSE 端点**: `http://localhost:8080/sse`

### 配置 CodeBuddy / Trae 使用 devPartner

**方法一：自动配置**（推荐）
启动 devPartner 后，让 AI 调用 `devpartner_setup` 工具，devPartner 会自动检测你的 AI 客户端并生成连接配置。

**方法二：手动配置**

编辑 MCP 配置文件：

| AI客户端 | 配置文件位置 |
|----------|------------|
| CodeBuddy | `%USERPROFILE%\.codebuddy\mcp.json` |
| Trae | `项目目录\.trae\mcp.json` |
| Cursor | `%USERPROFILE%\.cursor\mcp.json` |

添加以下配置：

```json
{
  "mcpServers": {
    "devpartner": {
      "type": "sse",
      "url": "http://localhost:8080/sse"
    }
  }
}
```

## 📁 项目结构

```
devPartner/
├── server.py                    # 主入口 - FastMCP 服务 (70+ 工具, 19 分类)
├── config.yaml                  # 配置文件 (含云同步/身份识别)
├── requirements.txt             # Python 依赖
├── start.bat                    # Windows 启动脚本
├── README.md                    # 本文件
│
├── core/                        # 核心引擎
│   ├── config.py               # 配置管理 (YAML + 环境变量 + 热重载)
│   ├── database.py             # SQLite (WAL模式 + 客户端追踪)
│   ├── identity.py             # ★ 多AI身份识别 (v2.0)
│   ├── cloud_sync.py           # ★ 云盘同步存储 (v2.0)
│   ├── rule_engine.py          # 规则引擎 (嵌入式 + 触发检测)
│   └── evolution.py            # 自我进化引擎 (更新 + 热重载)
│
├── tools/                       # 工具层
│   ├── filesystem.py           # 原生文件系统 (读/写/搜索/列表)
│   ├── native_tools.py         # 原生工具 (Git/SQLite/URL/记忆/命令)
│   └── subprocess_tools.py     # Subprocess 代理 (GitHub/Context7)
│
├── services/                    # 服务层
│   ├── ollama_service.py       # Ollama AI 分析
│   ├── log_service.py          # 日志记录与管理（客户端追踪）
│   ├── dialogue_service.py     # 跨AI对话管理（可配置路径）
│   ├── mindmap_service.py      # 思维导图生成
│   ├── discovery_service.py    # MCP 服务自动发现
│   ├── setup_service.py        # ★ 配置向导 (v2.0)
│   └── ai_optimizer.py         # ★ AI配置优化建议 (v2.0)
│
├── skills/                      # 技能模块
│   ├── daily_summary.py        # 每日总结技能
│   └── self_iterate.py         # 自我迭代技能
│
├── rules/                       # 规则模块
│   └── __init__.py
│
└── data/                        # 运行时数据 (自动创建)
    ├── devpartner.db            # 本地数据库
    ├── daily_logs/              # 每日日志
    ├── mindmaps/                # 思维导图输出
    ├── memories/                # 记忆存储
    └── backups/                 # 代码备份
```

## 🔧 工具分类 (50+ 工具)

### 1. 文件系统 (5 工具)
- `fs_read_file` - 读取文件
- `fs_write_file` - 写入文件
- `fs_list_directory` - 列出目录
- `fs_search_files` - 搜索文件
- `fs_search_content` - 搜索文件内容 (ripgrep)

### 2. Git 操作 (3 工具)
- `git_status` - 查看状态
- `git_log` - 提交历史
- `git_diff` - 差异对比

### 3. 网络与数据库 (2 工具)
- `fetch_url` - HTTP 请求
- `db_query` - SQL 查询

### 4. 思考与记忆 (3 工具)
- `sequential_think` - 链式思考
- `save_memory` / `get_memory` / `list_memories`

### 5. 外部搜索 (3 工具)
- `github_search_code` / `github_search_repositories`
- `context7_search`

### 6. 对话日志 (4 工具)
- `log_conversation` - 记录对话
- `read_daily_log` / `list_logs`
- `check_log_gaps` - 间隙检测

### 7. 跨AI对话 (4 工具)
- `check_cross_dialogue` / `read_cross_dialogue`
- `write_cross_dialogue` / `reply_cross_dialogue`
- `mark_dialogue_read`

### 8. 思维导图 (3 工具)
- `generate_mindmap` - 从数据生成
- `generate_mindmap_from_tree` - 从节点树生成
- `list_mindmaps`

### 9. Ollama AI (3 工具)
- `ollama_health` / `ollama_chat`
- `ai_self_reflect` - 决策复盘

### 10. 每日总结 (1 工具)
- `run_daily_summary`

### 11. 自我迭代 (2 工具)
- `run_self_iterate`
- `get_pending_improvements`

### 12. MCP 发现 (3 工具)
- `discover_mcp_servers` / `list_known_mcp_servers`
- `test_mcp_server`

### 13. 自我进化 (5 工具)
- `self_upgrade` / `self_create_file`
- `self_hot_reload` / `self_diagnose`
- `get_system_status` / `get_evolution_history`

### 14. 规则与数据 (4 工具)
- `get_rules_summary` / `detect_rules`
- `execute_system_command`
- `get_db_stats` / `search_conversations`

## 🧬 自我进化能力

devPartner 最核心的特性是**在对话中自我进化**：

```
你: "给 devPartner 添加一个新工具 XXX"
  ↓
CodeBuddy 调用 self_create_file 工具
  ↓
devPartner 创建新代码文件 + 验证语法
  ↓
CodeBuddy 调用 self_upgrade 更新 server.py
  ↓
devPartner 备份 → 写入 → 验证 → 成功
  ↓
CodeBuddy 调用 self_hot_reload 热重载
  ↓
新工具立即可用！🎉
```

安全机制：
- ✅ 自动备份（备份在 `data/backups/`）
- ✅ 语法验证（Python 文件编译检查）
- ✅ 失败自动回滚
- ✅ 每日升级次数限制（默认 3 次）
- ✅ 完整操作日志

## 🔄 与现有 CodeBuddy 配置的关系

devPartner 旨在**完全覆盖**当前 CodeBuddy 的以下配置：

| CodeBuddy 配置 | devPartner 替代方案 |
|---|---|
| `local-aggregator` MCP | 原生 Python 实现 (更快) |
| `auto-log-conversation` 规则 | 嵌入式规则引擎 + `log_conversation` 工具 |
| `cross-agent-dialogue` 规则 | `dialogue_service` + 相关工具 |
| `turbo-effect` 规则 | `self_iterate` 技能 + evolution 引擎 |
| `daily-summary` skill | `daily_summary` 技能 |
| `deploy-ops` skill | 工具聚合 (git/命令/文件) |
| `self-iterate` skill | `self_iterate` 技能 + evolution 引擎 |
| Hook 脚本 | 服务内置处理 (无需外部脚本) |
| Automations | 可通过 chat + schedule 实现 |

## 🆓 免费 MCP 服务推荐

| 服务 | 包名 | 免费额度 |
|------|------|---------|
| 文件系统 | `@modelcontextprotocol/server-filesystem` | 无限 |
| Git | `@modelcontextprotocol/server-git` | 无限 |
| SQLite | `@modelcontextprotocol/server-sqlite` | 无限 |
| 链式思考 | `@modelcontextprotocol/server-sequential-thinking` | 无限 |
| 记忆 | `@modelcontextprotocol/server-memory` | 无限 |
| URL获取 | `@modelcontextprotocol/server-fetch` | 无限 |
| GitHub | `@modelcontextprotocol/server-github` | 需Token |
| Brave搜索 | `@anthropic/mcp-server-brave-search` | 免费额度 |
| Puppeteer | `@anthropic/mcp-server-puppeteer` | 无限(本地) |
| Context7 | `@upstash/context7-mcp` | 需API Key |

## 📊 数据流向

```
CodeBuddy 对话
  ↓
  调用 devPartner MCP 工具
  ↓
  ├── log_conversation → data/daily_logs/conversation_{date}.md
  ├── save_memory → data/memories/{key}.json
  ├── run_daily_summary → Ollama 分析 → 共享 DB → 日报
  ├── run_self_iterate → Ollama 分析 → 改进建议 → auto-apply
  ├── write_cross_dialogue → agent_dialogue.md
  └── self_upgrade → 备份 → 写入 → 验证 → 热重载
```

## 🔒 安全说明

- 所有文件操作基于项目根目录
- 代码自进化有备份和回滚机制
- 每日升级次数限制防止无限修改
- SQLite 数据库为本地文件，无网络暴露

## 📝 版本历史

- v1.0.0 (2026-06-26): 🎉 初始版本
  - 50+ MCP 工具，14 个分类
  - 完整覆盖 CodeBuddy 现有配置
  - 自我进化引擎
  - MCP 自动发现
  - 思维导图生成
  - 跨AI对话系统
  - Ollama AI 分析集成
