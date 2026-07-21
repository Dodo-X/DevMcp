
from prompts.conversation import TASK_CONVERSATION_ANALYSIS
from prompts.step import TASK_STEP_ANALYSIS
from prompts.deep_analysis import TASK_CONVERSATION_DEEP_ANALYSIS
from prompts.daily_summary import TASK_DAILY_SUMMARY
from prompts.daily_summary import TASK_WEEKLY_REPORT
from prompts.daily_summary import TASK_MONTHLY_REPORT
from prompts.daily_summary import TASK_ANNUAL_REPORT
from prompts.daily_summary import TASK_GROWTH_ANALYSIS
from prompts.self_improvement import TASK_SELF_IMPROVEMENT
from prompts.file_parse import TASK_FILE_PARSE
from prompts.schema import TASK_SCHEMA_ANALYSIS
from prompts.knowledge_extraction import (
    TASK_KNOWLEDGE_EXTRACTION,
    TASK_BATCH_STEP_ANALYSIS,
)
from prompts.user_profile import (
    TASK_USER_PROFILE_ANALYSIS,
    TASK_DAILY_PROFILE_MERGE,
    TASK_DAILY_SYSTEM_MERGE,
    USER_TRAITS_SCHEMA,
    PROJECT_STRATEGY,
    FEW_SHOT_EXAMPLES,
    ANALYSIS_GUIDELINES,
)

from prompts._common import (
    parse_json,
    normalize_analysis,
    AnalysisTask,
    run_analysis,
)

TASK_REGISTRY = {
    'conversation_analysis': TASK_CONVERSATION_ANALYSIS,
    'step_analysis': TASK_STEP_ANALYSIS,
    'conversation_deep_analysis': TASK_CONVERSATION_DEEP_ANALYSIS,
    'daily_summary': TASK_DAILY_SUMMARY,
    'weekly_report': TASK_WEEKLY_REPORT,
    'monthly_report': TASK_MONTHLY_REPORT,
    'annual_report': TASK_ANNUAL_REPORT,
    'growth_analysis': TASK_GROWTH_ANALYSIS,
    'self_improvement': TASK_SELF_IMPROVEMENT,
    'file_parse': TASK_FILE_PARSE,
    'schema_analysis': TASK_SCHEMA_ANALYSIS,
    'user_profile_analysis': TASK_USER_PROFILE_ANALYSIS,
    'daily_profile_merge': TASK_DAILY_PROFILE_MERGE,
    'daily_system_merge': TASK_DAILY_SYSTEM_MERGE,
    'knowledge_extraction': TASK_KNOWLEDGE_EXTRACTION,
    'batch_step_analysis': TASK_BATCH_STEP_ANALYSIS,
}


def get_task(name: str):
    return TASK_REGISTRY.get(name)