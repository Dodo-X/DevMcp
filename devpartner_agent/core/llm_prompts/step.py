from devpartner_agent.core.llm_prompts._common import AnalysisTask, parse_json

def _parse_step_analysis(raw: str) -> dict:
    """步骤分析专用解析器"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_step_analysis"
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
    return parsed

TASK_STEP_ANALYSIS = AnalysisTask(
    name="step_analysis",
    description="对话步骤内容分析（知识点/改进建议）",
    prompt_template="""你是一个专业的开发者对话步骤分析 AI 助手。请分析以下对话步骤并提取关键信息。

## 步骤信息
- 步骤名称: {step_name}
- 步骤类型: {step_type}
- 症状: {symptom}
- 根因: {root_cause}
- 解决方案: {solution}

## 步骤内容
{content}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "step_summary": "步骤核心内容概括（100字以内）",
  "skill_domains": ["涉及的技术领域"],
  "knowledge_points": ["提取的知识点"],
  "difficulty": "easy/medium/hard",
  "key_insights": ["关键洞察"],
  "improvement_suggestions": ["改进建议"],
  "related_tools": ["相关MCP工具"]
}}
```

注意：只输出 JSON，不要其他文字""",
    parser=_parse_step_analysis,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)