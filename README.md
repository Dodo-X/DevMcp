# DevPartner - AI 驱动的开发者智能伴侣

<p align="center">
  <strong>基于本地 Ollama (Qwen) 的全栈开发辅助系统</strong><br>
  <em>对话管理 · 知识沉淀 · 自我进化 · MCP 工具集成</em>
</p>

---

## ✨ 核心特性

### 🏗️ 分层架构 (v9.5.5)
- **`foundation/`**: 全局基础框架（配置 / 日志 / 埋点 / 异常 / 统一返回体 / 通用工具），与业务解耦，可独立复用。
- **`backend/`**: 后端业务层，分 `core`（底层引擎）/ `business`（业务服务）/ `api_gateway`（HTTP 网关）/ `templates`（Prompt 与 MD 模板）。
- **`mcp_service/`**: MCP 薄壳模块，通过注解暴露工具，**与 Web 网关互不冲突**，共用 `foundation/` + `backend/` 底层。
- **`frontend/`**: 前后端分离预留位置（尚未构建）。

### 🤖 LLM 驱动架构
- **零硬编码**: 所有数据分析由本地 Ollama 模型智能推理。
- **统一提示词工程**: Prompt 集中在 `backend/templates/llm_prompt/`，支持热重载。
- **双模式运行**: LLM 可用时智能分析，不可用时优雅降级。
- **引擎切换**: 推理引擎基于本地 Ollama HTTP API。

### 🎯 核心能力
1. **对话智能分析** - 自动识别技能领域、复杂度、用户反馈
2. **每日工作总结** - LLM 生成专业日报（非模板化）
3. **自我迭代优化** - 基于数据驱动的系统改进建议
4. **用户画像融合** - 动态构建开发者能力模型
5. **MCP 工具集成** - 对话记录三件套工具无缝调用
6. **知识图谱** - 自动沉淀和关联知识点

### 🏗️ 技术栈
| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 推理引擎 | Ollama (本地 HTTP API) | 统一模型管理，无需 GGUF 文件 |
| LLM 模型 | Qwen (ollama pull) | 由 Ollama 管理，推荐 qwen2.5 / qwen3 |
| 数据库 | SQLite 3.x (WAL) | 轻量级，零配置 |
| Web Dashboard | HTML + JavaScript | 运维监控面板（系统 / 任务队列） |
| 部署方案 | Docker / 本地运行 | 支持容器化和裸机部署 |

---

## 🚀 快速开始

