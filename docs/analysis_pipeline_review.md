# DevPartner 分析流水线审计 & 改进方案

> 2026-07-21 | 用户提出的核心问题：不同分析阶段传什么数据、用什么 prompt、产出什么结果不合理

---

## 一、现状问题诊断

### 1.1 核心问题：分析阶段边界模糊，职责重叠

```
当前状态：
┌─────────────────────────────────────────────────────────────────────┐
│  Step Analysis（每个 step 触发一次 LLM 调用）                         │
│  ├─ 输入: step_name, content, symptom, root_cause, solution,         │
│  │        ai_reasoning, user_requirement, commands_executed           │
│  ├─ 输出: step_summary, skill_domains, difficulty,                    │
│  │        problem_solving_pattern (需求→推测→思路→为什么),             │
│  │        knowledge_points, commands_used, key_insights,              │
│  │        improvement_suggestions, related_tools,                     │
│  │        thinking_patterns, complexity_level                         │
│  └─ 存入: conversation_steps.output_data + knowledge_points 表         │
├─────────────────────────────────────────────────────────────────────┤
│  Conversation Finalize（对话结束时触发一次 LLM 调用）                   │
│  ├─ 输入: summary(从 steps 拼凑), self_reflection(=ai_summary),       │
│  │        user_traits(从 steps 聚合), key_decisions(空数组!),          │
│  │        steps_summary(只含 name/type/status/thinking_patterns),     │
│  │        topic, system_id, ai_analysis, ai_summary, client,          │
│  │        user_raw_input, project_context(=none)                      │
│  ├─ 输出: business_knowledge, user_profile(9维),                       │
│  │        technical_decisions, knowledge_graph, overall_assessment    │
│  └─ 存入: improvement_log + system_context_fragments                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 具体问题

| # | 问题 | 影响 |
|---|------|------|
| **1** | Step Analysis 的 `knowledge_points` 输出和 Finalize 的 `knowledge_graph` 输出**严重重叠** | LLM 做了两遍知识提取，浪费 token + 可能出现不一致 |
| **2** | Step Analysis 输出了 `problem_solving_pattern`（需求→推测→思路→为什么），这**本应是 Finalize 阶段做的事** | Step 阶段数据量太少，LLM 做不出有意义的"解题模式"分析 |
| **3** | Finalize 传给 prompt 的 `steps_summary` **只有 name/type/status/thinking_patterns**，**丢失了最关键的信息**：每个 step 的 `content`（AI 做了什么）、`ai_reasoning`（AI 怎么想的） | Finalize 的 LLM 看不到步骤细节，只能基于空壳做分析 |
| **4** | Finalize 的 `user_traits` 是从 steps 的 `input_data` 中 grep `%user_traits%` 拼凑的——但 steps 里根本没有 `user_traits` 字段 | user_traits 永远为空 {} |
| **5** | Finalize 的 `key_decisions` 被硬编码为空列表 `[]`（代码注释说"v9.2 decisions 字段已删除"） | 技术决策链分析没有数据源 |
| **6** | `user_profile` 分析要求 9 个维度（心理观察、情绪状态、沟通风格...），但这些需要**跨多天数据对比**才能得出结论 | 单次对话的数据量不足以支撑用户画像分析 |
| **7** | Step Analysis 和 Finalize 的 prompt 都要求输出 `skill_domains`，但没有明确的归并逻辑 | 同一技能可能被两个阶段以不同领域名记录 |

---

## 二、改进方案：三层递推分析流水线

### 2.1 设计原则

```
L0 → L1 → L2 递推，每层只做本层能做的事

L0 (Step):   零碎数据 → 知识点提取（纯信息提炼，不做推理）
L1 (Conv):   全对话数据 → 解题模式 + 技术决策（基于完整对话的推理）
L2 (Cross):  跨天数据 → 用户画像（需要多天数据积累才能做的分析）
```

### 2.2 各层数据流

#### L0: Step Analysis（每步触发）

```
输入（来自 record_step payload）:
  ├─ step_name:      "修复导入路径错误"
  ├─ step_type:      "debug"
  ├─ content:        "修改了server.py第42行的相对导入..."（AI做了什么）
  ├─ ai_reasoning:   "一开始以为是缺少__init__.py..."（AI怎么想的）
  ├─ commands_executed: "grep -n 'from \\.' server.py..."
  ├─ symptom:        "启动时报ImportError..."
  ├─ root_cause:     "直接运行脚本时相对导入找不到父包"
  └─ solution:       "改为绝对导入，兼容直接运行和模块导入"

Prompt 核心任务（知识提纯，不做推理）:
  1. 提取可独立理解的知识点（脱离上下文仍有价值）
  2. 标注技能领域（7 标准领域）
  3. 记录命令及坑点
  4. 评估复杂度

