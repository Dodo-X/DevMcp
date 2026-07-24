from backend.templates.llm_prompt._common import AnalysisTask, parse_json


def _parse_knowledge_extraction(raw: str) -> list:
    parsed = parse_json(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "conversations" in parsed:
        return parsed["conversations"]
    return parsed


# NOTE(T3): 已废弃 —— extract_all 不再使用此「一次巨调用」Prompt。
# 保留常量仅为导入兼容 / A-B 对照（设计 §8.2 风险缓解）。
# skill/business 的聚焦拆分见下方 TASK_SKILL_EXTRACTION / TASK_BUSINESS_EXTRACTION。
TASK_KNOWLEDGE_EXTRACTION = AnalysisTask(
    name="knowledge_extraction",
    description="从对话中提取技能知识点和业务知识点（已废弃：请用 TASK_SKILL_EXTRACTION + TASK_BUSINESS_EXTRACTION）",
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


# ══════════════════════════════════════════════════════════
# T3: 拆分后的两个聚焦子请求 Prompt（替代 TASK_KNOWLEDGE_EXTRACTION 的一次巨调用）
# ══════════════════════════════════════════════════════════

def _parse_knowledge_list(raw: str) -> list:
    """通用列表解析：LLM 返回 JSON 数组；兼容 `{"items": [...]}` 包装。"""
    parsed = parse_json(raw)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "items" in parsed:
        return parsed["items"]
    return parsed


TASK_SKILL_EXTRACTION = AnalysisTask(
    name="skill_extraction",
    description="从对话中提取通用技能知识点（Cards）",
    prompt_template="""从以下对话中提取**通用技能知识点**（Cards）——可跨项目复用的通用技巧、语法、框架用法、工具方法。

项目名称：{project_name}

## domain 归类规则（硬约束）
- domain 必须从以下标准领域选择其一（不要自创）：
  Python | 前端 | AI/LLM | DevOps | 数据库 | 架构设计 | 通用工程
- 仅提取通用知识，不要提取项目特有的业务规则 / 配置 / 流程（那些属于业务知识，由另一个任务处理）

## 已有知识标题（最多 200 条，超出已截断）
{existing_titles_list}

## 对话内容
{conversation_text}

请直接返回 JSON 数组（不要包含其他解释）：
[
  {{
    "domain": "Python",
    "title": "...",
    "content": "...",
    "tag": "装饰器",
    "difficulty": "easy/medium/hard/expert"
  }}
]
注意：
- tag 为单个字符串（单值），不要返回数组；不要为同一条知识写多个 tag
- difficulty 取 easy/medium/hard/expert 之一""",
    parser=_parse_knowledge_list,
    max_tokens=4096,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)


TASK_BUSINESS_EXTRACTION = AnalysisTask(
    name="business_extraction",
    description="从对话中提取项目业务知识（Efforts）",
    prompt_template="""从以下对话中提取**项目业务知识**（Efforts）——当前项目的业务规则、决策、流程、配置。

项目名（即 domain）：{project_name}

## 已知模块清单（提示，供你归类；可沿用也可补充新模块）
{modules_hint}

## 已有业务知识标题（最多 200 条，超出已截断）
{existing_titles_list}

## 对话内容
{conversation_text}

请直接返回 JSON 数组（不要包含其他解释）：
[
  {{
    "module": "报告生成",
    "title": "...",
    "content": "...",
    "tag": "报告生成",
    "difficulty": "easy/medium/hard/expert"
  }}
]
注意：
- module 为单个字符串，尽量匹配上方「已知模块清单」中的模块名；若无匹配则给出简洁的模块名
- tag 为单个字符串（单值），通常与 module 一致或为其子主题
- difficulty 取 easy/medium/hard/expert 之一""",
    parser=_parse_knowledge_list,
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
