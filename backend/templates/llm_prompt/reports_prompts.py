"""
长周期报告 prompt 定义 v9.10.1
==============================
周报 / 月报 / 年报 / 成长分析 四个 LLM 分析任务。

设计要点（针对"报告不够深入、难支撑决策"的优化）：
1. 结构化 JSON 输出，字段对齐 md_templates.py 渲染契约，避免渲染空白；
2. 新增 `facts` 区块：强制从输入提取 3-8 条**可量化事实**（带数字/比例），
   让报告"有数据支撑"，而不是散文；
3. 新增 `psychology` 区块：从 self_reflection / user_intent / 对话内容 /
   用户画像推断**心理与协作信号**（受挫点、心流、成长状态、沟通风格），
   这是"对话内容分析心理"的落点，且要求区分事实与推测、低置信标注；
4. 决策导向：关键成果写业务影响、风险与计划必须具体可执行；
5. 严禁编造：所有数字必须能在输入中找到依据。

feature_flag 对齐 foundation/config/config.yaml 的 enhance_* 开关；
成长分析无对应开关，feature_flag 留空（交由 run_analysis 内部的 LLM 可用性检查）。
"""

from backend.templates.llm_prompt._common import AnalysisTask, parse_json

# ══════════════════════════════════════════════════════════
# 周报
# ══════════════════════════════════════════════════════════

TASK_WEEKLY_REPORT = AnalysisTask(
    name="weekly_report",
    description="周报生成（v9.10.1 — 结构化 + 事实锚定 + 心理分析，对齐 weekly_report 模板）",
    prompt_template="""你是一个专业的开发者周报分析助手。基于以下本周（{period_start} ~ {period_end}）的日报聚合数据，生成**结构化、可决策**的周报。

## 本周日报聚合
{daily_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
生成完整 JSON。**所有数字必须来自上面的日报数据，禁止编造**。周报的核心价值是：这周做了什么、哪些有业务影响、风险在哪、下周怎么走、用户的心理状态如何。

```json
{{
  "summary": "一句话周总结（100字内，含本周最关键进展）",
  "key_achievements": [
    {{"achievement": "关键成果描述（含具体对象）", "impact": "业务影响/价值（量化优先，如'接口耗时从 3s 降到 0.8s'）"}}
  ],
  "skill_progress": {{
    "new_skills_acquired": ["本周新掌握的具体技能"],
    "skills_improved": ["有提升的技能及提升点"],
    "skills_to_learn": ["下周计划学习的技能"]
  }},
  "risk_assessment": {{
    "technical_risks": ["技术风险（含现象与影响范围）"],
    "knowledge_gaps": ["知识盲区（含已暴露的场景）"],
    "process_issues": ["流程/协作问题（含频率）"]
  }},
  "next_week_plan": {{
    "priorities": ["下周最优先的 1-3 件事（具体可验收）"],
    "learning_goals": ["学习目标"],
    "experiments": ["想验证的假设/实验"]
  }},
  "metrics": {{
    "productivity_trend": "生产力趋势描述（上升/平稳/下降，并说明依据）",
    "learning_velocity": "学习速度描述",
    "code_quality_trend": "代码质量趋势描述",
    "overall_score": 8
  }},
  "facts": [
    "可量化事实1（必须带数字，如'本周 12 次对话，debug 类 7 次占 58%'）",
    "可量化事实2（如'完成 3 个模块的单元测试覆盖，覆盖率从 40% 升至 72%'）",
    "可量化事实3（来自 self_reflection 的复盘率、意图清晰度等）"
  ],
  "psychology": {{
    "emotional_state_trend": "本周情绪/状态走向（如'前期受挫、后期顺畅'），区分观察与推测",
    "recurring_friction": ["重复出现的卡点（来自 self_reflection 的'暴露/问题/错误'信号）"],
    "growth_mindset": "成长型思维表现（如'主动深挖根因、先全量扫描再定位'）",
    "communication_pattern": "沟通/协作偏好（来自用户画像或对话，如'偏好详细型逐步推理'）"
  }}
}}
```

注意：
1. facts 必须能在日报原文中找到依据，每条带具体数字；facts 是报告可信度的锚点
2. psychology 是基于对话内容与画像的**推断**，区分"事实信号"与"推测"，置信低时明确写"推测"
3. key_achievements 的 impact 尽量量化；risk_assessment 的每条要可行动
4. overall_score 为 0-10 整数，反映本周综合产出质量
5. 只输出 JSON，不要额外说明""",
    parser=parse_json,
    max_tokens=8192,
    input_truncate=32768,
    feature_flag="enhance_weekly_report",
)


