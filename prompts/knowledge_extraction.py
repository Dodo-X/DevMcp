from prompts._common import AnalysisTask, parse_json


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
    prompt_template="""你是一个知识提取专家。请从以下对话中提取**技能知识点**和**业务知识点**。

项目名称：{project_name}

## domain 字段归类规则（v9.3 强化）

### type=skill 时，domain 必须从以下标准领域中选择一个，不要自创领域名：
- **Python**：Python语法、包管理、Django/FastAPI/Flask、pytest、Python调试
- **前端**：HTML/CSS/JavaScript/TypeScript、React/Vue、前端调试、前后端联调
- **AI/LLM**：LLM应用、Prompt Engineering、RAG、Agent、MCP协议、Ollama、AI/ML框架
- **DevOps**：Docker/Kubernetes、CI/CD、Linux运维、Git/GitHub
- **数据库**：SQL/SQLite/MySQL/PostgreSQL/Redis、WAL模式、索引优化
- **架构设计**：系统架构、设计模式、微服务、并发编程、异步设计、重构
- **通用工程**：代码质量、安全、调试、测试、文档、问题定位

### type=business 时，domain **必须**填写项目名 "{project_name}"

### 其他要求
- 技能知识：通用的编程技巧、框架、工具使用方法等。
- 业务知识：与项目 {project_name} 直接相关的业务规则、决策、流程、配置等。
- 每个知识点输出 JSON 格式，包含 title, content, category, tags (数组), difficulty, aliases (别名数组)。
- 分析每个新知识点与以下**已有知识标题**的关联，在 related_titles 中列出你认为相关的已有标题（最多5个）。

已有知识标题列表：
{existing_titles_list}

## 对话内容
{conversation_text}

请直接返回 JSON 数组，不要包含其他解释。
[
  {{
    "type": "skill/business",
    "domain": "标准技术领域名 或 项目名 {project_name}",
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