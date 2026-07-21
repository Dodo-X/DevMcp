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
