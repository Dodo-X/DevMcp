from devpartner_agent.core.llm_prompts._common import AnalysisTask, parse_json

def _parse_self_improvement(raw: str) -> list:
    """自我改进专用解析器：返回建议列表"""
    parsed = parse_json(raw)
    if parsed and isinstance(parsed.get("suggestions"), list):
        from datetime import datetime
        for s in parsed["suggestions"]:
            s["source"] = "llm"
            s["generated_at"] = datetime.now().isoformat()
        return parsed["suggestions"]
    return []

TASK_SELF_IMPROVEMENT = AnalysisTask(
    name="self_improvement",
    description="系统自我改进建议生成",
    prompt_template="""你是一个专业的系统自我优化 AI 助手。基于以下 DevPartner 系统运行数据，生成改进建议。

## 系统运行数据
{system_data}

## 历史优化记录
{improvement_history}

## 输出要求
请分析系统状态并输出改进建议 JSON:

```json
{{
  "analysis": {{
    "system_health": "excellent/good/fair/poor",
    "key_findings": ["关键发现"],
    "pain_points": ["痛点问题"]
  }},
  "suggestions": [
    {{
      "category": "performance/usability/reliability/feature",
      "target": "优化目标",
      "description": "问题描述",
      "suggestion": "具体改进建议",
      "priority": "low/medium/high",
      "effort": "low/medium/high"
    }}
  ]
}}
```

注意：只输出 JSON""",
    parser=_parse_self_improvement,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_self_improvement",
)