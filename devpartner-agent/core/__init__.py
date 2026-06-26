"""DevPartner Agent Core - 核心基础设施

包含：
- rule_engine: 规则引擎（自动触发+执行）
- evolution: 进化引擎（代码自更新+热重载）
- identity: 身份管理（多客户端配置）
- database: 数据存储（SQLite+共享数据库）
- capabilities: 按能力授权引擎（Capability-based Security）
- tool_registry: 统一工具注册表（Tool Registry 模式）
- approval_chain: 审批链引擎（借鉴 Goose）
"""

from .database import get_db, Database
from .rule_engine import get_rule_engine, RuleEngine
from .evolution import get_evolution_engine, EvolutionEngine
from .identity import get_identity, IdentityManager
from .capabilities import get_capability_manager, CapabilityManager, Capability, RiskLevel, require_capability
from .tool_registry import get_tool_registry, ToolRegistry, ToolMeta, ToolSource, ToolScope, deprecated_tool
from .approval_chain import ApprovalChain, ApprovalRequest, ApprovalResult, ApprovalStatus, create_approval_request

__all__ = [
    'get_db', 'Database',
    'get_rule_engine', 'RuleEngine',
    'get_evolution_engine', 'EvolutionEngine',
    'get_identity', 'IdentityManager',
    'get_capability_manager', 'CapabilityManager', 'Capability', 'RiskLevel', 'require_capability',
    'get_tool_registry', 'ToolRegistry', 'ToolMeta', 'ToolSource', 'ToolScope', 'deprecated_tool',
    'ApprovalChain', 'ApprovalRequest', 'ApprovalResult', 'ApprovalStatus', 'create_approval_request',
]
