"""DevPartner Agent Services - 业务服务层 (v6.0 精简版)

核心服务：
- conversation_analyzer: 对话分析引擎 v6.0 (LLM驱动)
- conversation_manager: 会话生命周期管理 (v5.0)
- llm_service: 本地 LLM 推理服务 (v4.4, llama-cpp-python)
- user_profile_service: 用户画像融合服务 v6.0 (LLM驱动)

辅助服务：
- log_service: 日志服务（对话记录+分析）
- dialogue_service: 跨AI对话服务
- task_queue: 异步任务队列 (v5.0)
- callback_registry: 回调注册表 (v5.2)
- file_watcher: 文件监控服务 (v2.4.0)
- optimization_loop: 优化闭环引擎 (v2.4.0)
- auto_analyzer: 自动分析引擎 (v4.1)

已移除（v6.0清理）:
❌ discovery_service - 功能整合到MCP工具层
❌ ai_optimizer - 功能整合到 LLMUnifiedAnalyzer
❌ conversation_analyzer_v2 - 废弃的实验版本
"""

from .log_service import get_log_service, LogService
from .dialogue_service import get_dialogue, DialogueService
from .conversation_analyzer import get_analyzer, ConversationAnalyzer
from .conversation_manager import get_conversation_manager, ConversationManager
from .task_queue import get_task_queue, TaskQueue
from .callback_registry import get_callback_registry, CallbackRegistry
from .knowledge_graph import get_knowledge_graph, KnowledgeGraph
from .file_watcher import get_watcher, FileWatcher
from .optimization_loop import get_optimization_loop, OptimizationLoop
from .auto_analyzer import analyze_pending_conversations, analyze_single_conversation
from .llm_service import LLMService
from .user_profile_service import apply_user_traits

__all__ = [
    'get_log_service', 'LogService',
    'get_dialogue', 'DialogueService',
    'get_analyzer', 'ConversationAnalyzer',
    'get_conversation_manager', 'ConversationManager',
    'get_task_queue', 'TaskQueue',
    'get_callback_registry', 'CallbackRegistry',
    'get_knowledge_graph', 'KnowledgeGraph',
    'get_watcher', 'FileWatcher',
    'get_optimization_loop', 'OptimizationLoop',
    'analyze_pending_conversations', 'analyze_single_conversation',
    'LLMService',
    'apply_user_traits',
]