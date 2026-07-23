from backend.templates.llm_prompt._common import AnalysisTask, parse_json


def _parse_knowledge_extraction(raw: str) -> list:
    parsed = parse_json(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "conversations" in parsed:
        return parsed["conversations"]
    return parsed


TASK_KNOWLEDGE_EXTRACTION = AnalysisTask(
    name="knowledge_extraction",
    description="从对话中提取技能知识点和业务知识点",
    prompt_template="""从以下对话中提取**技能知识点**和**业务知识点**。

项目名称：{project_name}

## domain 归类规则
- type=skill 时，domain 必须从标准领域选择：Python | 前端 | AI/LLM | DevOps | 数据库 | 架构设计 | 通用工程
- type=business 时，domain 必须填写 "{project_name}"
- 技能知识：通用编程技巧、框架、工具使用方法
- 业务知识：与项目 {project_name} 直接相关的业务规则、决策、流程、配置

## 已有知识标题（最多 200 条，超出已截断）
{existing_titles_list}

## 对话内容
{conversation_text}

请直接返回 JSON 数组，不要包含其他解释。
[
  {{
    "type": "skill/business",
    "domain": "标准技术领域名 或 {project_name}",
    "title": "...",
    "content": "...",
    "category": "...",
    "tags": ["...", "..."],
    "difficulty": "easy/medium/hard/expert",
    "aliases": ["别名1", "别名2"],
    "related_titles": ["已有标题A", "已有标题B"]
  }}
]""",
    parser=_parse_knowledge_extraction,
    max_tokens=4096,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)


def _parse_batch_step_analysis(raw: str) -> list:
    parsed = parse_json(raw)
    if isinstance(parsed, list):
        return parsed
    return parsed


TASK_BATCH_STEP_ANALYSIS = AnalysisTask(
    name="batch_step_analysis",
    description="批量分析多个开发步骤（思考模式/命令/语法/复杂度）",
    prompt_template="""请分析以下多个开发步骤，对每个步骤提取：思考模式、使用的命令、语法知识点、复杂度评估。
输出 JSON 数组，每个元素对应一个步骤，包含 step_id, thinking_patterns, commands_used, syntax_points, complexity_level, key_decision 字段。

步骤数据：
{steps_data}""",
    parser=_parse_batch_step_analysis,
    max_tokens=4096,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)
