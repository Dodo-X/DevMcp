"""
对话终结深度分析 Prompt (v9.5)
==============================

四个核心分析维度：
  1. 业务知识提取 — 数据分析师视角（对接系统、模块、功能、数据流、DB表字段）
  2. 用户画像分析 — 心理学家视角（9维用户特征分析）
  3. 技术决策链分析 — 工程师视角（方案选型、架构决策、权衡）
  4. 知识图谱更新 — 知识管理视角（可复用知识点提取）

NOT: 系统优化建议已移至月总结定时任务 (scheduler.py → TASK_GROWTH_ANALYSIS)
"""

from prompts._common import AnalysisTask, parse_json

def _parse_deep_analysis(raw: str) -> dict:
    """对话终结分析专用解析器"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_conversation_deep_analysis_v9"
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
    return parsed

TASK_CONVERSATION_DEEP_ANALYSIS = AnalysisTask(
    name="conversation_deep_analysis",
    description="对话终结深度分析 v9.5（业务知识+用户画像+技术决策+知识图谱）",
    prompt_template="""你是一个专业的开发者对话深度分析 AI 助手。请对以下已完成的对话进行四维度深度分析。

## 对话元数据
主题: {topic}
系统: {system_id}
客户端: {client}

## 用户原始输入（用于用户画像分析 — 这是用户对AI说的话，站在心理学角度分析）
{user_raw_input}

## 对话摘要
{summary}

## AI 意图分析（v9.1 — AI 对用户需求的理解和解题思路规划）
{ai_analysis}

## AI 最终总结（v9.1 — AI 对整个对话的复盘反思）
{ai_summary}

## AI 自我反思
{self_reflection}

## 客户端提交的用户画像
{user_traits}

## 关键决策
{key_decisions}

## 步骤摘要
{steps_summary}

## 项目上下文（对接系统业务描述）
{project_context}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
## 输出要求（严格 JSON 格式）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

请从以下四个维度进行深度分析，输出完整 JSON：

```json
{{
  "business_knowledge": {{
    "connected_systems": [
      {{
        "system_name": "对接的系统名称（如：结算系统）",
        "modules": [
          {{
            "module_name": "模块名称（如：收款模块）",
            "functions": ["模块下的功能列表"],
            "data_flow": "数据流转描述（从哪个入口→经过什么处理→输出什么）",
            "db_tables": [
              {{
                "table_name": "涉及的数据库表名",
                "key_fields": ["关键字段"],
                "description": "表的作用说明"
              }}
            ],
            "design_patterns": ["使用的设计模式"],
            "process_steps": ["业务流程步骤"]
          }}
        ],
        "architecture": "系统架构描述",
        "tech_stack": ["使用的技术栈"],
        "business_rules": ["业务规则"]
      }}
    ],
    "new_discoveries": ["本次对话新发现的业务知识"],
    "business_confidence": 0.7
  }},

  "user_profile": {{
    "skills_observed": ["从对话中识别的技术技能"],
    "behavior_notes": "学习习惯、问题解决方式、沟通特点的心理学观察",
    "mistakes": ["对话中暴露的错误或知识盲区"],
    "strengths": ["用户展现的优势和能力"],
    "communication_style": "直接|委婉|详细|简洁",
    "decision_pattern": "数据驱动|直觉|谨慎|大胆",
    "tech_interests": ["用户关注的技术方向"],
    "areas_for_growth": ["用户需要提升的领域"],
    "emotional_state": "专注|焦虑|兴奋|疲惫|好奇",
    "psychological_notes": "站在心理学角度的综合观察：用户的性格倾向、思维模式、压力反应、学习风格等",
    "learning_progress": "本次对话中的学习收获总结",
    "profile_confidence": 0.75
  }},

  "technical_decisions": [
    {{
      "decision": "技术决策描述",
      "reason": "决策理由",
      "tradeoff": "权衡考量（为什么选A不选B）",
      "alternatives": ["考虑过的替代方案"],
      "impact": "影响范围",
      "decision_type": "架构设计|技术选型|实现方案|重构决策"
    }}
  ],

  "knowledge_graph": [
    {{
      "title": "知识点标题",
      "content": "知识点详细描述（含具体代码/配置/命令）",
      "domain": "技术领域（Python/前端/数据库/DevOps/AI-ML/系统设计）",
      "tags": ["标签列表"],
      "importance": "high|medium|low",
      "reusable": true,
      "type": "skill|business|insight|solution"
    }}
  ],

  "overall_assessment": {{
    "conversation_quality": "对话质量评估（优秀/良好/一般/较差）",
    "completeness": "任务完成度（0-100）",
    "complexity": "整体复杂度（simple/moderate/complex）",
    "notable_patterns": ["值得注意的模式"],
    "risk_areas": ["识别的风险领域"]
  }}
}}
```

分析要点：
1. **业务知识**：从对话中提取对接系统的业务信息。你是一个数据分析师，关注：系统有什么模块？模块做什么？需要什么数据？涉及什么表和字段？运行流程是什么？设计模式是什么？
2. **用户画像**：站在心理学家的角度分析用户。基于用户原始输入（user_raw_input — 用户对AI说的原话）和对话过程，分析用户的性格、思维模式、情绪状态、沟通风格、决策偏好。不要只看表面技术能力，要深入心理层面。
3. **技术决策**：记录关键方案选型和架构决策，以及背后的权衡。
4. **知识图谱**：提取可复用的知识点，供日后翻阅。

注意：
- 只输出 JSON，不要添加任何解释性文字
- 所有字段都必须填写，不确定的字段填合理默认值
- confidence 范围 0.0-1.0
- 基于具体对话证据，避免主观臆断""",
    parser=_parse_deep_analysis,
    max_tokens=4096,
    input_truncate=16000,
    feature_flag="enhance_analysis",
)