输出:
  ├─ knowledge_points: [{title, desc, domain, tags, difficulty}]
  ├─ skill_domains:    ["Python"]
  ├─ commands_used:    [{command, purpose, key_flags, gotcha}]
  ├─ difficulty:       "easy"/"medium"/"hard"
  └─ complexity_level: "simple"/"medium"/"complex"

存入:
  ├─ conversation_steps.output_data（原始分析结果）
  └─ knowledge_points 表（每个知识点一条记录）

注意：
  - ❌ 不再输出 problem_solving_pattern（交给 L1）
  - ❌ 不再输出 key_insights（交给 L1）
  - ❌ 不再输出 improvement_suggestions（交给 L1/L2）
  - ❌ 不再输出 thinking_patterns（交给 L1）
```

#### L1: Conversation Finalize（对话结束时触发一次）

```
输入（从 SQLite 聚合）:
  ├─ 会话元数据:
  │   ├─ topic:            "修复server.py的3个Bug"
  │   ├─ system_id:        "devPartner"
  │   ├─ client:           "codebuddy"
  │   ├─ task_type:        "debug"
  │   ├─ user_raw_input:   "server.py 有3个bug..."（用户原文）
  │   ├─ ai_analysis:      "用户反馈server.py有3个bug..."（AI初始分析）
  │   └─ ai_summary:       "本次对话修复了server.py的3个启动bug..."（AI最终复盘）
  │
  ├─ 步骤详情（从 conversation_steps 读取）:
  │   ├─ step_1: {step_name, step_type, content, ai_reasoning, commands_executed,
  │   │           symptom, root_cause, solution}
  │   ├─ step_2: {同上}
  │   └─ step_3: {同上}
  │
  └─ L0 分析结果（从 conversation_steps.output_data 读取）:
      └─ 每个 step 的 knowledge_points, skill_domains, difficulty

Prompt 核心任务（推理和模式识别，需要完整对话上下文）:
  1. 解题模式识别 — 从多步操作中识别整体解题思路
  2. 技术决策链分析 — 为什么选这个方案而不是那个
  3. 知识图谱构建 — 跨步骤的知识关联
  4. 关键洞察 — 可迁移到其他场景的规律性认识
  5. 改进建议 — 面向用户技能提升

输出:
  ├─ problem_solving_pattern:
  │   ├─ overall_approach:    "先定位导入错误→再修复空指针→最后调整超时"
  │   ├─ key_decisions:       [{decision, reason, tradeoff, alternatives}]
  │   ├─ dead_ends:           ["曾考虑改启动方式，但影响面太大"]
  │   └─ pattern_type:        "系统排查型" / "快速修复型" / "重构优化型"
  │
  ├─ knowledge_graph:
  │   └─ [{title, content, domain, tags, importance, type, related_kp_ids}]
  │
  ├─ key_insights:            ["当遇到ImportError时，先检查运行方式再改导入路径"]
  ├─ improvement_suggestions: ["建议学习Python包管理机制，区分模块导入和脚本运行"]
  ├─ conversation_quality:    {completeness, complexity, risk_areas}
  │
  └─ aggregate_skill_domains: ["Python"]  （从 L0 结果聚合，不重新推断）

存入:
  ├─ improvement_log（解题模式、关键洞察、改进建议）
  ├─ knowledge_points（知识图谱）
  └─ system_context_fragments（系统认知）

注意：
  - ❌ 不再输出 user_profile（交给 L2）
  - ❌ 不再输出 business_knowledge（移到独立的知识提取流程）
```

#### L2: User Profile Analysis（日报/周报/月报时触发）

```
输入（跨多天数据）:
  ├─ 当天/本周/本月所有对话的 L1 分析结果
  ├─ 当前全局用户画像快照（user_skills 表）
  ├─ 行为信号历史（behavior_signals 表）
  └─ 对话统计（对话数、步骤数、任务类型分布、bug修复数）

Prompt 核心任务（需要大量跨天数据）:
  1. 技能等级评估 — 对比历史，判断趋势
  2. 行为模式分析 — 沟通风格、决策模式、学习风格
  3. 情绪状态推断 — 需要多天数据判断常态
  4. 成长方向建议 — 基于技能缺口和历史表现
  5. 心理画像 — 性格倾向、压力反应、学习风格

输出（存入 user_skills + growth_analysis 表）:
  ├─ skills_observed:        ["Python", "调试"]
  ├─ skills_with_domains:    [{skill_name, skill_domain, level, trend}]
  ├─ behavior_notes:         "偏好先自己排查再求助..."
  ├─ communication_style:    "详细型"
  ├─ decision_pattern:       "数据驱动"
  ├─ emotional_state:        "专注"
  ├─ psychological_notes:    "展现系统性排查思维..."
  ├─ areas_for_growth:       ["并发编程"]
  ├─ learning_progress:      {current_level, target_level, gap_analysis}
  └─ growth_suggestions:     ["建议学习 asyncio..."]

