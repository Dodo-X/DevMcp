from backend.templates.llm_prompt._common import (
    AnalysisTask,
    normalize_analysis,
    parse_json,
    run_analysis,
)

# v9.8.4: 从业务代码中提取的辅助 prompt
from backend.templates.llm_prompt.auxiliary import (
    TASK_QUESTION_EXPAND,
    TASK_REVIEW_PROJECT_DESC,
    TASK_USER_TRAITS_ENRICH,
)
from backend.templates.llm_prompt.conversation import TASK_CONVERSATION_ANALYSIS
from backend.templates.llm_prompt.daily_summary import TASK_DAILY_SUMMARY
from backend.templates.llm_prompt.deep_analysis import (
    TASK_BUSINESS_TECH_ASSESSMENT,
    TASK_CONV_USER_PROFILE,
)
from backend.templates.llm_prompt.file_parse import TASK_FILE_PARSE
from backend.templates.llm_prompt.knowledge_extraction import (
    TASK_BATCH_STEP_ANALYSIS,
    TASK_KNOWLEDGE_EXTRACTION,
)
from backend.templates.llm_prompt.schema import TASK_SCHEMA_ANALYSIS

# NOTE(架构迁移发现的历史遗留问题)：TASK_WEEKLY_REPORT / TASK_MONTHLY_REPORT /
# TASK_ANNUAL_REPORT / TASK_GROWTH_ANALYSIS 从未在任何 prompt 模块中定义，
# 原 prompts 包因此在包级导入时就会 ImportError（导致所有 `from prompts import ...`
# 静默走 fallback）。此处移除这 4 个死引用以恢复包可导入性；
# 周/月/年/成长报告的 prompt 需后续单独补充定义。
from backend.templates.llm_prompt.self_improvement import TASK_SELF_IMPROVEMENT
from backend.templates.llm_prompt.step import TASK_STEP_ANALYSIS
from backend.templates.llm_prompt.user_profile import (
    ANALYSIS_GUIDELINES,
    FEW_SHOT_EXAMPLES,
    PROJECT_STRATEGY,
    TASK_USER_PROFILE_ANALYSIS,
    USER_TRAITS_SCHEMA,
)

TASK_REGISTRY = {
    "conversation_analysis": TASK_CONVERSATION_ANALYSIS,
    "step_analysis": TASK_STEP_ANALYSIS,
    # v9.8.0: 拆分的三个子任务
    "business_tech_assessment": TASK_BUSINESS_TECH_ASSESSMENT,
    "conversation_user_profile": TASK_CONV_USER_PROFILE,
    "daily_summary": TASK_DAILY_SUMMARY,
    # weekly/monthly/annual/growth 的 prompt 任务未定义，暂不注册（见上方 NOTE）
    "self_improvement": TASK_SELF_IMPROVEMENT,
    "file_parse": TASK_FILE_PARSE,
    "schema_analysis": TASK_SCHEMA_ANALYSIS,
    "user_profile_analysis": TASK_USER_PROFILE_ANALYSIS,
    "knowledge_extraction": TASK_KNOWLEDGE_EXTRACTION,
    "batch_step_analysis": TASK_BATCH_STEP_ANALYSIS,
    # v9.8.4: 辅助 prompt
    "review_project_description": TASK_REVIEW_PROJECT_DESC,
    "user_traits_enrich": TASK_USER_TRAITS_ENRICH,
    "question_expand": TASK_QUESTION_EXPAND,
}


def get_task(name: str):
    return TASK_REGISTRY.get(name)
