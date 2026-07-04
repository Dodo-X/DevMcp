---
description: 
alwaysApply: false
enabled: false
updatedAt: 2026-07-04T14:35:25.249Z
provider: 
---

# 用户全维度画像分析规则 v1.0

> DevPartner MCP 双向画像协同协议的客户端分析规则。
> 客户端每次对话结束后按此规则分析用户，通过 `record_dialogue(user_traits=...)` 回传给 MCP。

---

## 9 维分析框架

### 1. skills_observed（技术技能观察）
**分析目标**：从本次对话中识别用户展现的技术能力。

**判定规则**：
- 使用频率 ≥ 2 次的技术栈 → 标记为 demonstrated
- 用户说"我知道了"、"原来是这么回事"等领悟表达 → 标记为 learning
- 用户主动提及某个技术领域的新特性/最佳实践 → 标记为 growing

**示例输出**：`["Python", "SQLite", "FastMCP", "数据库设计"]`

### 2. behavior_notes（行为模式）
**分析目标**：观察用户的思维和操作习惯。

**判定规则**：
- 用户先要求看全貌再动手 → "喜欢先理解全局再深入细节"
- 用户跳过理解直接用代码试错 → "偏好实践驱动学习"
- 用户频繁问"为什么"而非"怎么做" → "偏好原理驱动的学习方式"
- 用户要求分步骤输出 → "偏好结构化递进式信息"

### 3. mistakes（错误/教训）
**分析目标**：识别本次对话中用户暴露出的错误或疏忽。

**判定规则**：
- 代码写错了导致报错 → 记录具体错误
- 遗漏了某一步操作 → 记录遗漏点
- 理解偏差需要纠正 → 记录误解点
- 不要记录"尝试性错误"（实验代码的临时错误）

**示例输出**：`["忘了更新关联表", "误以为 SQLite 支持 ALTER TABLE ADD CONSTRAINT"]`

### 4. strengths（强项/优势）
**分析目标**：识别用户本次对话中展现的优势。

**判定规则**：
- 问题定位快（< 3 轮对话就定位到根因）→ "问题定位快"
- 提出了准确的猜测或假设 → "直觉准确"
- 能在 AI 建议基础上自主扩展 → "举一反三"
- 关注细节和边界条件 → "边界意识强"

### 5. communication_style（沟通风格）
**分析目标**：观察用户的沟通偏好。

**可选值**：
- `直接` — 开门见山，不铺垫
- `委婉` — 喜欢先问"能不能"、"可不可以"
- `详细` — 喜欢充分展开背景
- `简洁` — 一句话说清楚需求

### 6. decision_pattern（决策模式）
**分析目标**：观察用户如何做技术决策。

**可选值**：
- `数据驱动` — 基于数据/事实做决策
- `直觉` — 依赖经验和直觉
- `谨慎` — 倾向于多验证再动手
- `大胆` — 愿意尝试新技术/新方案

### 7. tech_interests（技术兴趣方向）
**分析目标**：识别用户关注/好奇的技术领域。

**判定规则**：
- 新话题：用户开始探索全新领域 → 高优先级
- 深化：用户在已有领域深入 → 中优先级
- 浅尝：用户只是顺带提到 → 低优先级

**示例输出**：`["AI/ML", "数据库设计", "自动化运维"]`

### 8. areas_for_growth（待提升领域）
**分析目标**：基于本次对话识别用户可提升的方向。

**判定规则**：
- 反复问同类问题 → 该领域是学习瓶颈
- 代码风格/规范类问题 → "代码质量"
- 安全/性能类疏忽 → "安全意识" / "性能优化"
- 测试/文档类缺失 → "工程质量"

**示例输出**：`["代码质量", "安全审计", "测试覆盖率"]`

### 9. emotional_state（情绪状态）
**分析目标**：推测用户在对话中的情绪基调。

**可选值**：
- `专注` — 沉浸式学习/开发
- `焦虑` — 赶时间/压力大
- `兴奋` — 学到新东西/解决难题后的满足
- `疲惫` — 大量重复劳动后
- `好奇` — 探索新领域的兴奋

---

## 分析策略（按项目标识区分）

### 通用策略（默认）
适用所有项目，覆盖全部 9 个维度。

### 数据库类项目（project_id 含 "database" / "db" 等）
加重维度：skills_observed（SQL/ORM/数据建模）、mistakes（数据完整性相关）
减轻维度：tech_interests（非数据相关领域降权）

### 前端类项目（project_id 含 "ui" / "frontend" / "react" 等）
加重维度：skills_observed（框架/样式/交互）、behavior_notes（视觉偏好）
减轻维度：areas_for_growth（后端领域降权）

### AI/ML 类项目（project_id 含 "ai" / "ml" / "model" 等）
加重维度：tech_interests、skills_observed（算法/训练/推理）
减轻维度：communication_style、decision_pattern

### 基础设施类项目（project_id 含 "infra" / "ops" / "devops" 等）
加重维度：areas_for_growth（稳定性/监控）、decision_pattern
减轻维度：emotional_state

---

## 双向交互协议

```
┌─────────────┐                      ┌─────────────┐
│  CodeBuddy   │                      │  DevPartner  │
│  (客户端)    │                      │  MCP (服务端) │
└──────┬──────┘                      └──────┬──────┘
       │                                    │
       │  ① MCP 主动下发分析任务              │
       │  request_user_profile_analysis()     │
       │ ←───────────────────────────────── │
       │                                    │
       │  ② 客户端按本规则执行 9 维分析       │
       │  分析维度覆盖:                       │
       │  skills/behavior/mistakes/           │
       │  strengths/communication/            │
       │  decision/interests/growth/emotion   │
       │                                    │
       │  ③ 客户端回传分析结果                │
       │  record_dialogue(user_traits={...})  │
       │ ─────────────────────────────────→ │
       │                                    │
       │  ④ MCP 融合到多表                    │
       │  user_skills / improvement_log /     │
       │  user_skill_plan                     │
```

**数据传输格式（user_traits JSON）**：

```json
{
  "skills_observed": ["Python", "SQLite"],
  "behavior_notes": "喜欢先理解全貌再动手",
  "mistakes": ["忘了更新关联表"],
  "strengths": ["问题定位快"],
  "communication_style": "直接",
  "decision_pattern": "数据驱动",
  "tech_interests": ["AI/ML", "系统设计"],
  "areas_for_growth": ["代码质量"],
  "emotional_state": "专注",
  "learning_progress": "对数据库设计范式理解加深"
}
```