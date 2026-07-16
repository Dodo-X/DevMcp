from devpartner_agent.core.llm_prompts._common import AnalysisTask, parse_json

def _parse_conversation_analysis(raw: str) -> dict:
    """对话分析专用解析器：解析 + 标准化"""
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm"
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
    return parsed

TASK_CONVERSATION_ANALYSIS = AnalysisTask(
    name="conversation_analysis",
    description="对话内容分析（技能领域/复杂度/反馈/工具缺口）",
    prompt_template="""你是一个专业的开发者对话分析 AI 助手。请分析以下对话内容并提取关键信息。

## 你的任务
1. 识别技术领域和技能点
2. 评估问题复杂度
3. 检测用户反馈信号
4. 识别应该调用但可能遗漏的 MCP 工具
5. 提取用户行为特征和技能画像

## 输出要求（严格 JSON 格式）
请只输出 JSON，不要包含任何其他文字：

```json
{{
  "summary": "一句话概括对话核心内容（100字以内）",
  "skill_domains": [
    {{
      "domain": "技术领域名称",
      "sub_skills": ["具体技能点列表"],
      "match_score": 0.95,
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
  }},
  "tool_gaps": [
    {{
      "tool": "工具名称",
      "reason": "为什么应该调用",
      "priority": "low/medium/high"
    }}
  ],
  "user_traits": {{
    "skills_observed": ["用户展现的技术技能"],
    "behavior_notes": "用户的行为模式观察",
    "mistakes": ["用户犯过的错误或踩过的坑"],
    "strengths": ["用户的强项和优势"],
    "communication_style": "直接 | 委婉 | 详细 | 简洁",
    "decision_pattern": "数据驱动 | 直觉 | 谨慎 | 大胆",
    "tech_interests": ["感兴趣的技术方向"],
    "areas_for_growth": ["需要提升的领域"],
    "emotional_state": "专注 | 焦虑 | 兴奋 | 疲惫 | 平静",
    "learning_progress": "具体收获总结（如'学会了使用 async/await 处理并发'）"
  }}
}}
```

## 待分析对话内容
来源: {source} | 客户端: {client}

{content}

注意：
1. 只输出 JSON，不要添加任何解释性文字
2. match_score 范围 0.0-1.0
3. 所有字段都必须填写，不确定的字段填默认值
4. emotional_state: 根据对话语气、措辞、响应速度判断用户当前情绪
5. learning_progress: 该对话中用户是否展现了新的知识收获，概括之""",
    parser=_parse_conversation_analysis,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)