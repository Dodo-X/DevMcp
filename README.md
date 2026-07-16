# DevPartner v7.5 - AI 驱动的开发者智能伴侣

<p align="center">
  <strong>基于本地 Ollama (Qwen3 等) 的全栈开发辅助系统</strong><br>
  <em>对话管理 · 知识沉淀 · 自我进化 · MCP 工具集成</em>
</p>

---

## ✨ 核心特性

### 🏗️ Engine Pattern 架构 (v7.5)
- **领域引擎模式**: 8 个独立 Engine 按业务域封装，server.py 仅 360 行薄壳入口
- **统一装饰器**: `@mcp_tool_handler` 消除 74 个裸函数的重复 try/except + json.dumps
- **关注点分离**: core/ 有状态引擎 vs services/ 无状态工具 vs routes/ HTTP 端点
- **可插拔注册**: 每个 Engine 自带 `register_*_tools(mcp)` 函数，按需加载

### 🤖 LLM 驱动架构 (v7.3.0+)
- **零硬编码**: 所有数据分析由本地 Ollama 模型智能推理
- **统一提示词工程**: 结构化 Prompt 确保输出精准可控
- **双模式运行**: LLM 可用时智能分析，不可用时优雅降级
- **代码精简 93%**: 从 3600+ 行硬编码 → ~150 行 LLM 调用
- **引擎切换**: v7.3.0 起推理引擎由 llama-cpp-python 迁移至本地 Ollama HTTP API

### 🎯 核心能力
1. **对话智能分析** - 自动识别技能领域、复杂度、用户反馈
2. **每日工作总结** - LLM 生成专业日报（非模板化）
3. **自我迭代优化** - 基于数据驱动的系统改进建议
4. **用户画像融合** - 动态构建开发者能力模型
5. **MCP 工具集成** - 20+ 开发工具无缝调用
6. **知识图谱** - 自动沉淀和关联知识点

### 🏗️ 技术栈
| 组件 | 技术选型 | 说明 |
|------|---------|------|
| 推理引擎 | Ollama (本地 HTTP API) | 统一模型管理，无需 GGUF 文件 |
| LLM 模型 | Qwen3 (ollama pull) | 由 Ollama 管理，推荐 qwen3 / qwen2.5 |
| 数据库 | SQLite 3.x (WAL) | 轻量级，零配置 |
| Web Dashboard | HTML + JavaScript | 运维监控面板（系统/任务队列） |
| 部署方案 | Docker / 本地运行 | 支持容器化和裸机部署 |

---

## 🚀 快速开始

