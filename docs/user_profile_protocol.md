# 客户端-MCP 双向画像数据传输协议 v4.3

> 本文档定义 CodeBuddy 客户端与 DevPartner MCP 之间的用户画像分析双向交互规范。

---

## 1. 协议概述

```
客户端                          MCP 服务端
  │                                │
  │──── ① 请求分析任务 ───────────→│ request_user_profile_analysis()
  │                                │
  │←─── 返回分析指令 + 维度 ───────│
  │                                │
  │  ② 客户端按规则执行分析          │
  │                                │
  │──── ③ 回传分析结果 ───────────→│ record_dialogue(user_traits=...)
  │                                │  record_conversation(user_traits=...)
  │                                │
  │                                │  ④ MCP 融合到多表：
  │                                │     user_skills / improvement_log /
  │                                │     user_skill_plan / conversations
  │                                │
  │←─── 确认结果 ──────────────────│
```

---

## 2. 工具调用规范

### 2.1 下行：MCP → 客户端（分析任务下发）

**工具**: `request_user_profile_analysis`

**参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `analysis_scope` | string | 否 | `full`(全9维) / `skills`(技能3维) / `behavior`(行为3维) / `quick`(快速2维) |
| `conversation_id` | string | 否 | 要分析的目标会话ID（不传则分析最近一次） |
| `project_id` | string | 否 | 项目标识，用于调整分析策略 |

**返回值关键字段**:
```json
{
  "analysis_request": {
    "scope": "full",
    "dimensions": ["skills_observed", "behavior_notes", ...],
    "user_traits_schema": { ... },
    "project_strategy": { "focus_dimensions": [...], "light_dimensions": [...] },
    "return_channel": "调用 record_dialogue 的 user_traits 参数回传"
  }
}
```

### 2.2 上行：客户端 → MCP（分析结果回传）

**通道 A**: `record_dialogue(user_traits=<JSON字符串>)`
- 适用场景：每次对话结束时的常规回传
- 写入目标：conversations + conversation_archive + user_skills + improvement_log + user_skill_plan

**通道 B**: `record_conversation(user_traits=<JSON字符串>)`
- 适用场景：对话存档时的附加回传
- 写入目标：同通道 A

---

## 3. user_traits 数据结构

### 3.1 完整格式（analysis_scope="full"）

```json
{
  "skills_observed": ["Python", "SQLite", "数据库设计"],
  "behavior_notes": "喜欢先理解全貌再动手",
  "mistakes": ["忘了更新关联表", "SQLite不支持ALTER TABLE ADD CONSTRAINT"],
  "strengths": ["问题定位快", "边界意识强"],
  "communication_style": "直接",
  "decision_pattern": "数据驱动",
  "tech_interests": ["AI/ML", "数据库设计"],
  "areas_for_growth": ["代码质量", "安全审计"],
  "emotional_state": "专注",
  "learning_progress": "对数据库设计范式理解加深"
}
```

### 3.2 字段说明

| 字段 | 类型 | 存储目标 | 描述 |
|------|------|----------|------|
| `skills_observed` | string[] | user_skills | 本次对话中展现的技术技能 |
| `behavior_notes` | string | improvement_log | 行为模式观察描述 |
| `mistakes` | string[] | improvement_log | 本次对话中的错误/教训 |
| `strengths` | string[] | improvement_log | 用户的强项/优势 |
| `communication_style` | string | improvement_log | 沟通风格（直接/委婉/详细/简洁） |
| `decision_pattern` | string | improvement_log | 决策模式（数据驱动/直觉/谨慎/大胆） |
| `tech_interests` | string[] | user_skill_plan | 技术兴趣方向 |
| `areas_for_growth` | string[] | user_skill_plan | 需要提升的领域 |
| `emotional_state` | string | improvement_log | 情绪状态（专注/焦虑/兴奋/疲惫） |
| `learning_progress` | string | improvement_log | 学习进度观察 |

---

## 4. 项目级策略适配

MCP 根据 `project_id` 关键词自动选择分析策略：

| project_id 关键词 | 策略类型 | 加重维度 | 减轻维度 |
|-------------------|----------|----------|----------|
| database / db | 数据库类 | skills_observed, mistakes | tech_interests, emotional_state |
| ui / frontend / react | 前端类 | skills_observed, behavior_notes | areas_for_growth |
| ai / ml / model | AI/ML类 | tech_interests, skills_observed | communication_style, decision_pattern |
| infra / ops / devops | 基础设施类 | areas_for_growth, decision_pattern | emotional_state |
| 无匹配 | 通用策略 | 无 | 无 |

---

## 5. 数据校验

### 5.1 客户端侧（回传前）

- `user_traits` 必须是合法的 JSON 字符串
- `skills_observed`/`mistakes`/`strengths`/`tech_interests`/`areas_for_growth` 必须是数组
- `communication_style` 必须是 `直接`/`委婉`/`详细`/`简洁` 之一
- `decision_pattern` 必须是 `数据驱动`/`直觉`/`谨慎`/`大胆` 之一

### 5.2 MCP 侧（入库后）

通过 `check_data_integrity()` 工具执行：
- `conversations.topic` / `task_type` / `skill_domains` / `feedback_type` 非空检查
- 子表 FK 关联有效性检查
- 写入成功率统计（record_dialogue / record_conversation / save_self_iterate）

---

## 6. 版本兼容

| 协议版本 | MCP 版本 | 变更 |
|----------|----------|------|
| v1.0 | v4.2.0 | 初始双向协议，9维分析框架 |
| v1.1 | v4.3.0 | 新增 project_strategy 项目级策略适配；conversations.analyzed 标记；FK 约束强制 |
