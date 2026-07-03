# DevPartner 项目记忆

## 项目结构（2026-06-28 重构后）
- **server.py** — 唯一启动入口，同时注册 tools + agent 共 79+ 个 MCP 工具
- **devpartner_tools/** — 纯工具层（无状态），6 大类 25 个工具
- **devpartner_agent/** — 智能管家层（有状态），48+ 个工具
- 端口限制：仅 7860 和 8080

## 关键决策
- 目录名从 `devpartner-tools`/`devpartner-agent` 改为 `devpartner_tools`/`devpartner_agent`（Python 包名不能含连字符）
- 使用包导入替代 `sys.path.insert` hack，IDE 能正确识别
- 修复了 `get_rule_engine` → `get_engine`、`get_dialogue_service` → `get_dialogue` 等函数名不一致问题
- 每个子包有 `pyproject.toml`，项目根也有 `pyproject.toml`
- **数据存储原则**：系统独立于客户端，所有数据写入 `data/` 目录，不使用 `.codebuddy/memory/`

## 技术栈
- FastMCP 框架
- SQLite（WAL 模式）
- Python 3.10+

## Transport 选择（2026-07-02 更新）
- **使用 `streamable-http` transport**，非 `sse`
- 默认端点路径为 `/mcp`，无需显式指定 path
- Dashboard 前端直接 POST 到 `/mcp` 调用 JSON-RPC
- streamable-http 同时支持 GET/POST/DELETE，兼容性更好，无 405 问题
- SSE transport 已被废弃，相关补丁代码保留但不生效

## self_iterate 自动触发机制（2026-07-01 v4.0.0）

### 触发条件
- **核心条件**：每 20 次有意义对话（record_dialogue / record_conversation / log_conversation）自动触发
- 对话计数器持久化在 `data/.conversation_counter.json`，重启不丢失
- `mark_optimization_done("optimize")` 重置计数器基准

### 输出维度
1. **用户画像**：技能领域分布、投入时间、强弱项识别
2. **技能评估**：等级分布、成长趋势、学习建议
3. **批评指点**：从优化反馈中提取用户纠正/不满信号
4. **未来规划建议**：基于技能规划进度和目标调整
5. **MCP 工具优化**：零使用工具精简、高频工具增强、利用率分析
6. **系统健康度**：数据库膨胀、规则引擎、服务发现
7. **系统反馈**：对话趋势、优化标记状态

### 数据来源
- `conversations` 表（有意义对话数）
- `user_skills` 表（技能画像）
- `user_skill_plan` 表（技能规划）
- `mcp_tool_registry` 表（工具调用统计）
- `optimization_feedback` 表（反馈统计）
- `improvement_log` 表（改进建议）
- `version_history` 表（版本演进）
- `data/.conversation_counter.json`（对话计数器）
- `data/.optimization_state.json`（优化状态）

### 新增工具
- `save_self_iterate_results`：将 self_iterate 分析结果持久化到数据库各表

### 触发链路（v4.0）
```
record_dialogue/record_conversation/log_conversation 调用
    → AutoLogMiddleware: 有意义对话计数器 +1
    → 累计 20 次 → optimization_hint.json 标记 pending
    → AI客户端调用 check_optimization_needed → should_optimize=true
    → AI客户端调用 self_iterate → 全维度分析
    → AI客户端调用 save_self_iterate_results → 写入 DB 各表
    → AI客户端调用 mark_optimization_done → 重置计数器
```

### 修改文件
- `server.py`：v4.0.0 重构，AutoLogMiddleware 有意义对话计数、check_optimization_needed 对话驱动、新增 save_self_iterate_results
- `devpartner_agent/skills/self_iterate.py`：v4.0 增强，_collect_system_data 收集7维度数据、_generate_data_driven_suggestions 全维度分析
- `devpartner_agent/config.yaml`：版本号升级为 4.0.0

## AI 行为强制约束（2026-07-01 v6.3）

### record_dialogue 强制调用规则
- **每次与用户完成一轮对话后，AI 必须立即调用 `record_dialogue` 工具**
- 不调用会导致：对话不记录到数据库、daily_logs 无当日记录、有意义对话计数器不更新、self_iterate 永远无法自动触发
- 调用时机：在完成用户请求并给出最终回复之后，立即调用
- `record_dialogue` 已从 `_AUTO_LOG_SKIP_TOOLS` 中移除，调用时会正确触发有意义对话计数

### 用户画像协同机制（v6.3 新增）
- `record_dialogue` 和 `record_conversation` 必须传入 `user_traits` 参数
- 9 个维度：skills_observed, behavior_notes, mistakes, strengths, communication_style, decision_pattern, tech_interests, areas_for_growth, emotional_state
- 映射到 DB 表：user_skills / improvement_log / user_skill_plan / optimization_feedback

### 数据写入路径（v6.2）
- **唯一数据源**：SQLite 数据库 `data/databases/devpartner.db`（conversations + conversation_archive 表）
- **daily_log Markdown 文件已废弃**：`data/daily_logs/conversation_YYYY-MM-DD.md` 不再写入
- **CodeBuddy 客户端不做任何数据记录**：不写 .codebuddy/memory/、不写 data/ 目录
- **跨会话记忆**：通过 MCP 工具 `update_memory` / `get_memory` 操作

## MCP 工具注册表 v4.1 优化（2026-07-01）

### 问题
- `mcp_tool_registry` 表始终为空（0行），`record_tool_call` 只做 UPDATE，工具不存在时不自动注册
- `save_self_iterate_results` 只生成建议不执行实际优化，零使用工具不会被禁用

### 修复内容
1. **`record_tool_call` 自动注册**：工具不存在时自动 INSERT OR IGNORE 到 `mcp_tool_registry`
2. **新增 DB 方法**：`update_tool_status`、`batch_update_tool_status`、`get_zero_usage_tools`、`get_all_tools`
3. **`save_self_iterate_results` v4.1**：新增 MCP 工具优化执行
   - 零使用工具 → `batch_update_tool_status(..., "disabled")`
   - 废弃工具 → `batch_update_tool_status(..., "deprecated")`
   - 高频工具 → `insert_improvement("tool_enhance", ...)`
   - 所有操作记录到 `evolution_log`
4. **`self_iterate.py` v4.1**：工具分析增强
   - 安全白名单：核心工具永不自动禁用
   - 生成 `mcp_tool_actions` 可执行指令字段
   - 零使用>=3个时自动生成 disable 指令
   - 高频工具自动生成 enhance 指令

### 安全白名单（永不自动禁用）
`check_optimization_needed`, `mark_optimization_done`, `self_iterate`,
`save_self_iterate_results`, `record_dialogue`, `record_conversation`,
`log_conversation`, `get_tool_registry`, `system_diagnose`,
`get_capabilities`, `check_rule`, `get_rules`, `process_user_feedback`

---

## 2026-07-02 文档规范化

### README 重写
- 重写了 README.md：规范化结构（概览→能力→架构→快速开始→配置→LLM→结构→运维→故障排查）
- 修正版本号混乱：README v5.0.0 / config v4.0.0 / server.py v4.3.0 → 统一为 v5.1.0
- 删除了 README 中大量冗余的 v5.0 Ollama 示例代码和过时配置说明
- 用简洁的表格替代冗长的代码示例

### 版本迭代独立
- 创建 CHANGELOG.md：从 v1.0.0 到 v5.1.0 的完整版本迭代记录
- 遵循 Keep a Changelog 格式，语义化版本号
- 标注当前版本状态：server.py 实际版本 v4.3.0 → 统一升级到 v5.1.0

### 版本号统一修正
- server.py：v4.3.0 → v5.1.0
- config.yaml：v4.0.0 → v5.1.0
- config.py：v4.0.0 → v5.1.0
- Dockerfile：v4.0.0 → v5.1.0

### 当前架构
- LLM 引擎：llama-cpp-python 单引擎（v5.1）
- 模型：Qwen3.5-9B-Q4_1.gguf (~5.7GB)
- 不再依赖 Ollama

---

## 2026-07-02 v5.2 异步化 + 代码清理优化

### 异步化（核心优化）
- **后台任务队列**：新增 `_background_task_queue` + `_enqueue_background_task()`，daemon 线程消费
- **record_dialogue 异步化**：数据完整性校验、自动分析触发、用户特征融合、写入追踪 4 个后处理步骤移至后台线程
- **record_conversation 异步化**：用户特征处理和写入追踪移至后台
- **启动**：懒启动，首次 `record_dialogue` 时自动启动 worker 线程

### 代码清理
- **删除 `log_conversation` MCP 工具**：v3.0 起已废弃，依赖已废弃的 Markdown 日志
- **精简 `log_service.py`**：移除 8 个已废弃方法（append_to_daily_log、read_daily_log、list_logs、get_logs_range、list_old_logs、archive_old_logs、gap_check 等），从 285 行减至 70 行
- **清理 `cleanup_scheduler.py`**：移除对已删除的 `log_svc.list_old_logs()` 的调用

### Bug 修复
- **对话计数修复**：`record_dialogue`/`record_conversation` 原本在 `_AUTO_LOG_SKIP_TOOLS` 中，导致不会触发有意义对话计数 → 移到新的 `_NO_FEEDBACK_DETECTION_TOOLS`
- **_agent_tools_count 被清零**：`__main__` 中 `_agent_tools_count = 0` 在 `_collect_tool_names()` 之后执行，导致 `_record_version_on_startup` 中 `tools_count` 错误 → 移除清零行
- **conversation_archive.user_feedback 硬编码 "[]"** → 改为从分析结果动态获取
- **tools_count 兜底**：`_record_version_on_startup` 中如果 `_agent_tools_count` 为零，用 `mcp._tool_manager._tools` 实时计算

### 版本号最终统一
- server.py：VERSION = "5.1.0"，启动日志显示 v5.1.0
- config.yaml：agent.version = "5.1.0"
- config.py：AgentConfig.version = "5.1.0"
- Dockerfile：v5.1.0
- pyproject.toml：version = "5.1.0"

### 变更文件清单
- `server.py`：后台队列 + 异步化 + 删除 log_conversation + 计数修复 + 版本号
- `devpartner_agent/services/log_service.py`：精简（285→70行）
- `devpartner_agent/services/cleanup_scheduler.py`：移除废弃调用
- `devpartner_agent/config.yaml`：版本号
- `devpartner_agent/core/config.py`：版本号
- `pyproject.toml`：版本号
- `Dockerfile`：版本号
- `CHANGELOG.md`：新增 v5.2.0 记录
- `README.md`：已在上一步重写

---
## 2026-07-02 修复：SSE → Streamable HTTP + 会话管理导入错误

### Transport 切换
- `mcp.run()` transport 从 `sse` 改为 `streamable-http`（+ json_response=True + stateless_http=True）
- 删除手动 /mcp 代理路由（~60 行），改用 FastMCP 原生 Streamable HTTP 端点
- Dashboard `MCP_MESSAGE_PATH` 从 `/messages/` 改为 `/mcp`

### 406 → 400 → 成功
- 406: Streamable HTTP 需要 Accept header → Dashboard 加 `Accept: application/json`
- 400: 默认 stateful 模式需要 Mcp-Session-Id → 加 `stateless_http=True`

### 会话管理异常修复
- **根因**：`ai_optimizer.py:20` 中 `from core import KNOWN_CLIENTS` 导入路径错误 → 应为 `from devpartner_agent.core.identity import KNOWN_CLIENTS`
- **连锁反应**：services/__init__.py 导入 ai_optimizer 失败 → conversation_manager/task_queue 无法导入 → get_system_health MCP 工具返回错误
- **额外修复**：`__init__.py` 中 `from .llm_service import get_llm_service` 不存在（只有 LLMService 类），改为 `from .llm_service import LLMService`

---

## 2026-07-02 v5.2.0 完整版 — Web Dashboard + 知识图谱

### Web Dashboard (`/dashboard`)
- 新增 `devpartner_agent/dashboard.html`：纯 HTML/CSS/JS 单页应用
- 使用 Chart.js 绘制实时趋势图（活跃会话/运行中任务/知识库条目）
- 通过 MCP JSON-RPC API 获取数据（`get_system_health`/`get_queue_stats`/`get_v5_status`/`get_callback_stats`）
- 3 秒自动刷新，4 个指标卡片 + 任务队列 + 知识库 + 回调注册表 + 趋势图
- 在 `server.py` 中通过 `@mcp.custom_route("/dashboard")` 注册

### 知识图谱引擎
- 新增 `devpartner_agent/services/knowledge_graph.py`（~400 行）
- 从 `knowledge_points` 表自动构建节点和边
- 5 种边类型：shared_domain / shared_tags / same_source / explicit / similar_content
- 基于 BFS 的路径发现 + Jaccard 内容相似度
- 6 个新 MCP 工具：`build_knowledge_graph` / `get_knowledge_graph_stats` / `get_knowledge_neighbors` / `find_knowledge_path` / `get_knowledge_cluster` / `export_knowledge_graph`

### 新增/修改文件
- `devpartner_agent/dashboard.html`：新建
- `devpartner_agent/services/knowledge_graph.py`：新建
- `server.py`：新增 dashboard 路由 + 6 个知识图谱 MCP 工具
- `devpartner_agent/services/__init__.py`：导出 KnowledgeGraph
- `CHANGELOG.md`：更新 v5.2.0 完整内容
- `devpartner_agent/config.yaml`：v5.2.0
- `devpartner_agent/core/config.py`：v5.2.0
- `pyproject.toml`：v5.2.0
- `Dockerfile`：v5.2.0
