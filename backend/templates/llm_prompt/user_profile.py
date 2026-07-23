from backend.templates.llm_prompt._common import AnalysisTask, parse_json

# ── 精简参考卡（v9.11 优化：原 4 个静态块压缩为 1 个，节省 ~60% prompt token）──
# 将归类规则和输出约束内联到 prompt_template 中，不再作为 kwargs 传入，
# 避免每次调用都需要传递常量数据。

_COMPACT_PROFILE_REF = """## 归类规则与输出约束
skill_domain 必须从7个标准领域中选择：Python | 前端 | AI/LLM | DevOps | 数据库 | 架构设计 | 通用工程
skills_with_domains 格式: [{{"skill_name":"具体技能名","skill_domain":"标准领域名"}}]
必填: skills_with_domains, behavior_notes
confidence 范围 0.0-1.0，基于具体对话证据标注(high/medium/low)
所有字段必须填写，不确定的填合理默认值
区分"已知能力"和"正在学习"
示例: skills_with_domains=[{{"skill_name":"Django ORM","skill_domain":"Python"}}，{{"skill_name":"SQL优化","skill_domain":"数据库"}}]
behavior_notes: 概括学习习惯、问题解决方式、沟通特点
learning_progress: {{current_level, target_level, gap_analysis}}
communication_style: 直接|委婉|详细|简洁
decision_pattern: 数据驱动|直觉|谨慎|大胆
emotional_state: 专注|焦虑|兴奋|疲惫|平静"""


def _parse_user_profile(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_user_profile"
        from datetime import datetime

        parsed["generated_at"] = datetime.now().isoformat()
    return parsed


TASK_USER_PROFILE_ANALYSIS = AnalysisTask(
    name="user_profile_analysis",
    description="用户画像分析（技能/行为/兴趣/成长方向）",
    prompt_template="""根据以下信息分析用户画像。

"""
    + _COMPACT_PROFILE_REF
    + """

## 待分析数据
分析范围: {analysis_scope}
客户端上下文: {client_context}

最近对话数据:
{recent_data}

## 输出要求（严格 JSON）
只输出 JSON，不要包含任何其他文字：

```json
{{
  "skills_observed": ["已掌握的技术技能"],
  "skills_with_domains": [
    {{
      "skill_name": "具体技能名称",
      "skill_domain": "标准领域名（必须从7个领域中选择）"
    }}
  ],
  "behavior_notes": "学习习惯、问题解决方式、沟通特点",
  "tech_interests": ["感兴趣的技术方向"],
  "areas_for_growth": ["需要提升的领域"],
  "mistakes": ["常见错误模式"],
  "strengths": ["明显优势"],
  "communication_style": "直接 | 委婉 | 详细 | 简洁",
  "decision_pattern": "数据驱动 | 直觉 | 谨慎 | 大胆",
  "emotional_state": "专注 | 焦虑 | 兴奋 | 疲惫 | 平静",
  "learning_progress": {{
    "current_level": "当前水平描述",
    "target_level": "目标水平描述",
    "gap_analysis": "差距分析"
  }},
  "confidence": 0.85
}}
```

注意：
1. 只输出 JSON，不要添加任何解释性文字
2. 基于具体对话证据，避免主观臆断
3. skill_domain 必须从7个标准领域中选择，不要自创""",
    parser=_parse_user_profile,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)