# ══════════════════════════════════════════════════════════
# 月报
# ══════════════════════════════════════════════════════════

TASK_MONTHLY_REPORT = AnalysisTask(
    name="monthly_report",
    description="月报生成（v9.10.1 — 结构化 + 事实锚定 + 心理分析，对齐 monthly_report 模板）",
    prompt_template="""你是一个专业的开发者月报分析助手。基于以下本月（{period_start} ~ {period_end}）的周报聚合数据，生成**结构化、可决策**的月报，并做与上月的结构化对比。

## 本月周报聚合
{weekly_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
生成完整 JSON。**所有数字必须来自上面的周报数据，禁止编造**。月报要体现"一个月的积累与成长"，重点在趋势、沉淀、风险债务。

```json
{{
  "summary": "一句话月度总结（100字内，含本月最关键产出与转折）",
  "major_achievements": [
    {{"achievement": "重大成果描述（含具体对象与规模）", "impact": "业务影响/价值（量化优先）"}}
  ],
  "skill_evolution": {{
    "skills_at_start": ["月初已具备的技能"],
    "skills_at_end": ["月末具备的技能"],
    "growth_highlights": ["本月技能成长亮点（含具体场景）"]
  }},
  "risk_and_debt": {{
    "critical_risks": ["当前关键风险（含触发条件）"],
    "tech_debt_accumulated": ["本月积累的技术债务（含影响范围）"],
    "knowledge_debt": ["知识欠债（含已暴露的盲区）"]
  }},
  "next_month_plan": {{
    "strategic_goals": ["下月战略目标（1-2 条，可衡量）"],
    "tactical_actions": ["具体行动项"],
    "learning_roadmap": ["学习路线"]
  }},
  "metrics": {{
    "overall_productivity": 8,
    "skill_growth_rate": "技能增长率描述（如'较上月 +2 个新领域'）",
    "project_health": "项目健康度描述（上升/平稳/下降 + 依据）",
    "work_life_balance": "工作生活平衡描述"
  }},
  "facts": [
    "可量化事实1（如'本月 4 篇周报，累计完成 23 次对话'）",
    "可量化事实2（如'技术债务新增 5 条，已清理 2 条，净增 3 条'）",
    "可量化事实3（来自画像快照的成长信号，如'debug 维度 trend=rising'）"
  ],
  "psychology": {{
    "emotional_state_trend": "本月情绪/状态走向（区分观察与推测）",
    "recurring_friction": ["本月反复出现的卡点模式"],
    "growth_mindset": "本月成长型思维的综合表现",
    "communication_pattern": "沟通/协作偏好演进"
  }}
}}
```

注意：
1. facts 必须能在周报原文中找到依据，每条带具体数字
2. 与上月对比时，若有上月数据线索请在 facts/metrics 中显式标注环比方向
3. psychology 是推断，区分"事实信号"与"推测"，置信低时标注"推测"
4. overall_productivity 为 0-10 整数
5. 只输出 JSON，不要额外说明""",
    parser=parse_json,
    max_tokens=8192,
    input_truncate=32768,
    feature_flag="enhance_monthly_report",
)


# ══════════════════════════════════════════════════════════
# 年报
# ══════════════════════════════════════════════════════════

