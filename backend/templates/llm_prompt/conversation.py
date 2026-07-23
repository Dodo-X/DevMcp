from backend.templates.llm_prompt._common import AnalysisTask, parse_json


def _parse_conversation_analysis(raw: str) -> dict:
    """对话分析专用解析器：解析 + 标注来源"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm"
        from datetime import datetime

        parsed["generated_at"] = datetime.now().isoformat()
    return parsed


TASK_CONVERSATION_ANALYSIS = AnalysisTask(
    name="conversation_analysis",
    description="对话内容分析（技能领域/复杂度/反馈）",
    prompt_template="""分析以下对话内容并提取关键信息。

任务：
1. 概括对话核心内容
2. 识别技术领域和技能点
3. 评估问题复杂度
4. 检测用户反馈信号

注意：user_traits 不在此任务中提取，由独立的 user_profile 任务专门处理。

## 输出要求（严格 JSON）
只输出 JSON，不要包含任何其他文字：

```json
{{
  "summary": "一句话概括对话核心内容（100字以内）",
  "skill_domains": [
    {{
      "domain": "技术领域名称",
      "sub_skills": ["具体技能点列表"],
      "evidence": "支持判断的关键词或上下文"
    }}
  ],
  "complexity": "simple 或 multi_step 或 complex",
  "complexity_reason": "复杂度判断依据",
  "user_feedback": {{
    "has_feedback": true,
    "types": ["纠正/补充/不满/重试/追问"],
    "severity": "none/low/medium/high",
    "detail": "反馈内容摘要"
  }}
}}
```

## 待分析对话内容
来源: {source} | 客户端: {client}

{content}

注意：
1. 只输出 JSON，不要添加任何解释性文字
2. 所有字段都必须填写，不确定的字段填默认值""",
    parser=_parse_conversation_analysis,
    max_tokens=1500,
    input_truncate=32768,
    feature_flag="enhance_analysis",
)
