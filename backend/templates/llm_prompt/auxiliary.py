"""
辅助 Prompt 定义 — 从业务代码中提取的零散 LLM prompt
=====================================================

v9.8.4: 从 llm_engine.py 和 conversation_engine.py 中提取，
       所有 prompt 模板统一由 prompts/ 目录管理。
"""

from backend.templates.llm_prompt._common import AnalysisTask, parse_json

# ══════════════════════════════════════════════════════════
# A1: review_project_description — 来自 llm_engine.py L766-783
# ══════════════════════════════════════════════════════════

TASK_REVIEW_PROJECT_DESC = AnalysisTask(
    name="review_project_description",
    description="评审项目描述是否需要优化",
    prompt_template="""你是一个项目描述维护助手。请根据本次对话内容，判断是否需要更新项目的简要描述。

当前项目描述：{current_description}

本次对话主题：{topic}

本次对话摘要：{summary}

AI 复盘总结：{ai_summary}

请分析：
1. 当前项目描述是否已经**全面、简洁、精准**地概括了项目的主要作用？
2. 本次对话是否揭示了新的项目信息（功能模块、技术架构、业务领域等），需要补充到描述中？
3. 如果当前描述已经很好，不需要修改，就返回 need_update: false

要求：
- 项目描述应控制在 1-3 句话，全面但精炼
- 只输出 JSON，不要任何解释

输出格式：
{{"need_update": true, "new_description": "优化后的项目描述（中文，1-3句话，全面精炼）"}}
或
{{"need_update": false, "new_description": ""}}""",
    parser=parse_json,
    max_tokens=256,
    input_truncate=4000,
    feature_flag="enhance_analysis",
)

# ══════════════════════════════════════════════════════════
# A2: user_traits_enrich — 来自 llm_engine.py L1053-1067
# ══════════════════════════════════════════════════════════

TASK_USER_TRAITS_ENRICH = AnalysisTask(
    name="user_traits_enrich",
    description="用户特征智能拆分和丰富",
    prompt_template="""请处理以下用户特征数据，进行智能拆分和丰富：

原始特征数据：
```json
{traits_json}
```

请输出处理后的 JSON，在原始结构基础上补充以下字段：
- skill_level: 用户综合技能等级（beginner/intermediate/advanced/expert）
- related_skills: 与已观察技能相关的子技能列表
- evidence_text: 自然语言证据描述
- estimated_hours: 估算该技能已投入的学习时间（小时）
- growth_trend: 成长趋势（growing/stable/declining）

只输出 JSON。""",
    parser=parse_json,
    max_tokens=1024,
    input_truncate=4000,
)

# ══════════════════════════════════════════════════════════
# B1: question_expand — 来自 conversation_engine.py L617-624
# ══════════════════════════════════════════════════════════

TASK_QUESTION_EXPAND = AnalysisTask(
    name="question_expand",
    description="技术问题同义扩展查询",
    prompt_template="""将以下技术问题改写为3个同义扩展查询词。

问题：{question}

请输出 JSON 格式：
```json
{{"queries": ["扩展词1", "扩展词2", "扩展词3"]}}
```
只输出 JSON。""",
    parser=parse_json,
    max_tokens=256,
    input_truncate=1000,
)
