from prompts._common import AnalysisTask, parse_json

USER_TRAITS_SCHEMA = {
    "version": "9.3",
    "schema_type": "json_schema",
    "fields": {
        "skills_observed": {"type": "array[string]", "description": "从对话中识别的技术技能列表（旧格式，保留兼容）"},
        "skills_with_domains": {
            "type": "array[object]",
            "description": "【v9.3 推荐】技能+领域结构化列表，每个元素包含 skill_name 和 skill_domain",
            "properties": {
                "skill_name": {"type": "string", "description": "具体技能名称"},
                "skill_domain": {"type": "string", "description": "所属技术领域"},
            },
        },
        "behavior_notes": {"type": "string", "description": "学习习惯、问题解决方式、沟通特点"},
        "tech_interests": {"type": "array[string]", "description": "用户表现出的技术兴趣方向"},
        "areas_for_growth": {"type": "array[string]", "description": "需要提升或学习的领域"},
        "mistakes": {"type": "array[string]", "description": "常见的错误模式或知识盲区"},
        "strengths": {"type": "array[string]", "description": "明显的优势和能力"},
        "communication_style": {"type": "string", "enum": ["详细型", "简洁型", "示例驱动型", "理论导向型"]},
        "decision_pattern": {"type": "string", "enum": ["快速决策", "深思熟虑", "依据建议", "自主探索"]},
        "emotional_state": {"type": "string", "enum": ["积极", "中性", "焦虑", "挫折"]},
        "learning_progress": {"type": "object", "properties": {"current_level": "string", "target_level": "string", "gap_analysis": "string"}},
    },
    "required_fields": ["skills_with_domains", "behavior_notes"],
}

PROJECT_STRATEGY = {
    "focus_areas": [
        "前端框架 (React/Vue/Angular)",
        "后端开发 (Python/Django/FastAPI)",
        "数据库设计 (SQL/NoSQL)",
        "DevOps 工具链 (Docker/Git/CI-CD)",
        "AI/ML 应用 (LLM/RAG/Agent)",
    ],
    "priority_skills": [
        "TypeScript 类型安全编程",
        "现代前端工程化",
        "微服务架构设计",
        "云原生部署实践",
    ],
    "learning_path_suggestion": (
        "1) 基础巩固阶段：熟练掌握当前技术栈核心概念。"
        " 2) 进阶提升阶段：深入理解底层原理和最佳实践。"
        " 3) 专家成长阶段：关注前沿技术和架构趋势。"
    ),
}

FEW_SHOT_EXAMPLES = [
    {
        "scenario": "前端开发者讨论 React 性能优化",
        "input_dialogue": "我在用 React + TypeScript 开发一个电商项目，遇到了 Redux Toolkit 的异步 action 类型定义错误。",
        "expected_output": {
            "skill_domains": ["frontend", "typescript"],
            "complexity": "moderate",
            "user_traits": {
                "skill_level": "intermediate",
                "learning_style": "示例驱动型",
                "communication_style": "详细型",
                "emotional_state": "中性",
                "areas_for_growth": ["类型编程", "react生态"],
                "tech_interests": ["React", "TypeScript"],
                "behavior_notes": "偏好详细解释和代码示例",
                "learning_progress": "已掌握基础，正在进阶",
            },
        },
    },
    {
        "scenario": "后端开发者讨论数据库性能",
        "input_dialogue": "Django ORM 的 N+1 查询问题怎么解决？我试了 select_related 但还是慢。",
        "expected_output": {
            "skills_observed": ["Python/Django", "ORM 使用", "数据库性能调优"],
            "skills_with_domains": [
                {"skill_name": "Django ORM", "skill_domain": "Python"},
                {"skill_name": "SQL 查询优化", "skill_domain": "数据库"},
                {"skill_name": "N+1 问题诊断", "skill_domain": "数据库"},
            ],
            "behavior_notes": "遇到性能问题会主动尝试常见方案再求助",
            "tech_interests": ["后端架构", "数据库优化"],
            "areas_for_growth": ["SQL 执行计划分析", "缓存策略设计"],
            "mistakes": ["混淆 select_related 和 prefetch_related"],
            "strengths": ["有性能优化意识"],
        },
    },
    {
        "scenario": "DevOps 工具链讨论",
        "input_dialogue": "我想搭建一个 CI/CD 流水线，用 GitHub Actions 自动部署到 Docker 容器。",
        "expected_output": {
            "skills_observed": ["Docker 容器化", "CI/CD 概念", "GitHub Actions"],
            "skills_with_domains": [
                {"skill_name": "Docker 容器化", "skill_domain": "DevOps"},
                {"skill_name": "GitHub Actions", "skill_domain": "DevOps"},
                {"skill_name": "CI/CD 流水线设计", "skill_domain": "DevOps"},
            ],
            "behavior_notes": "目标明确，希望系统地解决问题",
            "tech_interests": ["自动化运维", "DevOps 实践"],
            "areas_for_growth": ["YAML 工作流编写", "多环境部署策略"],
            "mistakes": ["缺少根因分析"],
            "strengths": ["有自动化意识"],
        },
    },
]