注意：
  - ✅ 这才是用户画像该做的事
  - ✅ 需要跨多天数据
  - ✅ 需要与历史画像对比
```

---

## 三、prompt 重构清单

### 3.1 step.py — 精简为纯知识提纯

当前问题：输出了 problem_solving_pattern、key_insights、improvement_suggestions、thinking_patterns——这些都是 L1 的事。

改进方向：
- 只保留 knowledge_points + skill_domains + commands_used + difficulty
- 去掉 problem_solving_pattern、key_insights、improvement_suggestions、thinking_patterns、related_tools
- 强化"知识点可独立理解"的要求

### 3.2 deep_analysis.py — 强化为解题模式+技术决策

当前问题：
- 输入中 steps_summary 只有空壳（name/type/status），丢失了 content/ai_reasoning
- user_traits 永远为空（从 steps grep 不到）
- key_decisions 硬编码为空数组
- 输出了 user_profile（应该交给 L2）
- 输出了 business_knowledge（应该独立流程）

改进方向：
- 输入改为包含每个 step 的完整 content + ai_reasoning + commands_executed + L0结果
- 去掉 user_profile 输出（交给 L2）
- 去掉 business_knowledge 输出（独立知识提取）
- 核心聚焦：解题模式 + 技术决策链 + 关键洞察 + 改进建议
- 新增 conversation_quality 评估

### 3.3 user_profile.py — 保留但改为日报触发

当前问题：单次对话触发用户画像分析，数据量不足。

改进方向：
- 只在日报/周报/月报时触发（已有 daily_profile_merge）
- 输入改为跨天聚合数据
- 输出聚焦 9 维用户画像

---

## 四、数据传递修正

### 4.1 conversation_engine.py 修改点

**handle_step_analysis (L0)**:
- payload 不变（已经包含了所有字段）
- 去掉 user_requirement 的传递（prompt 不需要）
- LLM 输出精简

**handle_conversation_finalize (L1)**:
- **关键修正**：steps_summary 不再只传 name/type/status，改为传完整 step 数据
- 从 conversation_steps 读取 input_data（content + ai_reasoning）+ output_data（L0 结果）
- 去掉 user_traits 的 grep（本来就没有）
- 去掉 key_decisions（让 LLM 自己从步骤中推断）
- 去掉 business_knowledge 和 user_profile 的入库逻辑
- 新增：将 L1 的解题模式存入 improvement_log

### 4.2 llm_engine.py 修改点

**analyze_step_content**:
- 去掉 user_requirement 参数（L0 不需要）
- 调用精简后的 TASK_STEP_ANALYSIS

**analyze_conversation_deep**:
- steps_summary 参数类型从 list[dict] 改为完整步骤数据
- 去掉 user_traits 参数（L1 不分析用户画像）
- 调用重构后的 TASK_CONVERSATION_DEEP_ANALYSIS

---

## 五、实施优先级

| 优先级 | 改动 | 影响范围 | 风险 |
|--------|------|---------|------|
| **P0** | 修正 handle_conversation_finalize 的 steps_summary 数据（从空壳改为完整数据） | conversation_engine.py | 低 — 只改数据读取 |
| **P0** | 修正 key_decisions 硬编码空数组 | conversation_engine.py | 低 — 一行改动 |
| **P1** | 重构 step.py prompt（去掉 L1 职责） | prompts/step.py | 中 — prompt 改动需测试 |
| **P1** | 重构 deep_analysis.py prompt（去掉 L2 职责，强化 L1） | prompts/deep_analysis.py | 中 — prompt 改动需测试 |
| **P2** | 将 user_profile 分析移到日报/周报触发 | conversation_engine.py + daily_engine.py | 高 — 架构改动 |
| **P2** | 独立 business_knowledge 提取流程 | 新建文件 | 中 — 新功能 |
| **P3** | 用户画像 L2 跨天聚合分析 | user_profile.py + daily_engine.py | 高 — 需要多天数据 |

---

## 六、用户确认点

请确认以下设计决策：

1. **L0 只做知识提纯**（知识点 + 技能领域 + 命令记录），不做解题模式推理 — 同意？
2. **L1 做解题模式 + 技术决策**，输入需要包含每个 step 的完整 content + ai_reasoning — 同意？
3. **L2 用户画像只在日报/周报触发**，需要跨多天数据 — 同意？
4. **business_knowledge 从 deep_analysis 中移除**，改为独立的知识提取流程 — 同意？
5. **prompt 的 skill_domains 输出只由 L0 产生**，L1 做聚合不重新推断 — 同意？