### 前置要求
- Python 3.10+
- 已安装并运行 [Ollama](https://ollama.com/download)
- 磁盘空间 ≥ 2GB（模型由 Ollama 管理，不占用本项目目录）

### Step 1: 安装依赖与模型

```bash
# 安装项目依赖（Ollama 推理通过标准库 urllib，无需额外推理库）
pip install -r requirements.txt

# 安装并启动 Ollama（单独进程），拉取推理模型
ollama pull qwen2.5        # 推荐；可在 foundation/config/config.yaml 的 llm.ollama_model 调整
```

### Step 2: 配置系统

编辑 `foundation/config/config.yaml`:

```yaml
llm:
  enabled: true
  ollama_model: "qwen2.5"  # Ollama 中已拉取的模型名（ollama list 查看）
  ollama_timeout: 120      # 推理超时（秒）
  max_tokens: 2048         # 最大生成长度
  temperature: 0.3         # 生成温度（低值更确定）
  fallback_to_rules: true  # Ollama 不可用时降级到规则引擎
```

### Step 3: 启动服务

```bash
# 方式 A: 统一入口（推荐，开发模式）
python main.py 7860

# 方式 B: 直接启动 MCP 模块
python -m mcp_service.mcp_server 7860

# 方式 C: Docker 部署（生产模式）
docker-compose up -d
```

**预期输出**:
```
============================================================
  DevPartner v9.5.5 (Engine Pattern)
  架构: mcp_service/mcp_server.py(薄壳) → backend/*(业务)
============================================================

  MCP工具: 3 个 (3核心 + 0通用)
  Prompts: 5 个 Prompt 已注册
  管家层: 已加载
  LLM并行: OLLAMA_NUM_PARALLEL=1

  启动模式: MCP 服务 (Streamable HTTP)
  运行环境: 本地开发
  监听端口: 7860
  MCP端点: http://127.0.0.1:7860/mcp

  待命状态: 等待 MCP 客户端连接...
============================================================
```

### Step 4: 验证安装

访问 http://localhost:7860/dashboard 查看 Dashboard，或运行测试：

```bash
pytest tests/ -v
```

---

## 📁 项目结构

```
devPartner/                              # 根目录（包名不变）
├── README.md                            # ← 主文档
├── PROJECT_STRUCTURE.md                 # 项目导航指南
├── CHANGELOG.md                         # 版本迭代记录
│
├── main.py                              # 🚀 统一启动入口（runpy 代理到 mcp_service）
├── mcp_service/                         # 🔌 MCP 薄壳模块（注解暴露工具）
│   ├── mcp_server.py                    #    FastMCP 入口：3 个核心 @mcp.tool + 注册
│   └── __init__.py
│
├── foundation/                          # 🏗️ 全局基础框架（与业务无关，可独立复用）
│   ├── config/                          #    配置（app_settings / error_code / path_settings）
│   │   └── config.yaml                  #    运行时配置
│   ├── logger_framework/                #    日志框架（setup_logging / get_logger）
│   ├── trace_tracker/                   #    埋点追踪（contextvars + span + 计数器）
│   ├── exception_framework/             #    异常框架（BizException / 全局捕获 / 渲染）
│   ├── api_response/                    #    统一返回体（BaseResponse / PageResponse / 工厂）
│   └── common_utils/                    #    通用工具（json/text/time/file/schema/decorators）
│
├── backend/                             # 🎯 后端业务层（核心大脑）
│   ├── core/                            #    ├─ 核心底层能力（有状态, 单例）
│   │   ├── conversation_mgr/            #    │  ⭐ 对话引擎（总分三步走，分层子包）
│   │   ├── llm_kernel/                  #    │  🤖 LLM 推理内核（Ollama HTTP）
│   │   ├── task_queue_kernel/           #    │  📨 异步任务队列内核
│   │   ├── database/                    #    │  💾 数据库连接与 DAO
│   │   ├── bootstrap.py                 #    │  🏗️ 启动与初始化
│   │   ├── scheduler.py                 #    │  ⏰ 定时调度器
│   │   ├── task_recovery.py             #    │  🔁 任务恢复流水线
│   │   └── data_types/                  #    │  📐 数据契约（dataclass schema）
│   │
│   ├── business/                        #    ├─ 业务层（无状态服务 + 技能）
│   │   ├── system_ops/                  #    │  🔧 系统引擎（诊断+清理+热重载）
│   │   ├── knowledge_extractor/         #    │  📚 知识引擎（图谱+检索）
│   │   ├── data_cleanup/                #    │  🧹 数据清理调度
│   │   ├── vault_export/                #    │  📦 Obsidian Vault 导出
│   │   ├── analytics/                   #    │  📈 成长分析
│   │   └── task_handlers/               #    │  📋 日报/周报/月报/年报 + 技能
│   │
│   ├── api_gateway/                     #    ├─ HTTP 网关层
│   │   ├── rest_api.py                  #    │  REST 路由（/dashboard, /health, /api/*）
│   │   ├── server.py / lifespan.py      #    │  网关装配 + 生命周期
│   │   ├── dashboard.html               #    │  运维监控面板
│   │   └── middlewares/routes/dependencies/  # 预留扩展点
│   │
│   └── templates/                       #    └─ 模板层
│       ├── llm_prompt/                  #       LLM 提示词模板
│       └── md_render/                   #       Markdown 渲染模板（预留）
│
├── frontend/                            # 🖥️ 前端（预留，前后端分离，尚未构建）
├── tests/                               # 🧪 测试套件
├── scripts/                             # 📜 运维脚本
├── docs/                                # 📚 技术文档
├── data/                                # 💾 运行时数据（数据库 / 日志 / 知识库，gitignore）
├── models/                              # 🧠 LLM 模型文件（gitignore）
├── docker-compose.yml / Dockerfile      # 🐳 部署配置（根目录）
├── pyproject.toml                       # 项目元数据
└── requirements.txt                     # 全局依赖
```

### 分层原则

```
MCP 客户端 ──→ mcp_service/（注解暴露）──┐
                                         ├──→ backend/business/（业务编排）
Web 客户端 ──→ backend/api_gateway/ ─────┘            │
                                                      ↓
                                         backend/core/（底层能力：引擎/队列/DB/LLM）
                                                      ↓
                                         foundation/（配置/日志/埋点/异常/返回体/工具）
```

- **MCP 与 Web 不冲突**：MCP 工具通过注解暴露，仅被 MCP 客户端调用；两者共用 `foundation/` + `backend/` 底层。
- **绝对导入**：所有模块使用 `from backend.xxx` / `from foundation.xxx` 绝对导入，禁止跨包相对导入。

### 📂 模块职责说明

#### `main.py` + `mcp_service/` - 入口与 MCP 薄壳 🚀
`main.py` 仅做 `runpy.run_module("mcp_service.mcp_server")` 代理；真正的 MCP 入口是 `mcp_service/mcp_server.py`。
**包含**:
- 3 个核心 `@mcp.tool`: `start_conversation`, `record_step`, `finalize_conversation`
- `_register_rest_routes()`: 注册 HTTP REST 路由
- `_register_task_handlers()`: 注册各模块任务处理器到 `task_queue`

#### `backend/core/` - 核心底层能力 🧠
| 模块 | 职责 |
|------|------|
| `conversation_mgr/` | 对话生命周期（start→record→finalize 总分三步走） |
| `llm_kernel/` | LLM 推理内核（Ollama HTTP API） |
| `task_queue_kernel/` | 异步任务队列（FIFO + 对话级互斥 + 回调） |
| `database/` | SQLite 连接（WAL）与 DAO |
| `bootstrap.py` | 启动与初始化（`ensure_ready` / `apply_patches`） |
| `scheduler.py` | 定时调度器（日报 / 恢复流水线） |
| `task_recovery.py` | 任务恢复流水线（启动 + 定时双入口） |
| `data_types/` | 数据契约（dataclass Schema） |

#### `backend/business/` - 业务层 ⚙️
无状态业务服务，被核心引擎或任务队列调用。
- `system_ops/`：系统诊断 + 清理 + 热重载
- `knowledge_extractor/`：知识点提取 + 知识图谱
- `data_cleanup/`：数据清理调度
- `vault_export/`：Obsidian Vault 导出（MD 引擎 + 导出器）
- `analytics/`：成长分析（用户成长概览 / 技能雷达）
- `task_handlers/`：日报/周报/月报/年报 + 每日总结技能

#### `backend/api_gateway/` - HTTP 网关层 🌐
REST API 端点，供 Web 前端 / 运维面板使用。
- `/dashboard` - 运维面板（系统 / 任务队列监控）
- `/health` - 健康检查
- `/api/growth/*` - 成长分析 API
- `/api/system/*` - 系统状态 API
- `/api/projects/*` - 项目知识 API

#### `backend/templates/llm_prompt/` - 提示词模板层 ✍️
所有 LLM Prompt 集中管理，与代码解耦，支持热重载。

#### `foundation/` - 全局基础框架 🏗️
与业务无关的通用能力，可独立复用于其他项目。
- `config/`：配置加载（`app_settings.py`）+ `config.yaml`
- `logger_framework/`：统一日志
- `trace_tracker/`：埋点追踪（基于 `contextvars`）
- `exception_framework/`：统一异常（`BizException` / 全局捕获 / 错误渲染）
- `api_response/`：统一返回体（`ok` / `fail` / `page`）
- `common_utils/`：通用工具（json / text / time / file / schema / decorators）

---

## 🎮 使用指南

### 基础用法

#### 1️⃣ 对话记录与分析（总分三步走）

```python
from backend.business.conversation_mgr import get_conversation_engine

engine = get_conversation_engine()

# 第一步: 开始对话
result = engine.start_conversation(
    client="trae", topic="React前端开发", task_type="development"
)
conv_id = result["conversation_id"]

# 第二步: 记录步骤
engine.record_step(
    conversation_id=conv_id, step_name="创建组件", step_type="implementation",
    content='{"file": "src/App.tsx", "action": "create"}'
)

# 第三步: 结束对话（自动触发 LLM 分析）
summary = engine.finalize_conversation(conversation_id=conv_id)
print(f"总结: {summary['summary']}")
```

#### 2️⃣ 生成每日总结

```python
from backend.business.task_handlers.daily_engine import get_daily_engine

engine = get_daily_engine()
report = engine.get_daily_summary(date="2026-07-23")
print(f"📊 今日摘要: {report.get('summary', '')}")
```

#### 3️⃣ 使用 MCP 工具

通过 MCP 协议调用工具（已集成到 Cursor / Windsurf / Trae 等 IDE）：

```json
{
  "tool": "start_conversation",
  "params": {
    "client": "trae",
    "topic": "React前端开发",
    "task_type": "development"
  }
}
```

**核心 MCP 工具 (3个)**:
- `start_conversation` - 开启会话（总分总·总）
- `record_step` - 记录步骤（总分总·分，每完成一个子任务立即调用）
- `finalize_conversation` - 结束会话（总分总·总，触发全局分析）

---

## 🔧 高级配置

### LLM 引擎调优

编辑 `foundation/config/config.yaml`:

```yaml
llm:
  ollama_model: "qwen2.5"   # Ollama 模型名（ollama list 查看可用模型）
  ollama_timeout: 120       # 推理超时（秒）
  max_tokens: 2048          # 最大输出长度
  max_input_chars: 8000     # 最大输入字符数
  temperature: 0.3          # 创造性（0=确定性, 1=随机）
  preload: true             # 启动时验证 Ollama 连接并测试推理
  fallback_to_rules: true   # LLM 失败时降级到规则
```

### 性能优化建议

推理性能主要取决于 Ollama 侧（模型量化等级、GPU 是否可用）。本项目通过 `ollama_model` 选择模型即可，无需调整底层推理参数。

| 场景 | 推荐模型 | 预期效果 |
|------|---------|---------|
| **内存有限** (< 8GB) | `qwen2.5:3b` | 内存占用低，响应快 |
| **追求速度** | 启用 Ollama GPU 加速 | 推理速度提升 3-5 倍 |
| **质量优先** | `qwen2.5:14b` / `qwen2.5:32b` | 输出更精准 |
| **中文场景** | `qwen2.5` 系列 | 中文能力优异 |

---

## 📊 监控与维护

### Web Dashboard

启动后访问: **http://localhost:7860/dashboard**

功能概览:
- 📈 实时统计（对话数、活跃用户、工具调用）
- 🧠 LLM 状态（模型加载、推理延迟、缓存命中率）
- 📋 最近对话列表
- ⚙️ 配置管理界面

### 日志查看

```bash
tail -f data/logs/agent.log
grep ERROR data/logs/agent.log
```

### 数据库维护

```bash
# 备份数据库
cp data/databases/devpartner.db backups/devpartner_$(date +%Y%m%d).db

# 数据库完整性检查
python scripts/check_db_integrity.py
```

---

## 🔄 版本迭代记录

### v9.5.5 (2026-07-23) - 分层架构重构 ⭐
**重大变更**:
- ✅ 按模板重构为四层架构：`foundation/`（基础框架）+ `backend/`（core/business/api_gateway/templates）+ `mcp_service/`（MCP 薄壳）+ `frontend/`（预留）
- ✅ 原 `server.py` → `mcp_service/mcp_server.py`，新增 `main.py` 统一入口
- ✅ 原 `devpartner_agent/` → `backend/core` + `backend/business` + `backend/api_gateway`
- ✅ 原 `devpartner_tools/tools/growth_analytics.py` → `backend/business/analytics/`
- ✅ 原 `prompts/` → `backend/templates/llm_prompt/`
- ✅ 全部改为绝对导入（`from backend.xxx` / `from foundation.xxx`）
- ✅ 修复 `backend/templates/llm_prompt/__init__.py` 中 4 个从未定义的 Prompt 名称导致的包导入失败
- ✅ `config.yaml` 迁移至 `foundation/config/config.yaml`
- ✅ 保留 MCP 形态（注解暴露工具，与 Web 不冲突，共用底层）

详见 [CHANGELOG.md](./CHANGELOG.md)

---

## 🐛 故障排查

### 常见问题

#### Q1: LLM 服务启动失败？
**症状**: `❌ Ollama 服务不可达` 或分析功能不可用
**解决方案**:
1. 确认 Ollama 已安装并运行: `ollama list`
2. 确认模型已拉取: `ollama pull qwen2.5`
3. 确认 `foundation/config/config.yaml` 的 `llm.ollama_model` 与 `ollama list` 名称一致
4. 如 Ollama 不在本机，设置环境变量 `OLLAMA_BASE_URL=http://<host>:11434`
5. Ollama 不可用时系统自动降级到规则引擎，核心功能不受影响

#### Q2: 内存不足（OOM）？
改用更小模型: `ollama pull qwen2.5:3b`

#### Q3: 推理速度太慢？
1. 启用 Ollama GPU 加速
2. 减少 token 数: `max_tokens: 1024`
3. 相同输入会命中缓存，重复分析更快

#### Q4: 数据库锁定？
**症状**: `database is locked`
**解决方案**:
1. 检查是否有其他进程占用: `lsof data/databases/devpartner.db`
2. 重启服务释放锁
3. 启用 WAL 模式（默认已启用）

---

## 🤝 贡献指南

### 开发流程
1. Fork 并克隆仓库
2. 创建特性分支: `git checkout -b feature/new-feature`
3. 编写代码并添加测试
4. 运行测试: `pytest tests/`
5. 提交变更: `git commit -m "feat: add new feature"`
6. 推送分支并创建 Pull Request

### 代码规范
- 遵循 PEP 8 风格指南
- 类型注解（Python 3.10+）
- 中文注释（面向中文开发者）
- 所有公开函数必须有 docstring
- 跨包使用绝对导入

---

## 📄 许可证

MIT License

Copyright (c) 2026 DevPartner Team

---

## 🙏 致谢
- [Qwen](https://qwenlm.github.io/) - 强大的开源大语言模型
- [Ollama](https://ollama.com/) - 简单的本地大模型运行与管理框架
- [Model Context Protocol](https://modelcontextprotocol.io/) - 标准化的工具调用协议