ANALYSIS_GUIDELINES = {
    "focus_areas": [
        "技术技能识别与等级评估",
        "技能领域归类（必须使用标准领域名）",
        "学习行为模式分析",
        "常见错误与改进方向",
        "沟通偏好与决策风格",
        "情绪状态与学习进度",
    ],
    "output_format": {
        "skills_observed": "已掌握的技术技能列表（旧格式）",
        "skills_with_domains": "[{\"skill_name\": \"...\", \"skill_domain\": \"...\"}] 技能+领域结构化列表",
        "behavior_notes": "学习习惯、问题解决方式、沟通特点",
        "tech_interests": "感兴趣的技术方向",
        "areas_for_growth": "需要提升的领域",
        "mistakes": "常见错误模式",
        "strengths": "明显优势",
        "learning_progress": "当前水平 → 目标水平的差距分析",
    },
    "standard_domains": [
        "Python", "前端", "AI/LLM", "DevOps", "数据库", "架构设计", "通用工程",
    ],
    "quality_requirements": [
        "基于具体对话证据，避免主观臆断",
        "区分'已知能力'和'正在学习'",
        "标注置信度（high/medium/low）",
        "提供可操作的成长建议",
        "skill_domain 必须从标准领域列表中选择",
    ],
}


def _parse_user_profile(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        parsed["source"] = "llm_user_profile"
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
    return parsed


TASK_USER_PROFILE_ANALYSIS = AnalysisTask(
    name="user_profile_analysis",
    description="用户画像分析（技能/行为/兴趣/成长方向）",
    prompt_template="""你是一个专业的开发者画像分析 AI 助手。请根据以下信息分析用户画像。

## 用户画像 Schema
{user_traits_schema}

## 项目策略
{project_strategy}

## Few-shot 示例
{few_shot_examples}

## 分析指南
{analysis_guidelines}

## 待分析数据
分析范围: {analysis_scope}
客户端上下文: {client_context}

最近对话数据:
{recent_data}

## 输出要求（严格 JSON 格式）
请只输出 JSON，不要包含任何其他文字：

```json
{{
  "skills_observed": ["已掌握的技术技能（旧格式，保留兼容）"],
  "skills_with_domains": [
    {{
      "skill_name": "具体技能名称（如 FastAPI、React Hooks、Docker Compose）",
      "skill_domain": "所属技术领域"
    }}
  ],
  "behavior_notes": "学习习惯、问题解决方式、沟通特点",
  "tech_interests": ["感兴趣的技术方向"],
  "areas_for_growth": ["需要提升的领域"],
  "mistakes": ["常见错误模式"],
  "strengths": ["明显优势"],
  "communication_style": "详细型 | 简洁型 | 示例驱动型 | 理论导向型",
  "decision_pattern": "快速决策 | 深思熟虑 | 依据建议 | 自主探索",
  "emotional_state": "积极 | 中性 | 焦虑 | 挫折",
  "learning_progress": {{
    "current_level": "当前水平描述",
    "target_level": "目标水平描述",
    "gap_analysis": "差距分析"
  }},
  "confidence": 0.85
}}
```

## skill_domain 归类规则（重要）
请将每个技能归入以下标准领域之一，不要自创领域名：
- **Python**：Python语法、pip/conda包管理、Django/FastAPI/Flask框架、pytest测试
- **前端**：HTML/CSS/JavaScript/TypeScript、React/Vue/Angular、Webpack/Vite、前端调试、前后端联调
- **AI/LLM**：LLM应用开发、Prompt Engineering、RAG、Agent、MCP协议、Ponytail原则、AI/ML框架
- **DevOps**：Docker/Kubernetes、CI/CD、Linux运维、Nginx、Git/GitHub
- **数据库**：SQL/SQLite/MySQL/PostgreSQL/Redis/MongoDB、WAL模式、索引优化
- **架构设计**：系统架构、设计模式、微服务、并发编程、异步设计、重构
- **通用工程**：代码质量、安全、调试、测试、文档、问题定位

注意：
1. 只输出 JSON，不要添加任何解释性文字
2. 所有字段都必须填写，不确定的字段填默认值
3. confidence 范围 0.0-1.0
4. 基于具体对话证据，避免主观臆断
5. **skill_domain 必须从上述7个标准领域中选择**""",
    parser=_parse_user_profile,
    max_tokens=2048,
    input_truncate=8000,
    feature_flag="enhance_analysis",
)


def _parse_profile_merge(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_daily_profile_merge"
    return parsed


TASK_DAILY_PROFILE_MERGE = AnalysisTask(
    name="daily_profile_merge",
    description="每日用户画像合并（行为信号 → 全局画像维度更新）",
    prompt_template="""你是一个专业的开发者画像分析 AI 助手。请基于以下当日用户行为信号片段，合并生成全局用户画像更新。

## 当日行为信号片段
{behavior_signals_json}

## 当前全局用户画像
{current_profile_json}

## 当日对话摘要
{daily_conversations_summary}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "dimensions": [
    {{
      "dimension": "画像维度名称（如 skill_level_python, communication_style, decision_pattern 等）",
      "value": "维度值",
      "confidence": 0.8,
      "evidence": "支持此判断的行为信号证据",
      "trend": "stable/rising/declining"
    }}
  ],
  "new_insights": ["当日新发现的用户特征"],
  "changed_dimensions": ["相比全局画像发生变化的维度"],
  "merge_summary": "一句话总结当日画像变化"
}}
```

维度建议（但不限于）：
- skill_level_{{lang}}: 技术技能等级（beginner/intermediate/advanced/expert）
- communication_style: 沟通风格（详细型/简洁型/示例驱动型/理论导向型）
- decision_pattern: 决策模式（快速决策/深思熟虑/依据建议/自主探索）
- emotional_tendency: 情绪倾向（积极/中性/焦虑/挫折）
- learning_style: 学习风格（实践型/理论型/示例驱动型）
- problem_solving: 问题解决方式（系统排查/直觉驱动/求助型/自主探索）
- tech_interests: 技术兴趣方向列表
- areas_for_growth: 需要提升的领域列表

注意：
1. 只输出 JSON
2. confidence 范围 0.0-1.0
3. 基于行为信号证据，避免主观臆断
4. 与全局画像对比，标注变化趋势""",
    parser=_parse_profile_merge,
    max_tokens=2048,
    input_truncate=8000,
    timeout=300,  # 重型分析任务，prompt ~12KB，Qwen3.5-9B 需要 2-5 分钟
    feature_flag="enhance_profile_merge",
)


def _parse_system_merge(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_daily_system_merge"
    return parsed


# ────────────────────────────────────────────────
# v9.1.1: behavior_signals 从硬编码关键词 → LLM 分析 ai_analysis
# ────────────────────────────────────────────────


def _parse_behavior_signals(raw: str) -> dict:
    parsed = parse_json(raw)
    if parsed and not parsed.get("parse_error"):
        from datetime import datetime
        parsed["generated_at"] = datetime.now().isoformat()
        parsed["source"] = "llm_behavior_signals"
    return parsed


TASK_BEHAVIOR_SIGNALS = AnalysisTask(
    name="behavior_signals_extraction",
    description="从 AI 分析文本 + 用户原始输入中提取结构化行为信号",
    prompt_template="""你是一个开发者行为分析专家。请分析以下 AI 思考过程，提取用户的行为信号。

## AI 对用户意图的深度分析
{ai_analysis}

## 用户原始输入
{user_raw_input}

## 对话主题
{topic}

## 任务类型
{task_type}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "input_length": {input_length},
  "has_code_block": {has_code_block},
  "has_question_mark": {has_question_mark},
  "has_error_keyword": true_or_false,
  "has_debug_keyword": true_or_false,
  "has_design_keyword": true_or_false,
  "has_optimize_keyword": true_or_false,
  "has_learn_keyword": true_or_false,
  "language_hints": ["从上下文推断的语言列表"],
  "tech_domain": "主要技术领域",
  "user_skill_level_hint": "beginner/intermediate/advanced/expert",
  "user_urgency": "normal/urgent/critical",
  "ai_analysis_based": true
}}
```

注意：
1. 只输出 JSON，不要添加任何解释性文字
2. 语言提示从 AI 分析中推断（如提到 Python/Django → python，提到 React/JS → javascript）
3. 用户技术水平从 AI 分析中推断（如"用户能准确说出3个bug类型"→ intermediate）
4. has_* 字段从用户原始输入中检测（有对应关键词则为 true）
5. ai_analysis_based 固定为 true""",
    parser=_parse_behavior_signals,
    max_tokens=512,
    input_truncate=4000,
    feature_flag="llm_behavior_signals",
)


TASK_DAILY_SYSTEM_MERGE = AnalysisTask(
    name="daily_system_merge",
    description="每日系统认知合并（系统认知片段 → 项目画像更新）",
    prompt_template="""你是一个专业的项目分析 AI 助手。请基于以下当日系统认知片段，合并生成项目画像更新。

## 系统标识
system_id: {system_id}

## 当日系统认知片段
{fragments_json}

## 当前项目画像
{current_project_profile_json}

## 输出要求（严格 JSON 格式）
请只输出 JSON：

```json
{{
  "tech_stack": ["技术栈列表（合并后）"],
  "architecture": {{
    "pattern": "架构模式（如 monolith/microservices/serverless 等）",
    "components": ["核心组件列表"],
    "data_flow": "数据流向描述"
  }},
  "business_domains": ["业务领域列表（合并后）"],
  "maturity": "项目成熟度（unknown/early/growing/mature）",
  "new_discoveries": ["当日新发现的项目特征"],
  "confidence": 0.7,
  "merge_summary": "一句话总结当日项目画像变化"
}}
```

注意：
1. 只输出 JSON
2. 与当前项目画像合并，保留已有认知
3. 新发现的信号优先级高于旧数据
4. confidence 范围 0.0-1.0""",
    parser=_parse_system_merge,
    max_tokens=2048,
    input_truncate=8000,
    timeout=300,  # 重型分析任务
    feature_flag="enhance_system_merge",
)