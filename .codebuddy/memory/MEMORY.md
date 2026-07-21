# DevPartner 项目参考（仅供 AI 参考，非数据存储）

> **数据存储**: 所有对话/用户画像/知识图谱数据由 MCP 管理（SQLite），此文件仅保留项目技术参考。

## 当前状态（v9.5.1 | 2026-07-21）

> **2026-07-21 v9.5.1 异步任务架构升级**:
> - **心跳机制**: Worker 每 45s 更新 `last_heartbeat`，僵尸检测优先用心跳时间（1h 无心跳→僵尸）
> - **进度报告**: `update_task_progress(task_id, progress, partial_result, status_note)` + `get_running_tasks_with_progress()`
> - **流式输出**: `llm_engine.infer()` 新增 `on_progress` 回调，使用 Ollama `stream: true` 每 10 token 回调进度
> - **Worker 上下文注入**: `_dispatch_task_execution()` 自动注入 `_task_id` + `_progress_callback` 到 payload
> - **Scheduler 解耦**: `_execute_daily_summary()` 改为异步提交 `queue.submit_task("daily_summary")`，不再同步等待 LLM
> - **新增 handler**: `handle_daily_summary()` — 日报完整异步处理器，替代 Scheduler 中的同步逻辑
> - **新增 REST API**: `/api/tasks/progress` (GET) + `/api/tasks/job-status?task_id=xxx` (GET)
> - **新增 task_queue 字段**: `last_heartbeat`, `progress`, `partial_result`, `status_note`
> - 改动文件: `task_queue.py`, `llm_engine.py`, `rest_api.py`, `prompts/_common.py`, `conversation_engine.py`, `scheduler.py`

> **2026-07-21 v9.5.0 LLM 超时策略重构**:
> - 用户明确要求：prompt 必须专业完整（不砍质量），可以慢但不能超时报错
> - **回退了 v9.5.0 的 prompt 精简**，恢复日报/深度分析/对话分析/步骤分析为专业完整版（~4000+ 字符，完整 JSON schema）
> - **三层超时策略**：
>   1. `ollama_timeout: 0`（config.yaml + config.py）— HTTP 请求不设超时，让 Ollama 自然完成
>   2. `llm_engine.infer()` retries 2→5，初始 60s，指数退避到 1920s（32分钟），确保一定能跑完
>   3. `task_queue` 默认 timeout 600→3600s，僵尸检测 1200→3600s — 任务级兜底 1h
> - 去掉了 conversation_engine/scheduler 中的硬编码 `timeout_seconds=900`，统一用 task_queue 默认值
> - 原则：**宁慢勿丢，后台运行不在乎时间**
> - `dashboard.html` 的 `fetchJSON(url)` 只接受一个参数，第二个 `options` 被忽略，导致所有通过它发 POST 的 API 实际发 GET → 405
> - 受影响 API: `/api/reports/generate`, `/api/reports/generate-daily`, `/api/growth/review`, `/api/growth/apply` (共5处调用)
> - 修复: `fetchJSON(url, options)` → `fetch(url, options || {})`，一行改动修复5个API
> - 其他 POST API (cancel/pending-analyses/archive/ollama/cleanup/knowledge-match/create/projects-query) 直接用原生 `fetch()` 不受影响

> **2026-07-20 v9.3.0 Dashboard修复+存量数据修复**: 
> - 技能领域分布与技能雷达功能重复问题：领域分布改为展示领域下具体技能名列表（`skills` 数组），雷达保留掌握度评分
> - 知识库搜索/匹配结果从卡片改为表格展示（标题/领域/分类/置信度/使用次数+摘要行）
> - 项目列表从混乱展示改为表格（#/项目名称/类型/操作），移除路径展示，新增 `selectProject()` 快捷选择
> - 项目查询 API 修复：`undefined` → `''` 避免 JSON 序列化问题；后端加 raw_body 解析 + 错误处理
> - 系统健康模块：`get_system_health()` 每个子模块独立 try-catch，防止单点崩溃
> - 系统诊断：移除废弃的 `rule_engine` 引用，改为数据库表统计检查
> - 数据清理预览：`escHtml()` 修复为 `String(s)` 强制转换，解决 `(s||"").replace is not a function` 错误
> - **存量技能数据修复**：`user_skills` 表 41 条碎片化记录 → 7 个标准领域（AI/LLM、DevOps、Python、前端、数据库、架构设计、通用工程），通过 `scripts/fix_skill_domains.py` 合并完成
>
> **2026-07-20 v9.3.1 技能领域标准化根治**:
> - 新建 `devpartner_agent/core/skill_domain_standard.py` 作为全项目统一数据源（normalize_domain + DOMAIN_KEYWORD_MAP）
> - llm_engine.py: 删除旧的 SKILL_DOMAIN_MAP，入库前强制 `normalize_domain(skill_domain)`
> - knowledge_extractor.py: `_save_knowledge()` 入库前强制标准化 skill 类型 domain
> - fix_skill_domains.py: 改用统一数据源，删除本地映射表
> - knowledge_points 表存量修复: 49 条非标准 domain → 6 个标准领域（scripts/fix_kp_domains.py）

