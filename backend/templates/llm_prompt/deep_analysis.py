"""
对话终结深度分析 Prompts (v9.8.0)
=================================

拆分策略：原来一个四维大 Prompt 拆为两个独立 Prompt，每个聚焦单一维度
  1. business_tech_assessment — 业务知识 + 技术决策 + 整体评估
  2. user_profile_analysis     — 用户画像分析（9维特征）

设计理由：
  - 每个 Prompt 更短、更聚焦 → LLM 分析精度更高
  - 独立 num_predict 配置 → 避免单次 JSON 被截断
  - 模块解耦 → 任一维度失败不影响其他维度
"""

from backend.templates.llm_prompt._common import AnalysisTask, parse_json

# ═══════════════════════════════════════════════════════════
# 公共 Prompt 头部（三个模块共享的元数据部分）
# ═══════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════
# v9.8.1: 按模块拆分 HEADER，每个模块只包含所需数据
# ═══════════════════════════════════════════════════════════

# 模块一用：业务知识 + 技术决策 + 整体评估
_BUSINESS_TECH_HEADER = """## 对话元数据
主题: {topic}
系统: {system_id}

## 项目上下文
{project_context}

## 用户原始输入
{user_raw_input}

## 对话摘要
{summary}

## 关键决策
{key_decisions}

## AI 意图分析
{ai_analysis}"""

# 模块二用：用户画像分析
_USER_PROFILE_HEADER = """## 用户原始输入
{user_raw_input}

## AI 意图分析
{ai_analysis}"""

# ═══════════════════════════════════════════════════════════
# 模块一：业务知识 + 技术决策 + 整体评估
# ═══════════════════════════════════════════════════════════


def _parse_business_tech(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_business_tech_v9.8"
        from datetime import datetime

        parsed["generated_at"] = datetime.now().isoformat()
    return parsed


TASK_BUSINESS_TECH_ASSESSMENT = AnalysisTask(
    name="business_tech_assessment",
    description="业务知识提取 + 技术决策链 + 整体评估",
    prompt_template="""你是一个技术架构分析师。请对以下已完成的对话进行业务知识和技术决策分析。

"""
    + _BUSINESS_TECH_HEADER
    + """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 输出要求（严格 JSON）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```json
{{
  "business_knowledge": {{
    "connected_systems": [
      {{
        "system_name": "系统名称",
        "modules": [
          {{
            "module_name": "模块名称",
            "functions": ["功能列表"],
            "data_flow": "数据流转描述",
            "db_tables": [
              {{"table_name": "表名", "key_fields": ["关键字段"], "description": "表作用"}}
            ],
            "design_patterns": ["设计模式"],
            "process_steps": ["业务流程步骤"]
          }}
        ],
        "architecture": "系统架构",
        "tech_stack": ["技术栈"],
        "business_rules": ["业务规则"]
      }}
    ],
    "new_discoveries": ["新发现的业务知识"],
    "business_confidence": 0.7
  }},
  "technical_decisions": [
    {{
      "decision": "技术决策",
      "reason": "决策理由",
      "tradeoff": "权衡考量",
      "alternatives": ["替代方案"],
      "impact": "影响范围",
      "decision_type": "架构设计|技术选型|实现方案|重构决策"
    }}
  ],
  "overall_assessment": {{
    "conversation_quality": "优秀|良好|一般|较差",
    "completeness": 85,
    "complexity": "simple|moderate|complex",
    "notable_patterns": ["值得注意的模式"],
    "risk_areas": ["风险领域"]
  }}
}}
```

分析要点：
1. 业务知识：从对话中提取系统、模块、功能、数据流、DB表、设计模式、业务流程
2. 技术决策：记录方案选型和架构决策，关注 why 而不只是 what
3. 整体评估：对话质量、完成度、复杂度、风险

注意：
- 只输出 JSON，不要添加任何解释
- 所有字段必须填写，不确定的填合理默认值
- confidence 范围 0.0-1.0，completeness 范围 0-100
- 基于具体对话证据，避免主观臆断""",
    parser=_parse_business_tech,
    max_tokens=4096,
    input_truncate=24000,
    feature_flag="enhance_analysis",
)


# ═══════════════════════════════════════════════════════════
# 模块二：用户画像分析
# ═══════════════════════════════════════════════════════════


def _parse_user_profile(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_user_profile_v9.8"
        from datetime import datetime

        parsed["generated_at"] = datetime.now().isoformat()
    return parsed


TASK_CONV_USER_PROFILE = AnalysisTask(
    name="conversation_user_profile",
    description="对话级用户画像深度分析（9维特征 + 心理观察）",
    prompt_template="""你是一个心理学分析师。请基于对话记录分析用户的认知模式和行为特征。

"""
    + _USER_PROFILE_HEADER
    + """

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 输出要求（严格 JSON）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

```json
{{
  "user_profile": {{
    "skills_observed": ["识别的技术技能"],
    "behavior_notes": "学习习惯、问题解决方式、沟通特点",
    "mistakes": ["暴露的错误或知识盲区"],
    "strengths": ["优势和能力"],
    "communication_style": "直接|委婉|详细|简洁",
    "decision_pattern": "数据驱动|直觉|谨慎|大胆",
    "tech_interests": ["关注的技术方向"],
    "areas_for_growth": ["需要提升的领域"],
    "emotional_state": "专注|焦虑|兴奋|疲惫|好奇",
    "psychological_notes": "性格倾向、思维模式、压力反应、学习风格",
    "learning_progress": "本次学习收获",
    "profile_confidence": 0.75
  }}
}}
```

分析要点：
1. 基于 user_raw_input（用户原话）分析沟通风格和情绪状态
2. 从对话过程中识别：解决问题的方式、遇到困难时的反应、学习吸收能力
3. psychological_notes 深入心理层面：性格倾向、认知偏好、压力应对模式
4. 不要只看表面技术能力，要挖掘行为背后的思维模式

注意：
- 只输出 JSON，不要添加任何解释
- 所有字段必须填写，不确定的填合理默认值
- confidence 范围 0.0-1.0
- 基于具体对话证据，避免主观臆断""",
    parser=_parse_user_profile,
    max_tokens=3072,
    input_truncate=24000,
    feature_flag="enhance_analysis",
)
