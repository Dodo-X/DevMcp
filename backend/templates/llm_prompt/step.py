from backend.templates.llm_prompt._common import AnalysisTask, parse_json


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
    description="对话步骤内容分析（解题思路/推测过程/知识点提纯）",
    prompt_template="""你是一个专业的开发者对话步骤分析 AI 助手。你的任务是将对话步骤**提纯**为可复用的解题思路和知识点，而非简单概括。

## 步骤信息
- 步骤名称: {step_name}
- 步骤类型: {step_type}
- 症状: {symptom}
- 根因: {root_cause}
- 解决方案: {solution}
- AI推测过程: {ai_reasoning}
- 用户需求: {user_requirement}
- 命令执行: {commands_executed}

## 步骤内容
{content}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "step_summary": "步骤核心内容概括（100字以内）",
  "skill_domains": ["涉及的技术领域"],
  "difficulty": "easy/medium/hard",

  "problem_solving_pattern": {{
    "requirement": "用户原始需求（一句话）",
    "ai_interpretation": "AI 对需求的理解和推测",
    "approach": "采取的解题思路/方法论（如：先定位→再分析→最后修复）",
    "why_this_approach": "为什么选这个思路而非其他方案",
    "dead_ends": ["探索过但放弃的方向（如有）"]
  }},

  "knowledge_points": [
    {{
      "title": "知识点标题",
      "desc": "知识点描述（可独立理解，脱离上下文仍有价值）",
      "domain": "所属技术领域",
      "tags": ["标签1", "标签2"],
      "difficulty": "basic/intermediate/advanced",
      "prerequisites": ["前置知识点"],
      "related_patterns": ["相关解题模式"]
    }}
  ],

  "commands_used": [
    {{
      "command": "执行的命令原文",
      "purpose": "命令目的",
      "key_flags": ["关键参数说明"],
      "gotcha": "注意事项/踩坑点"
    }}
  ],

  "key_insights": ["关键洞察（可迁移到其他场景的规律性认识）"],
  "improvement_suggestions": ["改进建议（面向用户技能提升）"],
  "related_tools": ["相关工具/框架"],

  "thinking_patterns": ["展现的思维模式（如：二分排查、假设验证、类比迁移）"],
  "complexity_level": "simple/medium/complex"
}}
```

## 提纯原则
1. **knowledge_points 必须可独立理解** — 脱离上下文仍有价值，能作为 Obsidian 笔记卡片
2. **problem_solving_pattern 是核心** — 记录「需求→推测→思路→为什么」，这是自我提升的关键数据
3. **commands_used 要记录坑点** — 不仅记录命令本身，还要记录为什么用这个参数、踩过什么坑
4. **key_insights 要有迁移性** — 不是"修了X的bug"，而是"当遇到Y类问题时，应该先检查Z"
5. **improvement_suggestions 面向用户** — 基于步骤中暴露的问题，给出具体可执行的提升建议

注意：只输出 JSON，不要其他文字""",
    parser=_parse_step_analysis,
    max_tokens=4096,
    input_truncate=12000,
    feature_flag="enhance_analysis",
)