> **2026-07-20 v9.2.2 代码清理**: 删除3个空文件（optimization_engine.py/optimization_loop.py/routes/__init__.py），清理 config.yaml 废弃配置项（services/rules/fallback_to_rules/daily_logs_dir），清理 config.py 零引用配置类（LogServiceConfig/DialogueServiceConfig/EvolutionServiceConfig/RulesConfig），清理3个 __init__.py 零引用导出，删除 BusinessKnowledgeExtractor 别名。

> **2026-07-20 v9.2.1 优化建议审核面板**: Dashboard 新增"优化建议"Tab（page-suggestions），对接 growth_analysis 表，支持同意/拒绝/反馈/标记已应用。growth_analytics.py 采纳率统计从 optimization_feedback 迁移到 growth_analysis。

> **2026-07-20 v9.2.0 全局清理**: 删除 conversations 表6个 v1 废弃字段 + depends_on 死字段 + archived_conversations 表 + insert_conversation 方法。files_touched 改为从 conversation_steps 聚合。MCP instructions 强化为强制流程。

> **2026-07-20 补充**:
> - Dashboard 新增 Ollama "重新连接"按钮（调用 POST /api/ollama/start），LLM 状态卡片增加 reconnectOllama() JS 函数
> - 数据库手动补全了 ai_analysis 列（agent_context 已在 v9.2.0 废弃，不应添加）
> - 修复报告页日期选择器：onReportTypeChange() 不再无条件覆盖日期为今天，改为判空后设默认值
> - **报告页选择器重构**：日报保留 type=date；周报改为下拉框列出所有ISO周（"2026年第N周 (MM-DD ~ MM-DD)"）；月报改为下拉框列出所有月份（"2026年N月"）；年报保持年份下拉框。新增 initWeekPicker()/initMonthPicker()，value 存周一/月初日期兼容后端 target_date

### 快速启动
```bash
python server.py 7860
```
- 端口: **7860**，Transport: **streamable-http**，端点 `/mcp`

### 技术栈
- FastMCP + SQLite(WAL) + Python 3.10+ + Ollama(qwen3)

## 架构

```
server.py (FastMCP, /mcp)
├── prompts/          # 所有 LLM Prompt 模板（v8.5 提取到根目录）
├── devpartner_tools/ # 纯工具层（12个工具）
└── devpartner_agent/ # 智能层
    ├── core/         # LLM分析器 + DB + 配置 + 兼容桥
    ├── services/     # 对话分析/任务队列/知识图谱/用户画像
    └── skills/       # 每日总结/自我迭代
```

## 关键决策

1. **数据唯一源**: SQLite `data/databases/devpartner.db`，客户端零写入
2. **LLM**: Ollama HTTP API（v7.3 起替代 llama-cpp-python）
3. **总分总录制**: start_conversation → record_step → finalize_conversation
   - v9.1: 三个方法均接收 AI 文本分析，系统从 DB 读结构化数据，双向互补
4. **包导入**: 绝对导入 `from devpartner_agent.core.xxx`
5. **废弃**: optimization 引擎（v8.3）、daily_log Markdown（v6.2）、conversation_archive 表（v7.0）

## 致命 Bug 速查

| 问题 | 根因 | 修复 |
|------|------|------|
| SQL 占位符丢失 | `query_local("""` → `query_local("""""` | 全局替换+18处手动修复 |
| conversation_steps FK 失败 | conversation_id 缺 UNIQUE INDEX | 启动时 CREATE UNIQUE INDEX |
| SSE ClosedResourceError | 客户端断开后 writer.send() | 三重防护补丁 |
| LLM 分析结果被丢弃 | Prompt 输出字段与 handler 消费字段不匹配 | 重写 step.py Prompt + 字段对齐 |

## 核心表结构

