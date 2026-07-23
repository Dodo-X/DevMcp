"""
Finalize 子任务处理器 (v9.10.1)
==============================
向后兼容重导出。实际实现已迁移到 conversation/handlers/ 子包。

v9.10.1: 所有处理器从 conversation/handlers/ 重导出，消除重复代码。
"""

import logging

from backend.business.conversation_mgr.handlers.finalize_aggregator import (
    cascade_check_daily_summary as _cascade_check_daily_summary,
)
from backend.business.conversation_mgr.handlers.finalize_aggregator import (
    check_finalize_sub_tasks as _check_finalize_sub_tasks,
)
from backend.business.conversation_mgr.handlers.finalize_aggregator import (
    merge_skills_from_profile as _merge_skills_from_profile,
)
from backend.business.conversation_mgr.handlers.finalize_business_tech import (
    handle_finalize_business_tech,
)
from backend.business.conversation_mgr.handlers.finalize_knowledge_graph import (
    handle_finalize_knowledge_graph,
)
from backend.business.conversation_mgr.handlers.finalize_user_profile import (
    handle_finalize_user_profile,
)

logger = logging.getLogger(__name__)

__all__ = [
    "handle_finalize_business_tech",
    "handle_finalize_user_profile",
    "handle_finalize_knowledge_graph",
    "_check_finalize_sub_tasks",
    "_merge_skills_from_profile",
    "_cascade_check_daily_summary",
]