TASK_ANNUAL_REPORT = AnalysisTask(
    name="annual_report",
    description="年报生成（v9.10.1 — 结构化 + 事实锚定 + 心理分析，对齐 annual_report 模板）",
    prompt_template="""你是一个专业的开发者年报分析助手。基于以下本年（{period_start} ~ {period_end}）的月报聚合数据，生成**结构化、有纵深**的年报，回答"这一年怎么过来的、成长在哪、明年去哪"。

## 本年 月报聚合
{monthly_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
生成完整 JSON。**所有数字必须来自上面的月报数据，禁止编造**。年报是复盘与展望，重长期趋势、能力跃迁、决策成熟度。

```json
{{
  "summary": "一句话年度总结（150字内，含全年主线与最大跃迁）",
  "year_in_review": {{
    "defining_moments": ["定义性时刻（改变工作方式的节点）"],
    "biggest_achievements": ["最大成就（含规模/影响）"],
    "hardest_challenges": ["最困难挑战（含如何突破）"],
    "unexpected_discoveries": ["意外发现（技术/业务/自我）"]
  }},
  "skill_journey": {{
    "skills_at_year_start": ["年初技能状态"],
    "skills_at_year_end": ["年末技能状态"],
    "breakthrough_skills": ["突破性提升的技能（含拐点）"],
    "abandoned_skills": ["搁置/放弃的方向（含原因）"]
  }},
  "growth_analysis": {{
    "learning_curve": "学习曲线描述（加速/平台期/拐点）",
    "productivity_evolution": "生产力演变（季度对比）",
    "decision_making_maturity": "决策成熟度演进",
    "communication_style_evolution": "沟通风格演变"
  }},
  "next_year_vision": {{
    "strategic_direction": "战略方向（1-2 句）",
    "skill_goals": ["技能目标"],
    "project_ambitions": ["项目愿景"],
    "learning_commitments": ["学习承诺"]
  }},
  "metrics": {{
    "overall_growth_score": 8,
    "technical_depth": "技术深度描述",
    "breadth_of_knowledge": "知识广度描述",
    "impact_level": "影响力描述",
    "sustainability": "可持续性描述"
  }},
  "facts": [
    "可量化事实1（如'全年 12 篇月报，累计 260+ 次对话'）",
    "可量化事实2（如'技能树从 7 个领域扩展到 15 个'）",
    "可量化事实3（来自画像快照的长期趋势，如'debug/refactoring 维度全年 rising'）"
  ],
  "psychology": {{
    "emotional_state_trend": "全年心理状态走向（区分观察与推测）",
    "recurring_friction": ["全年反复出现的底层卡点模式"],
    "growth_mindset": "全年成长型思维的综合画像",
    "communication_pattern": "沟通/协作风格的长期演进"
  }}
}}
```

注意：
1. facts 必须能在月报原文中找到依据，每条带具体数字
2. psychology 是基于全年数据的推断，区分"事实信号"与"推测"，置信低时标注"推测"
3. overall_growth_score 为 0-10 整数，衡量全年综合成长
4. 只输出 JSON，不要额外说明""",
    parser=parse_json,
    max_tokens=8192,
    input_truncate=32768,
    feature_flag="enhance_annual_report",
)


# ══════════════════════════════════════════════════════════
# 成长分析（双维度：系统 + 用户）— 月报生成后触发
# ══════════════════════════════════════════════════════════

TASK_GROWTH_ANALYSIS = AnalysisTask(
    name="growth_analysis",
    description="成长分析（v9.10.1 — 系统+用户双维度，输出 system_analyses/user_analyses 供 growth_analysis 表入库）",
    prompt_template="""你是一个软件工程成长教练。基于以下本月周报聚合、用户画像与项目画像，产出**系统优化**与**用户成长**双维度的可落地建议。

## 本月周报聚合
{weekly_summaries}

## 当前用户画像快照
{user_profile_snapshot}

## 当前项目画像快照
{project_profile_snapshot}

## 输出要求
生成完整 JSON，含 system_analyses（工程/系统层面可改进项）与 user_analyses（用户能力成长项）。
每条建议必须**具体、可验收、带预期效果**，禁止空泛。

```json
{{
  "system_analyses": [
    {{
      "analysis_type": "system",
      "title": "建议标题（具体）",
      "description": "问题/机会描述（含依据）",
      "suggestion": "具体改进动作（可验收）",
      "related_data": {{
        "related_skills": ["相关技能"],
        "trend_keywords": ["趋势关键词"],
        "expected_effect": "预期效果（量化优先）"
      }},
      "priority": "high"
    }}
  ],
  "user_analyses": [
    {{
      "analysis_type": "user",
      "title": "成长建议标题（具体）",
      "description": "现状与差距描述",
      "suggestion": "具体成长动作（可验收）",
      "related_data": {{
        "related_skills": ["相关技能"],
        "trend_keywords": ["趋势关键词"],
        "expected_effect": "预期成长效果"
      }},
      "priority": "medium"
    }}
  ],
  "summary": {{
    "system_summary": "系统层面本月核心结论（1-2 句）",
    "user_summary": "用户成长层面本月核心结论（1-2 句）"
  }}
}}
```

注意：
1. system_analyses 聚焦工程效率/质量/架构可改进项；user_analyses 聚焦用户能力短板与成长路径
2. priority 取值 high/medium/low；建议需可落地，避免"多学习"这类空话
3. 所有内容基于输入数据，禁止编造；只输出 JSON""",
    parser=parse_json,
    max_tokens=3000,
    input_truncate=32768,
    feature_flag="",
)