- **conversations**: 主对话表（conversation_id UNIQUE）
- **conversation_steps**: 子任务步骤（FK → conversations）
- **knowledge_points**: 知识点库
- **task_queue**: 异步任务（step_analysis / conversation_finalize）
- **user_skills / improvement_log / user_skill_plan**: 用户画像

## 版本演进

| 版本 | 关键变更 |
|------|---------|
| v7.0.0 | 总分总对话分析架构 |
| v7.3.0 | LLM 迁移至 Ollama，移除 llama-cpp-python |
| v8.0.0 | system_id 多客户端支持 |
| v8.3.0 | 清理 optimization 遗留代码，引擎 5→4 |
| v8.4.0 | 清理无引用方法(6个)+空壳register+废弃Dashboard HTML路由 |
| v8.4.1 | 恢复 Dashboard HTML 运维面板（21KB），从 JSON 导航恢复为完整可视化面板 |
| v8.5.0 | Prompt提取到prompts/、MCP解耦、消除硬编码、GROWTH_ANALYSIS双维度 |
| v8.5.1 | Dashboard VERSION模板替换修复 + 冗余API清理(12个端点, 53→41) |
| v8.5.2 | Dashboard全面对接剩余API，新增5个Tab页面(23KB→47KB)，41个端点全覆盖 |
| v8.5.5 | 定时任务调度器审计修复（5个Bug） |
| v8.5.6 | 系统运维面板修复（LLM状态null崩溃 + WriteTracker接入 + pending_retry重试） |
| v8.5.7 | Dashboard报告Tab页（日/周/月/年手动触发+覆盖+预览），新增4个报告API |
| v8.5.8 | 项目列表修复（connected_systems→真实项目名）+ 知识提取domain规则 + 报告时间选择器优化 |
| v8.5.9 | CleanupScheduler.cleanup() Bug修复 + 运维面板tooltip注释 + WriteTracker状态区分 |
| v9.0.0 | **finalize_conversation 解耦重构**: AI只需传 conversation_id，Worker从SQLite读取全量数据；消除AI→MCP的冗余数据传递 |
| v9.1.0 | **双向互补分析架构**: start_conversation(+ai_analysis)、record_step(ai_reasoning强化)、finalize_conversation(+ai_summary)；AI传文本分析+系统从DB读结构化数据 |
| v9.1.1 | **消除硬编码规则提取**: 删除 _extract_behavior_signals/_fallback_analysis/_estimate_skill_level/_estimate_time_spent；behavior_signals 改为异步 LLM 分析 ai_analysis 填充；新增 TASK_BEHAVIOR_SIGNALS prompt + behavior_signals_extraction handler；MCP 参数对齐(agent_context, client_request_id)；DB 新增 agent_context 列 |
| v9.2.0 | **全局废弃清理**: 删除 conversations 6个 v1 字段 + depends_on 死字段 + archived_conversations 表 + insert_conversation 方法；files_touched 改为从 conversation_steps 聚合；MCP instructions 强化为强制流程；新增 .codebuddy/rules/mcp-recording.md |
| v9.2.1 | Dashboard 优化建议审核面板 + growth_analytics.py 采纳率统计修复 |
| v9.2.2 | **代码清理**: 删除空文件+废弃配置项+零引用配置类+零引用导出+死别名 |

## 版本发布检查清单（AI 必执行）

每次版本更新后，AI 必须主动执行以下 6 项结构化审计：

1. **模块引用完整性** — 扫描所有 `__init__.py` 的导出项，grep 全项目引用；标记零引用导出
2. **数据生命周期完整性** — 对比 DDL CREATE TABLE 字段 vs INSERT/UPDATE 实际写入字段 vs SELECT 查询字段；标记僵尸字段和缺失字段
3. **配置项使用情况** — 解析 config.yaml 所有叶子节点，grep 每个配置项的代码引用；标记废弃配置
4. **文件级死代码** — 列出所有 .py 文件中的公开函数/类，grep 全项目调用；标记零调用公开 API
5. **import 副作用** — 搜索 `from X import Y` + `get_xxx()` 模式，检查获取实例后是否有后续方法调用
6. **版本注释一致性** — 搜索代码中的版本号引用（vX.Y），对比当前实际版本；标记过时注释

## 禁止事项

- ❌ 测试代码混入业务模块
- ❌ 配置文件散落各处（统一 config.yaml）
- ❌ 工具代码放在 agent 中
- ❌ `duration_ms = 0` 硬编码
- ❌ LLM 输出不经空值守卫直接拼接
