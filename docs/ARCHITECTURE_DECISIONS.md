# 架构决策记录 (Architecture Decision Records)

> 本文件记录 DevPartner 的关键架构决策（ADR），确保“为什么这样设计”可追溯。
> 新增决策请复制下方模板追加；废弃决策标记为 `状态: 已废弃` 并保留链接。

---

## ADR 模板（新增请复制）

```markdown
## ADR-XXX: <决策标题>

- 状态: 提议 / 采纳 / 已废弃
- 日期: YYYY-MM-DD
- 决策人: @owner

### 背景 (Context)
<遇到的问题、约束、可选方案>

### 决策 (Decision)
<我们决定怎么做，以及为什么>

### 后果 (Consequences)
<带来的好处、代价、后续需要跟进的事>
```

---

## ADR-001: 四层分层架构

- 状态: 采纳
- 日期: 2025（v9.5.5 重构）
- 决策人: @devpartner/core

**背景**：旧版 `devpartner_agent/` 模块边界模糊、依赖交叉，难以维护与测试。
**决策**：采用 `foundation`（配置/日志/追踪/异常/统一响应/通用工具）→ `backend/core`（引擎/DB/LLM 内核/任务队列）→ `backend/business`（业务服务）→ `backend/api_gateway`（REST）+ `mcp_service`（MCP 薄壳）+ `frontend`（预留） 的四层结构。MCP 仅暴露核心对话记录工具，不与 CodeBuddy 原生工具重复。
**后果**：职责清晰、可测试；MCP 层无业务耦合，便于独立部署。需保证各层只依赖下一层，禁止反向依赖（由架构评审把关）。

## ADR-002: 统一响应契约

- 状态: 采纳
- 日期: 2025
- 决策人: @devpartner/core

**背景**：历史 HTTP 与 MCP 返回结构不一致（`{code,message,data}` vs `{success,error}`），导致调用方解析混乱。
**决策**：HTTP 接口统一使用 `foundation/api_response` 工厂（`{code,message,data}`）；MCP 工具返回 JSON 字符串（`{"error":..., "success":...}`）。两者语义对齐（success 对应 code==0）。
**后果**：需在文档中明确两套信封的差异，避免调用方误用（已在测试中固化契约）。

## ADR-003: 线程安全 SQLite + WAL

- 状态: 采纳
- 日期: 2025
- 决策人: @devpartner/core

**背景**：多模块并发读写 SQLite 存在锁竞争与索引错建风险（已修复 `improvement_log` 索引在表创建前执行的问题）。
**决策**：统一经 `base_conn.py` 的读写锁管理器访问，启用 WAL 模式；DDL 顺序严格受控。
**后果**：并发安全；禁止业务层直接 `connect`，新增表须评审 DDL 顺序。

## ADR-004: 本地 LLM 推理 + 规则兜底

- 状态: 采纳
- 日期: 2025
- 决策人: @devpartner/core

**背景**：云端 LLM 受网络/合规约束。
**决策**：经 Ollama HTTP API 本地推理；流式响应按 `done` 标志结束（已修复流式 `done` 检测失效）；不可用时走规则引擎兜底，保证可用性。
**后果**：离线可用；需在 CI/测试中以 `LLM_TEST_MODE=mock` 隔离，避免测试依赖本地模型。
