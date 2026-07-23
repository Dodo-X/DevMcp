from backend.templates.llm_prompt._common import (
    AnalysisTask,
    extract_behavior_signals,
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

# v9.10.1: 长周期报告 prompt（周/月/年/成长）— 此前在架构迁移时被误删，现补回
from backend.templates.llm_prompt.reports_prompts import (
    TASK_ANNUAL_REPORT,
    TASK_GROWTH_ANALYSIS,
    TASK_MONTHLY_REPORT,
    TASK_WEEKLY_REPORT,
)
from backend.templates.llm_prompt.schema import TASK_SCHEMA_ANALYSIS

# NOTE(v9.10.1): TASK_WEEKLY_REPORT / TASK_MONTHLY_REPORT / TASK_ANNUAL_REPORT /
# TASK_GROWTH_ANALYSIS 此前在架构迁移时被误删，导致 reports.py 调用即 ImportError、
# 周/月/年/成长报告从未真正生成。现已在 reports_prompts.py 补回并注册。
from backend.templates.llm_prompt.self_improvement import TASK_SELF_IMPROVEMENT
from backend.templates.llm_prompt.step import TASK_STEP_ANALYSIS
from backend.templates.llm_prompt.user_profile import TASK_USER_PROFILE_ANALYSIS

TASK_REGISTRY = {
    "conversation_analysis": TASK_CONVERSATION_ANALYSIS,
    "step_analysis": TASK_STEP_ANALYSIS,
    # v9.8.0: 拆分的三个子任务
    "business_tech_assessment": TASK_BUSINESS_TECH_ASSESSMENT,
    "conversation_user_profile": TASK_CONV_USER_PROFILE,
    "daily_summary": TASK_DAILY_SUMMARY,
    # v9.10.1: 长周期报告 prompt（此前缺失，reports.py 调用即 ImportError）
    "weekly_report": TASK_WEEKLY_REPORT,
    "monthly_report": TASK_MONTHLY_REPORT,
    "annual_report": TASK_ANNUAL_REPORT,
    "growth_analysis": TASK_GROWTH_ANALYSIS,
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
