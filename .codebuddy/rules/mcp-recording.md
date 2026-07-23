# DevPartner MCP 记录强制规则

## 触发条件

**每次对话，只要涉及以下任一场景，必须执行 MCP 总分总记录流程**：

- 代码修改（创建/编辑/删除文件）
- 问题排查（debug、错误分析）
- 配置变更
- 方案设计讨论
- 技术学习/知识问答
- 任何产生实质性工作内容的对话

**可以不记录的例外**：
- 纯问候（"你好""今天星期几"）
- 用户明确说"不用记录"

## start_conversation 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `client` | ✅ | 固定 `"codebuddy"` |
| `topic` | ✅ | 对话主题 |
| `task_type` | ✅ | debug/refactoring/coding/config/design/learning/general |
| `user_intent` | ✅ | 用户真实意图 |
| `priority` | ⭕ | 默认 `"medium"` |
| `system_id` | ✅ | 工作目录根目录名称 |
| `user_raw_input` | ✅ | 用户原始输入原文 |
| `ai_analysis` | ✅ | AI 深度分析思考过程 |
| `trace_id` | ⭕ | 外部调用链追踪ID（CodeBuddy 的 traceId） |
| `request_id` | ⭕ | 外部会话请求ID（CodeBuddy 的 conversationRequestId） |
| `external_conv_id` | ⭕ | 外部系统会话ID（CodeBuddy 的 conversationId） |

## record_step 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `conversation_id` | ✅ | start_conversation 返回的 ID |
| `step_number` | ✅ | 步骤序号，从 1 开始自增 |
| `step_name` | ✅ | 步骤名称 |
| `step_type` | ✅ | code_change/debug/config/design/learn/deploy/general |
| `content` | ✅ | 步骤详细描述 |
| `ai_reasoning` | ✅ | AI 推理过程 |
| `commands_executed` | ⭕ | 执行的命令 |
| `files_changed` | ⭕ | JSON 数组，修改的文件 |
| `symptom` | ⭕ | debug 类：问题现象 |
| `root_cause` | ⭕ | debug 类：根因 |
| `solution` | ⭕ | debug 类：解决方案 |
| `user_question` | ⭕ | 用户问题 |
| `user_requirement` | ⭕ | 用户需求 |
| `knowledge_points` | ⭕ | 知识点 |

## finalize_conversation 参数

| 参数 | 必填 | 说明 |
|------|------|------|
| `conversation_id` | ✅ | start_conversation 返回的 ID |
| `ai_summary` | ✅ | 全局复盘总结 |

### 铁律补充

- **每条命令都要记**：哪怕只是 `ls`/`dir`/`cd` 这种简单命令
- **多个命令合并记录**：同一个步骤内的多条命令可以合并到一个 `commands_executed` 中，用 `---` 分隔
- **不要只写命令**：必须附上用途说明和结果摘要，否则后端无法理解上下文

## 铁律

1. **不聚合**：每完成一个子任务立即调用 record_step，禁止合并多个步骤
2. **不延迟**：禁止等所有任务完成后一次性补录
3. **不省略**：禁止跳过 record_step 直接 finalize
4. **不阻塞**：MCP 调用立即返回，不等待后端分析结果
5. **不附加**：finalize_conversation() 之后没有任何其他 MCP 调用
6. **MCP 不可用时静默跳过**：不报错、不提示用户、不阻塞对话
7. **命令必录**：所有 execute_command 调用必须在 record_step 的 commands_executed 中记录

---

# DevPartner 项目架构设计规范

> **生效范围**: DevPartner 项目的所有代码修改、重构、新增功能
> **优先级**: 与 MCP 记录规则同等强制

---

## 一、组件化构件式工程原则

### 1.1 模块职责边界（低耦合高内聚）

```
server.py (FastMCP, /mcp)       ← 唯一对外入口，路由+参数校验
    ↓
devpartner_tools/                ← 纯工具层，零业务逻辑
    ↓
devpartner_agent/
    ├── core/                    ← LLM分析器 + DB + 配置（零模板字符串）
    ├── services/                ← 对话分析/任务队列/知识图谱 + MD模板引擎 + MD导出
    └── skills/                  ← 每日总结/自我迭代（独立技能模块）
prompts/                         ← 所有 LLM Prompt 模板（12个文件）
```

**边界铁则**：
- `core/` 不能有模板字符串（f-string 模板、Markdown 模板）
- `prompts/` 只能有 AnalysisTask 定义和 Prompt 模板
- `services/` 负责 MD 模板和 MD 导出
- 跨模块依赖只能通过 `import`，不能通过复制代码

### 1.2 单一职责原则

