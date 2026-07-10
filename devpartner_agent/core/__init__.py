"""DevPartner Agent Core - 核心基础设施
PONYTATIL: __init__.py 导出保留兼容，外部调用直接 from .xxx import。
"""

from .database import get_db, Database
from .rule_engine import get_engine, RuleEngine, Rule
from .evolution import get_evolution_engine, EvolutionEngine
from .identity import get_identity, IdentityManager, KNOWN_CLIENTS
from .config import get_config, AgentConfig, ConfigManager
from .capabilities import get_capability_manager, CapabilityManager, Capability, RiskLevel
from .tool_registry import get_tool_registry, ToolRegistry, ToolMeta, ToolSource, ToolScope
from .approval_chain import ApprovalChain, ApprovalRequest, ApprovalResult, ApprovalStatus, create_approval_request
