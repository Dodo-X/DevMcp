from devpartner_agent.core.llm_prompts._common import AnalysisTask, parse_json

def _parse_deep_analysis(raw: str) -> dict:
    """对话深层分析专用解析器"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_conversation_deep_analysis"
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
    return parsed

TASK_CONVERSATION_DEEP_ANALYSIS = AnalysisTask(
    name="conversation_deep_analysis",
    description="对话深层分析（总结/反思/知识提取）",
    prompt_template="""你是一个专业的开发者对话深层分析 AI 助手。请对以下已完成的对话进行深度分析。

## 对话摘要
{summary}

## 自我反思
{self_reflection}

## 用户特征
{user_traits}

## 关键决策
{key_decisions}

## 步骤摘要
{steps_summary}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "deep_summary": "深度总结（200字以内）",
  "knowledge_extracted": [
    {{
      "topic": "知识点主题",
      "content": "知识点详细内容",
      "domain": "技术领域",
      "importance": "high/medium/low"
    }}
  ],
  "pattern_insights": ["发现的模式和规律"],
  "skill_progression": ["技能成长轨迹"],
  "improvement_areas": ["需要改进的领域"]
}}
```

注意：只输出 JSON""",
    parser=_parse_deep_analysis,
    max_tokens=2048,
    input_truncate=10000,
    feature_flag="enhance_analysis",
)