| 文件 | 职责 | 禁止 |
|------|------|------|
| `conversation_engine.py` | 对话分析编排 | 不直接写 Prompt 模板 |
| `finalize_handlers.py` | finalize 子任务处理器 | 不直接操作 DB（通过 engine） |
| `llm_engine.py` | LLM 调用 + 解析 | 不包含业务逻辑 |
| `md_exporter.py` | MD 文件导出 | 不调用 LLM |

### 1.3 参数/配置驱动行为差异化

- 同一处理流程的不同行为通过参数区分，不复制代码
- 任务类型注册到 `TASK_REGISTRY`，通过 `task_type` 路由
- 配置统一在 `devpartner_agent/core/config.py`，不在代码中硬编码

---

## 二、代码修改纪律

### 2.1 添加方法/类的前置检查（3 问）

每次添加新方法/新类之前，必须自问：

1. **这真的需要吗？** — 现有方法/工具/库能否直接满足？
2. **有更简单的方案吗？** — 用更少的代码、更少的抽象解决问题
3. **会引入新问题吗？** — 新代码是否会导致重复、循环依赖、职责混乱？

> 遵循 Ponytail 原则：最短路径即正确路径。**删除优于添加。**

### 2.2 修改后影响面检查

每次修改任何代码，必须做：

1. **搜索调用方**：`grep` 被修改的函数/方法名，确认所有调用方兼容
2. **搜索导入链**：检查 `import` 链，确认没有循环依赖
3. **DB 影响**：如果改了数据写入逻辑，确认 DDL 与代码一致
4. **任务队列影响**：如果改了 task_type 的处理逻辑，确认 task_queue 兼容
5. **全链路跑通**：从入口到出口完整验证

### 2.3 旧版本代码删除

- 方法迁移/重构完成后，**立即删除**旧版本代码
- 不允许"保留向后兼容"的兼容空壳（除非有明确过渡期计划）
- 不允许注释掉的废弃代码留在文件中
- 删除后全局搜索确认零引用

---

## 三、DDL 变更流程

### 3.1 变更规范

每次数据库结构变更，必须按以下 3 步执行：

1. **更新 `data/schema.sql`**：保持完整 DDL 为最新
2. **创建 migration 脚本**：`data/migrations/vX.Y.Z_description.sql`，包含 ALTER/CREATE 语句
3. **记录到 `data/migrations/README.md`**：简要说明变更内容和原因

### 3.2 变更检查清单

- [ ] `data/schema.sql` 已更新
- [ ] migration SQL 已创建
- [ ] 代码中的 INSERT/UPDATE 列与 DDL 一致
- [ ] 无多余列（代码写了但 DDL 没有的列）

---

## 四、知识导出链路唯一性原则

### 4.1 数据查询链

```
conversation_id
    → conversation_steps (step_id)
        → knowledge_points (source_id = step_id)
```

**关键规则**：`knowledge_points.source_id` 有两种格式：
- `step_id`（step_analysis 写入时）
- `conversation_id`（finalize 阶段 knowledge_extractor 写入时）

查询时 **必须同时匹配两种格式**：`WHERE source_id IN (step_ids + [conversation_id])`

### 4.2 导出路径唯一性

| 导出类型 | 唯一路径 | 触发时机 |
|---------|---------|---------|
| 知识卡片 MD | `handle_conversation_finalize → vault_export_batch` 异步任务 | finalize 完成后 |
| 知识摘要 MD | `handle_finalize_knowledge_graph → export_knowledge_summary` | finalize 子任务 |
| 项目画像 MD | `handle_finalize_business_tech → export_project_profile` | finalize 子任务 |
| 用户画像 MD | `handle_finalize_user_profile → export_user_profile` | finalize 子任务 |

**铁则**：每种导出只能有一条路径。发现重复路径立即删除多余的。

### 4.3 级联链路

```
step 全完成
    → AI 调 finalize_conversation (MCP)
        → handle_conversation_finalize
            → 提交 3 子任务:
                ├── finalize_business_tech
                ├── finalize_user_profile
                └── finalize_knowledge_graph
            → 提交 vault_export_batch 异步任务
    → 3 子任务全部完成
        → _check_finalize_sub_tasks
            → conversations status='completed'
```

---

## 五、全链路验证检查清单

每次完成一轮修改后，必须逐项验证：

- [ ] 数据写入正确：`SELECT` 确认数据已写入目标表
- [ ] 数据查询正确：用实际数据验证查询 SQL 能返回预期结果
- [ ] MD 文件导出：检查文件已生成且内容非空
- [ ] 任务队列状态：确认 task_queue 中关联任务状态正确
- [ ] 无死代码：`grep` 确认被删除的方法名无残留引用
- [ ] DDL 一致：`PRAGMA table_info` 与代码中的 INSERT 列一致