### 前置要求
- Python 3.10+
- 已安装并运行 [Ollama](https://ollama.com/download)
- 磁盘空间 ≥ 2GB（模型由 Ollama 管理，不占用本项目目录）

### Step 1: 安装依赖与模型

```bash
# 克隆项目
git clone https://github.com/your-repo/devpartner.git
cd devpartner

# 创建虚拟环境（推荐）
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装项目依赖（Ollama 推理通过标准库 urllib，无需额外推理库）
pip install -r requirements.txt

# 安装并启动 Ollama（单独进程），拉取推理模型
ollama pull qwen3        # 推荐；可在 config.yaml 的 llm.ollama_model 调整
```

### Step 2: 配置系统

编辑 `devpartner_agent/config.yaml`:

```yaml
llm:
  enabled: true
  ollama_model: "qwen3"   # Ollama 中已拉取的模型名（ollama list 查看）
  ollama_timeout: 120     # 推理超时（秒）
  max_tokens: 2048        # 最大生成长度
  temperature: 0.3        # 生成温度（低值更确定）
  fallback_to_rules: true # Ollama 不可用时降级到规则引擎
```

### Step 4: 启动服务

```bash
# 方式 A: 直接启动（开发模式）
python server.py

# 方式 B: Docker 部署（生产模式）
docker-compose up -d

# 方式 C: 仅启动 Agent（无 Web UI）
cd devpartner_agent
python -m server
```

**预期输出**:
```
============================================================
  DevPartner v7.5 (Engine Pattern)
  架构: server.py(薄壳) → core/*_engine.py(业务)
============================================================

  工具层: 32 个工具已注册
  管家层: 已加载

  启动模式: MCP 服务 (Streamable HTTP)
  运行环境: 本地开发
  监听端口: 7860
  MCP端点: http://127.0.0.1:7860/mcp

  待命状态: 等待 MCP 客户端连接...
============================================================
```

### Step 5: 验证安装

访问 http://localhost:7860/dashboard 查看 Dashboard，或运行测试：

```bash
# 运行核心功能测试
python tests/test_basic_functionality.py

# 测试 LLM 分析引擎
python tests/test_llm_analyzer.py
```

---

## 📁 项目结构

```
devPartner/
├── README.md                          # ← 你在这里（主文档）
├── CHANGELOG.md                       # 版本迭代记录
│
├── server.py                          # 🚀 MCP 薄壳入口 (~360行)
│                                      #    4 个核心 @mcp.tool + 引擎注册
│
├── devpartner_agent/                  # 🎯 核心 Agent 系统
│   ├── core/                          #    ├─ 核心引擎层 (有状态, 单例)
│   │   ├── conversation_engine.py     #    │  ⭐ 对话引擎 (总分三步走)
│   │   ├── knowledge_engine.py        #    │  📚 知识引擎 (图谱+检索)
│   │   ├── system_engine.py           #    │  🔧 系统引擎 (诊断+清理)
│   │   ├── daily_engine.py            #    │  📋 日报引擎 (总结+日志)
│   │   ├── optimization_engine.py     #    │  🔄 优化引擎 (反馈+闭环)
│   │   ├── memory_engine.py           #    │  🧠 记忆引擎 (跨会话)
│   │   ├── iteration_engine.py        #    │  🧬 迭代引擎 (自我进化+规则+权限)
│   │   ├── vault_engine.py            #    │  🏦 Vault 引擎 (归档+回调+任务)
│   │   ├── llm_engine.py              #    │  🤖 LLM 推理引擎 (Ollama)
│   │   ├── bootstrap.py               #    │  🏗️ 启动与初始化
│   │   ├── decorators.py              #    │  🎯 @mcp_tool_handler 统一装饰器
│   │   ├── database.py                #    │  💾 数据库操作
│   │   └── config.py                  #    │  ⚙️ 配置管理
│   │
│   ├── routes/                        #    ├─ HTTP 路由层
│   │   └── rest_api.py                #    │  REST API 端点 (/dashboard, /health, /api/*)
│   │
│   ├── services/                      #    ├─ 无状态服务层
│   │   ├── task_queue.py              #    │  异步任务队列
│   │   ├── knowledge_graph.py         #    │  知识图谱服务
│   │   ├── callback_registry.py       #    │  回调注册表
│   │   ├── cleanup_scheduler.py       #    │  清理调度器
│   │   ├── optimization_loop.py       #    │  优化闭环
│   │   └── ...                        #    └─ 其他无状态服务
│   │
│   ├── skills/                        #    ├─ 技能模块
│   │   ├── daily_summary.py           #    │  日报生成技能
│   │   └── self_iterate.py            #    │  自我迭代技能
│   │
│   └── config.yaml                    #    Agent 配置文件
│
├── devpartner_tools/                  # 🔧 MCP 工具集 (无状态, 21个纯工具)
│   └── tools/
│       ├── filesystem.py              #    文件系统操作 (5个工具)
│       ├── git_operations.py          #    Git 命令封装 (3个工具)
│       ├── web_requests.py            #    HTTP 请求 (3个工具)
│       ├── system_utils.py            #    系统工具 (4个工具)
│       └── growth_analytics.py        #    成长分析 (5个工具)
│
├── tests/                             # 🧪 测试套件
├── scripts/                           # 📜 运维脚本
├── docs/                              # 📚 技术文档
├── data/                              # 💾 运行时数据 (gitignore)
├── deploy/                            # 🐳 部署配置
├── pyproject.toml                     # 项目元数据
└── requirements.txt                   # 全局依赖
```

### 📂 模块职责说明

#### `server.py` - 薄壳入口 🚀
**定位**: MCP 服务入口，仅负责注册工具和启动服务  
**核心原则**: 不包含任何业务逻辑，所有调用委托给 Engine  
**包含**:
- 4 个核心 `@mcp.tool`: `start_conversation`, `record_step`, `finalize_conversation`, `question_with_context`
- `_register_tool_layer()`: 注册工具层 21 个纯工具
- `_register_agent_engines()`: 注册 8 个领域引擎
- `_register_rest_routes()`: 注册 HTTP REST 路由

#### `devpartner_agent/core/` - 核心引擎层 🧠
**定位**: 有状态的业务引擎，单例模式，线程安全  
**设计原则**: 每个 Engine 对应一个业务域，自带 `register_*_tools(mcp)` 函数

| Engine | 职责 | MCP 工具数 |
|--------|------|-----------|
| ConversationEngine | 对话生命周期 (start→record→finalize) | 4 (在 server.py 直接注册) |
| KnowledgeEngine | 知识点 + 图谱 + 检索 | 10 |
| SystemEngine | 诊断 + 清理 + LLM状态 + 热重载 | 9 |
| DailyEngine | 日报 + 日志 + 工作数据 | 9 |
| OptimizationEngine | 反馈 + 优化闭环 + 检查 | 5 |
| MemoryEngine | 跨会话记忆 + 对话检索 | 3 |
| IterationEngine | 自我迭代 + 规则 + 权限 + Git + 并行 | 27 |
| VaultEngine | 归档 + 回调 + 任务状态 | 8 |

#### `devpartner_agent/services/` - 无状态服务层 ⚙️
**定位**: 无状态的辅助工具，被 Engine 调用  
**关键组件**:
- `task_queue.py`: 异步任务队列 (FIFO + 对话级互斥)
- `knowledge_graph.py`: 知识图谱构建与查询
- `callback_registry.py`: 回调通知注册表
- `cleanup_scheduler.py`: 数据清理调度
- `optimization_loop.py`: 优化闭环处理

#### `devpartner_agent/routes/` - HTTP 路由层 🌐
**定位**: REST API 端点，从 server.py 提取  
**端点**:
- `/dashboard` - 运维面板
- `/health` - 健康检查
- `/api/growth/*` - 成长分析 API
- `/api/system/*` - 系统状态 API
- `/api/projects/*` - 项目知识 API

#### `devpartner_tools/` - 工具层 🔧
**定位**: 无状态纯工具，不依赖 Agent 层  
**设计原则**: 每个工具文件自带 `register_*_tools(mcp)` 函数

#### `scripts/` - 运维工具 🛠️
**定位**: 一次性运维任务，非核心业务  
**典型用途**:
- 数据库升级/迁移
- 数据回填/修复
- 批量数据处理

**何时使用**:
- 版本升级时运行 `upgrade_to_v5.py`
- 数据异常时运行 `backfill_conversation.py`

#### `tests/` - 质量保障 ✅
**定位**: 确保系统稳定性和正确性  
**分类**:
- 单元测试 (`test_*.py`)
- 集成测试 (`test_integration.py`)
- 性能测试 (`test_performance.py`)

**何时运行**:
- 提交代码前: `pytest tests/`
- CI/CD 流水线自动执行

---

## 🎮 使用指南

### 基础用法

#### 1️⃣ 对话记录与分析 (总分三步走)

```python
from devpartner_agent.core.conversation_engine import get_conversation_engine

engine = get_conversation_engine()

# 第一步: 开始对话
result = engine.start_conversation(
    client="trae", topic="React前端开发", task_type="development"
)
conv_id = result["conversation_id"]

# 第二步: 记录步骤
engine.record_step(
    conversation_id=conv_id, step_number=1,
    step_name="创建组件", step_type="implementation",
    step_input='{"file": "src/App.tsx", "action": "create"}'
)

# 第三步: 结束对话 (自动触发 LLM 分析)
summary = engine.finalize_conversation(conversation_id=conv_id)
print(f"总结: {summary['summary']}")
```

#### 2️⃣ 生成每日总结

```python
from devpartner_agent.core.daily_engine import get_daily_engine

engine = get_daily_engine()
report = engine.get_daily_summary(date="2026-07-13")
print(f"📊 今日摘要: {report.get('summary', '')}")
```

#### 3️⃣ 触发自我优化

```python
from devpartner_agent.core.iteration_engine import get_iteration_engine

engine = get_iteration_engine()
result = engine.self_iterate(mode="auto")
print(f"生成建议: {len(result.get('suggestions_generated', []))} 条")
```

#### 4️⃣ 使用 MCP 工具

通过 MCP 协议调用工具（已集成到 Cursor/Windsurf/Trae 等 IDE）：

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

**核心 MCP 工具 (4个)**:
- `start_conversation` - 开始对话
- `record_step` - 记录步骤
- `finalize_conversation` - 结束对话
- `question_with_context` - 基于上下文提问

**领域 MCP 工具 (75+个)**:
- 知识域: `list_knowledge_points`, `search_knowledge`, `build_knowledge_graph` 等
- 系统域: `get_system_health`, `system_diagnose`, `hot_reload` 等
- 日报域: `get_daily_summary`, `read_daily_log`, `list_logs` 等
- 优化域: `process_user_feedback`, `check_optimization_needed` 等
- 记忆域: `get_memory`, `update_memory`, `search_conversations` 等
- 迭代域: `self_iterate`, `self_upgrade`, `get_rules`, `git_auto_commit` 等
- Vault域: `archive_conversation`, `register_callback`, `get_task_status` 等

---

## 🔧 高级配置

### LLM 引擎调优

编辑 `devpartner_agent/config.yaml`:

```yaml
llm:
  # Ollama 连接
  ollama_model: "qwen3"     # Ollama 模型名（ollama list 查看可用模型）
  ollama_timeout: 120       # 推理超时（秒）

  # 生成参数
  max_tokens: 2048          # 最大输出长度
  max_input_chars: 8000     # 最大输入字符数
  temperature: 0.3          # 创造性（0=确定性, 1=随机）
  top_p: 0.9               # 核采样
  top_k: 40                # Top-K 采样
  repeat_penalty: 1.1       # 重复惩罚

  # 启动行为
  preload: true             # 启动时验证 Ollama 连接并测试推理

  # 功能开关
  enhance_analysis: true     # 对话分析增强 ⭐ 推荐
  enhance_file_parsing: true  # 文件解析增强
  enhance_daily_summary: true  # LLM 日报生成 ⭐ 强烈推荐
  enhance_self_improvement: true  # 自我改进建议 ⭐ 推荐
  fallback_to_rules: true    # LLM 失败时降级到规则
```

### 性能优化建议

推理性能主要取决于 Ollama 侧（模型量化等级、GPU 是否可用）。本项目通过 `ollama_model` 选择模型即可，无需调整底层推理参数。

| 场景 | 推荐模型 | 预期效果 |
|------|---------|---------|
| **内存有限** (< 8GB) | `qwen3:1.7b` / `qwen2.5:3b` | 内存占用低，响应快 |
| **追求速度** | 启用 Ollama GPU 加速 | 推理速度提升 3-5 倍 |
| **质量优先** | `qwen3:14b` / `qwen3:32b` | 输出更精准 |
| **中文场景** | `qwen3` 系列 | 中文能力优异 |

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
# 实时日志
tail -f data/logs/agent.log

# 错误日志
grep ERROR data/logs/agent.log

# 性能指标
grep "inference_time" data/logs/agent.log
```

### 数据库维护

```bash
# 备份数据库
cp data/databases/devpartner.db backups/devpartner_$(date +%Y%m%d).db

# 清理旧日志（保留最近 90 天）
python scripts/cleanup_old_logs.py

# 数据库完整性检查
python scripts/check_db_integrity.py
```

---

## 🔄 版本迭代记录

### v7.5.0 (2026-07-13) - Engine Pattern 架构重构 ⭐
**重大变更**:
- ✅ server.py 从 4240 行 → 360 行薄壳入口（减少 91%）
- ✅ 8 个领域引擎按业务域封装 (core/*_engine.py)
- ✅ `@mcp_tool_handler` 统一装饰器消除样板代码
- ✅ HTTP REST 路由提取到 `routes/rest_api.py`
- ✅ 启动逻辑提取到 `core/bootstrap.py`
- ✅ 工具层添加 `register_*_tools(mcp)` 注册函数
- ✅ 删除废弃文件: `conversation_manager.py`, `conversation_analyzer.py`, `log_service.py`

**新增文件**:
- `core/conversation_engine.py` - 对话引擎 (已有，补充 register 函数)
- `core/knowledge_engine.py` - 知识引擎
- `core/system_engine.py` - 系统引擎
- `core/daily_engine.py` - 日报引擎
- `core/optimization_engine.py` - 优化引擎
- `core/memory_engine.py` - 记忆引擎
- `core/iteration_engine.py` - 迭代引擎
- `core/vault_engine.py` - Vault 引擎
- `core/bootstrap.py` - 启动与初始化
- `core/decorators.py` - 统一装饰器
- `routes/rest_api.py` - REST API 路由

**架构对比**:
| 维度 | v7.3 | v7.5 |
|------|------|------|
| server.py 行数 | 4240 | 360 |
| 业务逻辑位置 | 散落在 server.py | 集中在 core/*_engine.py |
| MCP 工具注册 | 内联在 server.py | 每个 Engine 自带 register 函数 |
| HTTP 路由 | 混在 server.py | 独立 routes/rest_api.py |
| 启动逻辑 | 内嵌 server.py | 独立 core/bootstrap.py |

详见 [CHANGELOG.md](./CHANGELOG.md)

### v7.3.0 (2026-07-10) - LLM 引擎迁移至 Ollama ⭐
**重大变更**:
- ✅ 推理引擎由 llama-cpp-python 迁移至本地 Ollama HTTP API
- ✅ `LLMService` 重写：通过 `POST /api/chat` 调用 Ollama，零 GGUF 文件管理
- ✅ 配置精简：移除 `model_path`/`n_ctx`/`n_gpu_layers` 等，新增 `ollama_model`/`ollama_timeout`
- ✅ 移除 `llama-cpp-python` / `modelscope` 依赖，`requirements.txt` 仅保留 `ollama`（可选）
- ✅ 新增 `record_version_upgrade` MCP 工具手动触发版本记录

**同期能力（v7.3.0/7.3.1/7.3.2）**:
- 🗂️ 业务知识提取器（通用 Prompt 模板，从对话提取业务规则/架构决策）
- 📚 Obsidian Vault 导出器（业务知识卡片 → `data/vault/`）
- 🔍 `question_with_context` 支持 `project_name` + `category`（business/skill 数据层隔离）
- 🖥️ 运维面板保留（`/api/system/*`、`/api/tasks/*`、`/api/health/*`、`/api/trends/*`）

### v7.2.0 (2026-07-09) - 四阶段优化 ⭐
**重大变更**:
- ✅ conversation_steps 数据回写修复（knowledge_point_ids/duration_ms/started_at）
- ✅ 生命周期兜底清理（孤儿步骤自动回收）
- ✅ 数据库表文档规范（11 张表结构化注释）
- ✅ 新增技能复习提醒 + 遗忘曲线 + 知识关联同步
- ✅ Schema 收敛（conversation_id 双FK策略）
- ✅ 全系统版本号统一为 7.2.0

**新增功能**:
- `get_stale_skills()` - 技能复习提醒
- `get_forgetting_curve()` - 遗忘曲线可视化
- `sync_knowledge_relations()` - 知识关联同步
- `_auto_cleanup_orphan_steps()` - 孤儿步骤自动清理

### v7.1.0 (2026-07-07) - LLM 双层分析
- ✅ Step 级 + Conversation 级双层 LLM 分析引擎
- ✅ Step→Task 链式异步任务

### v7.0.0 (2026-07-07) - 总分总对话架构
- ✅ 总分总三步走模式（create→record_step×N→finalize）
- ✅ conversation_archive 标记 @deprecated
- ✅ 数据清理服务 + 会话管理器

### v6.0.4 (2026-07-05) - CodeBuddy 兼容修复
- 修复 CodeBuddy Accept header 兼容问题

### v6.0.3 (2026-07-04) - ModelScope 容器修复
- 修复容器崩溃重启循环

### v6.0.0 (2026-07-03) - LLM 驱动架构重构 ⭐
- ✅ 新增 `LLMUnifiedAnalyzer` 统一分析引擎
- ✅ 废弃 3600+ 行硬编码规则，代码精简 93%
- ✅ 对话分析、日报生成、自我改进全面 LLM 化
- ✅ 项目结构标准化重组

### v5.2.0 (2026-07-03) - 异步任务队列
- 异步后台任务队列 + 代码清理

### v5.1.0 (2026-06-28) - 性能优化
- LLM 服务预加载和缓存机制
- 数据库连接池优化
- 异步任务队列改进

### v5.0.0 (2026-06-20) - 架构升级
- Schema 升级到 v5.0
- 新增 knowledge_points 表
- 任务队列系统引入

[查看完整历史 →](./CHANGELOG.md)

---

## 🐛 故障排查

### 常见问题

#### Q1: LLM 服务启动失败？

**症状**: `❌ Ollama 服务不可达` 或分析功能不可用

**解决方案**:
1. 确认 Ollama 已安装并运行: `ollama list`（应列出已拉取的模型）
2. 确认模型已拉取: `ollama pull qwen3`
3. 确认 `config.yaml` 的 `llm.ollama_model` 与 `ollama list` 中的名称一致
4. 如 Ollama 不在本机，设置环境变量 `OLLAMA_BASE_URL=http://<host>:11434`
5. 查看详细错误: `cat data/logs/agent.log | grep -i error`
6. Ollama 不可用时系统自动降级到规则引擎，核心功能不受影响

#### Q2: 内存不足（OOM）？

**症状**: Ollama 进程被系统杀死

**解决方案**:
- 改用更小模型: `ollama pull qwen3:1.7b`，并在 `config.yaml` 设置 `llm.ollama_model: "qwen3:1.7b"`
- 推理由 Ollama 独立进程负责，本项目自身内存占用很低

#### Q3: 推理速度太慢？

**症状**: 单次分析 > 30 秒

**优化方案**:
1. 启用 Ollama GPU 加速（安装对应 CUDA 版本的 Ollama）
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
6. 推送分支: `git push origin feature/new-feature`
7. 创建 Pull Request

### 代码规范

- 遵循 PEP 8 风格指南
- 类型注解（Python 3.10+）
- 中文注释（面向中文开发者）
- 所有公开函数必须有 docstring

### 测试要求

- 新功能必须包含单元测试
- 测试覆盖率 > 80%
- 集成测试覆盖主要流程

---

## 📄 许可证

MIT License

Copyright (c) 2026 DevPartner Team

---

## 🙏 致谢

- [Qwen](https://qwenlm.github.io/) - 强大的开源大语言模型
- [Ollama](https://ollama.com/) - 简单的本地大模型运行与管理框架
- [Model Context Protocol](https://modelcontextprotocol.io/) - 标准化的工具调用协议

---

## 📞 联系我们

- 📧 Email: devpartner@example.com
- 💬 Issues: [GitHub Issues](https://github.com/your-repo/devpartner/issues)
- 💬 Discussions: [GitHub Discussions](https://github.com/your-repo/discussions)

---

<p align="center">
  <strong>⭐ 如果这个项目对你有帮助，请给一个 Star！⭐</strong><br>
  <em>Made with ❤️ by DevPartner Team</em>
</p>