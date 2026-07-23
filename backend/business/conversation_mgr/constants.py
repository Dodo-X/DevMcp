"""
全局常量定义 (v9.10.1)
======================
从 conversation_engine.py 和 finalize_handlers.py 中提取所有硬编码值。
所有代码统一引用常量，便于统一修改。
"""

# ══════════════════════════════════════════════════════════
# 字段截断长度
# ══════════════════════════════════════════════════════════

TRUNC_RULES = {
    "content": 100_000,
    "symptom": 50_000,
    "root_cause": 50_000,
    "solution": 50_000,
    "ai_reasoning": 50_000,
    "commands": 50_000,
    "user_question": 10_000,
    "user_requirement": 10_000,
    "raw_input": 10_000,
    "ai_analysis": 50_000,
    "ai_summary": 100_000,
    "topic": 200,
    "partial_text": 2_000,
    "error_msg": 500,
    "business_signal": 300,
    "decision_str": 200,
    "profile_value": 2_000,
    "knowledge_content": 2_000,
}

# ══════════════════════════════════════════════════════════
# 任务队列固定参数
# ══════════════════════════════════════════════════════════

TASK_PRIORITY = {
    "step_analysis": 8,
    "conversation_finalize": 10,
    "finalize_business_tech": 10,
    "finalize_user_profile": 9,
    "finalize_knowledge_graph": 9,
    "vault_export_batch": "low",
    "daily_summary": "medium",
}

TASK_MEM_MB = {
    "step_analysis": 100,
    "conversation_finalize": 200,
    "finalize_business_tech": 150,
    "finalize_user_profile": 120,
    "finalize_knowledge_graph": 120,
}

# ══════════════════════════════════════════════════════════
# 步骤/会话状态常量
# ══════════════════════════════════════════════════════════

STEP_STATUS = {
    "PENDING": "pending",
    "QUEUED": "queued",
    "RUNNING": "running",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "SKIPPED": "skipped",
    "PENDING_RETRY": "pending_retry",
}

CONV_STATUS = {
    "ACTIVE": "active",
    "COMPLETED": "completed",
    "FAILED": "failed",
    "PAUSED": "paused",
}

# ══════════════════════════════════════════════════════════
# 表名
# ══════════════════════════════════════════════════════════

TABLE_CONVERSATIONS = "conversations"
TABLE_CONVERSATION_STEPS = "conversation_steps"
TABLE_TASK_QUEUE = "task_queue"
TABLE_CONNECTED_SYSTEMS = "connected_systems"
TABLE_SYSTEM_CONTEXT_FRAGMENTS = "system_context_fragments"
TABLE_USER_PROFILE = "user_profile"
TABLE_USER_SKILLS = "user_skills"
TABLE_KNOWLEDGE_POINTS = "knowledge_points"
TABLE_IMPROVEMENT_LOG = "improvement_log"

# ══════════════════════════════════════════════════════════
# 默认值
# ══════════════════════════════════════════════════════════

DEFAULT_SYSTEM_ID = "default"
DEFAULT_CLIENT = "codebuddy"
DEFAULT_TASK_TYPE = "general"
DEFAULT_STEP_TYPE = "general"
DEFAULT_CONFIDENCE = 0.7
DEFAULT_PROFILE_CONFIDENCE = 0.75
DEFAULT_SKILL_CONFIDENCE = 0.5
DEFAULT_SKILL_LEVEL = "intermediate"
DEFAULT_HOURS_SPENT = 0.5

# ══════════════════════════════════════════════════════════
# 系统限制
# ══════════════════════════════════════════════════════════

MAX_CONCURRENCY = 3
MAX_MEMORY_MB = 2048
MAX_RETRIES = 3
RETRY_SCHEDULER_INTERVAL = 300

# ══════════════════════════════════════════════════════════
# 步骤默认参数
# ══════════════════════════════════════════════════════════

STEP_DEFAULT_MAX_RETRIES = 3
STEP_DEFAULT_PRIORITY = 5

# ══════════════════════════════════════════════════════════
# Finalize 子任务类型列表
# ══════════════════════════════════════════════════════════

FINALIZE_SUB_TASK_TYPES = [
    "finalize_business_tech",
    "finalize_user_profile",
    "finalize_knowledge_graph",
]

# ══════════════════════════════════════════════════════════
# User Profile 维度映射
# ══════════════════════════════════════════════════════════

USER_PROFILE_DIMENSION_MAP = {
    "communication_style": "communication_style",
    "decision_pattern": "decision_pattern",
    "emotional_state": "emotional_state",
    "behavior_notes": "behavior_notes",
    "psychological_notes": "psychological_notes",
    "learning_progress": "learning_progress",
    "skills_observed": "skills_observed",
    "strengths": "strengths",
    "mistakes": "mistakes",
    "tech_interests": "tech_interests",
    "areas_for_growth": "areas_for_growth",
}

# 需要 JSON 序列化的维度
USER_PROFILE_JSON_DIMENSIONS = {
    "skills_observed",
    "strengths",
    "mistakes",
    "tech_interests",
    "areas_for_growth",
}
