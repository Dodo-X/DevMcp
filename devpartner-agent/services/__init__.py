"""DevPartner Agent Services - 业务服务层

包含：
- log_service: 日志服务（对话记录+分析）
- dialogue_service: 跨AI对话服务
- discovery_service: 服务发现
- ai_optimizer: AI优化器
"""

from .log_service import get_log_service, LogService
from .dialogue_service import get_dialogue, DialogueService
from .discovery_service import get_discovery, DiscoveryService
from .ai_optimizer import get_optimizer, AIOptimizer

__all__ = [
    'get_log_service', 'LogService',
    'get_dialogue', 'DialogueService',
    'get_discovery', 'DiscoveryService',
    'get_optimizer', 'AIOptimizer',
]
