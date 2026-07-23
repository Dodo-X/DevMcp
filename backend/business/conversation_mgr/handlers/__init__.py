"""
任务处理器子包 (v9.10.1)
========================
独立的任务处理器，从 engine.py 和 finalize_handlers.py 拆出。

模块：
  - step_analysis: handle_step_analysis
  - conv_finalize: handle_conversation_finalize
  - finalize_business_tech: handle_finalize_business_tech
  - finalize_user_profile: handle_finalize_user_profile
  - finalize_knowledge_graph: handle_finalize_knowledge_graph
  - finalize_aggregator: _check_finalize_sub_tasks / _merge_skills / _cascade_check_daily_summary
  - misc_handlers: conversation_analysis / profile_update / knowledge_extraction / system_optimization
"""

from backend.business.conversation_mgr.handlers.conv_finalize import handle_conversation_finalize
from backend.business.conversation_mgr.handlers.finalize_business_tech import (
    handle_finalize_business_tech,
)
from backend.business.conversation_mgr.handlers.finalize_knowledge_graph import (
    handle_finalize_knowledge_graph,
)
from backend.business.conversation_mgr.handlers.finalize_user_profile import (
    handle_finalize_user_profile,
)
from backend.business.conversation_mgr.handlers.misc_handlers import (
    handle_conversation_analysis,
    handle_knowledge_extraction,
    handle_profile_update,
    handle_system_optimization,
)
from backend.business.conversation_mgr.handlers.step_analysis import handle_step_analysis

__all__ = [
    "handle_step_analysis",
    "handle_conversation_finalize",
    "handle_finalize_business_tech",
    "handle_finalize_user_profile",
    "handle_finalize_knowledge_graph",
    "handle_conversation_analysis",
    "handle_profile_update",
    "handle_knowledge_extraction",
    "handle_system_optimization",
]
