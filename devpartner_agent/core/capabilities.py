"""
按能力授权引擎 - Capability-based Security

借鉴 Goose 的 Capability-based Security 模式：
- 按能力（而非工具名）授权
- 支持"允许文件读写但不允许网络访问"等细粒度控制
- 危险操作需要审批，可配置自动批准策略
"""

from datetime import datetime
from enum import Enum
from typing import Dict, Set, List, Any
from dataclasses import dataclass, field


class Capability(Enum):
    """能力枚举"""
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"  
    FILE_DELETE = "file_delete"
    GIT_READ = "git_read"
    GIT_WRITE = "git_write"
    NETWORK = "network"
    SYSTEM_EXEC = "system_exec"
    DATABASE = "database"
    EVOLUTION = "evolution"
    CONFIG = "config"
    ADMIN = "admin"


class RiskLevel(Enum):
    """风险等级"""
    SAFE = "safe"           # 只读操作，无需审批
    LOW = "low"            # 低风险，可自动批准
    MEDIUM = "medium"      # 中风险，需要日志记录
    HIGH = "high"          # 高风险，需要审批
    CRITICAL = "critical"  # 关键操作，必须人工确认


@dataclass
class CapabilityProfile:
    """能力配置档案"""
    name: str
    description: str
    risk_level: RiskLevel
    requires_approval: bool
    auto_approve_conditions: List[str] = field(default_factory=list)


@dataclass  
class ApprovalResult:
    """审批结果"""
    approved: bool
    reason: str
    approver: str  # "auto" | "ai" | "user" | "system" | "pending"
    timestamp: str = ""
    approval_required: bool = False  # 是否需要调用方向用户发起二次确认
    approval_prompt: str = ""  # 给调用方的审批提示文案


# 能力配置表
CAPABILITY_PROFILES: Dict[Capability, CapabilityProfile] = {
    Capability.FILE_READ: CapabilityProfile(
        name="文件读取",
        description="读取文件内容、列出目录、搜索文件",
        risk_level=RiskLevel.SAFE,
        requires_approval=False,
    ),
    Capability.FILE_WRITE: CapabilityProfile(
        name="文件写入",
        description="写入/修改文件内容",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        auto_approve_conditions=["文件大小 < 1MB", "非系统目录"],
    ),
    Capability.FILE_DELETE: CapabilityProfile(
        name="文件删除",
        description="删除文件或目录",
        risk_level=RiskLevel.HIGH,
        requires_approval=True,
    ),
    Capability.GIT_READ: CapabilityProfile(
        name="Git 读取",
        description="查看 Git 状态、日志、差异",
        risk_level=RiskLevel.SAFE,
        requires_approval=False,
    ),
    Capability.GIT_WRITE: CapabilityProfile(
        name="Git 写入",
        description="提交、推送、创建分支",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
    ),
    Capability.NETWORK: CapabilityProfile(
        name="网络请求",
        description="HTTP 请求、API 调用",
        risk_level=RiskLevel.LOW,
        requires_approval=False,
        auto_approve_conditions=["仅限 GET 请求", "非内网地址"],
    ),
    Capability.SYSTEM_EXEC: CapabilityProfile(
        name="系统命令",
        description="执行 Shell/PowerShell 命令",
        risk_level=RiskLevel.CRITICAL,
        requires_approval=True,
    ),
    Capability.DATABASE: CapabilityProfile(
        name="数据库操作",
        description="SQL 查询、数据修改",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=False,
        auto_approve_conditions=["仅 SELECT 查询"],
    ),
    Capability.EVOLUTION: CapabilityProfile(
        name="自我进化",
        description="修改自身代码、热重载",
        risk_level=RiskLevel.HIGH,
        requires_approval=True,
    ),
    Capability.CONFIG: CapabilityProfile(
        name="配置修改",
        description="修改系统配置文件",
        risk_level=RiskLevel.MEDIUM,
        requires_approval=True,
    ),
    Capability.ADMIN: CapabilityProfile(
        name="管理操作",
        description="系统级管理操作",
        risk_level=RiskLevel.CRITICAL,
        requires_approval=True,
    ),
}


# 工具到能力的映射表
TOOL_CAPABILITY_MAP: Dict[str, Set[Capability]] = {
    # 文件系统工具
    "read_file": {Capability.FILE_READ},
    "write_file": {Capability.FILE_WRITE},
    "list_directory": {Capability.FILE_READ},
    "search_files": {Capability.FILE_READ},
    "search_content": {Capability.FILE_READ},
    
    # Git 工具
    "git_status": {Capability.GIT_READ},
    "git_log": {Capability.GIT_READ},
    "git_diff": {Capability.GIT_READ},
    
    # 网络工具
    "fetch_url": {Capability.NETWORK},
    "github_search_code": {Capability.NETWORK},
    "github_search_repositories": {Capability.NETWORK},
    "context7_search": {Capability.NETWORK},
    
    # 推理工具（纯计算，无风险）
    "sequential_think": set(),
    "generate_mindmap": set(),
    "generate_mindmap_from_tree": set(),
    "list_mindmaps": set(),
    
    # 系统工具
    "execute_system_command": {Capability.SYSTEM_EXEC},
    "detect_client": {Capability.FILE_READ},
    "environment_scan": {Capability.FILE_READ, Capability.SYSTEM_EXEC},
    "validate_path": {Capability.FILE_READ},
    
    # 发现工具（只读）
    "discover_mcp_servers": set(),
    "list_known_mcp_servers": set(),
    "test_mcp_server": {Capability.NETWORK},
    "get_rules_summary": set(),
    "generate_config_snippet": set(),
    
    # Agent 工具
    "log_conversation": {Capability.DATABASE, Capability.FILE_WRITE},
    "get_daily_summary": {Capability.DATABASE, Capability.FILE_READ},
    "send_agent_message": {Capability.FILE_WRITE},
    "check_agent_messages": {Capability.FILE_READ},
    "self_iterate": {Capability.EVOLUTION, Capability.DATABASE, Capability.FILE_READ},
    "self_upgrade": {Capability.EVOLUTION, Capability.FILE_WRITE},
    "self_create_file": {Capability.EVOLUTION, Capability.FILE_WRITE},
    "get_rules": {Capability.FILE_READ},
    "trigger_rule": {Capability.CONFIG},
    "query_database": {Capability.DATABASE},
    "optimize_prompt": set(),
    "cleanup_old_data": {Capability.DATABASE, Capability.FILE_DELETE, Capability.ADMIN},
}


class CapabilityManager:
    """能力管理器"""

    def __init__(self):
        self._disabled_capabilities: Set[Capability] = set()
        self._approval_history: List[dict] = []
        self._auto_approve_enabled: Dict[Capability, bool] = {}
    
    def disable_capability(self, capability: Capability) -> None:
        """禁用某个能力"""
        self._disabled_capabilities.add(capability)
    
    def enable_capability(self, capability: Capability) -> None:
        """启用某个能力"""
        self._disabled_capabilities.discard(capability)
    
    def set_auto_approve(self, capability: Capability, enabled: bool) -> None:
        """设置自动批准"""
        self._auto_approve_enabled[capability] = enabled
    
    def get_tool_capabilities(self, tool_name: str) -> Set[Capability]:
        """获取工具所需的能力"""
        return TOOL_CAPABILITY_MAP.get(tool_name, set())
    
    def get_risk_level(self, tool_name: str) -> RiskLevel:
        """获取工具的风险等级"""
        caps = self.get_tool_capabilities(tool_name)
        if not caps:
            return RiskLevel.SAFE
        
        max_level = RiskLevel.SAFE
        for cap in caps:
            profile = CAPABILITY_PROFILES.get(cap)
            if profile:
                risk_order = list(RiskLevel)
                if risk_order.index(profile.risk_level) > risk_order.index(max_level):
                    max_level = profile.risk_level
        return max_level
    
    def check_authorization(self, tool_name: str,
                            dry_run: bool = False) -> ApprovalResult:
        """
        检查工具是否被授权
        
        Args:
            tool_name: 工具名称
            dry_run: 是否为试运行模式
        
        Returns:
            ApprovalResult: 审批结果
        """
        
        caps = self.get_tool_capabilities(tool_name)
        timestamp = datetime.now().isoformat()
        
        # 无风险工具直接通过
        if not caps:
            result = ApprovalResult(
                approved=True, 
                reason=f"工具 '{tool_name}' 无风险能力要求",
                approver="auto",
                timestamp=timestamp
            )
            self._approval_history.append(result.to_dict() if hasattr(result, 'to_dict') else {
                "approved": result.approved, "reason": result.reason, "approver": result.approver, "timestamp": result.timestamp
            })
            return result
        
        # 检查是否有禁用的能力
        disabled = caps & self._disabled_capabilities
        if disabled:
            names = ", ".join(c.value for c in disabled)
            result = ApprovalResult(
                approved=False,
                reason=f"以下能力已被禁用: {names}",
                approver="system",
                timestamp=timestamp
            )
            self._approval_history.append({
                "approved": result.approved, "reason": result.reason, "approver": result.approver, "timestamp": result.timestamp
            })
            return result
        
        # 获取最高风险等级
        risk_level = self.get_risk_level(tool_name)
        
        # SAFE 级别自动通过
        if risk_level == RiskLevel.SAFE:
            result = ApprovalResult(
                approved=True,
                reason=f"工具 '{tool_name}' 风险等级为 SAFE，自动通过",
                approver="auto",
                timestamp=timestamp
            )
            self._approval_history.append({
                "approved": result.approved, "reason": result.reason, "approver": result.approver, "timestamp": result.timestamp
            })
            return result
        
        # 检查是否需要审批
        needs_approval = any(
            CAPABILITY_PROFILES[c].requires_approval 
            for c in caps if c in CAPABILITY_PROFILES
        )
        
        if needs_approval and not dry_run:
            # 检查是否设置了自动批准
            auto_approved = all(
                self._auto_approve_enabled.get(c, False)
                for c in caps if CAPABILITY_PROFILES.get(c, CapabilityProfile("", "", RiskLevel.SAFE, False)).requires_approval
            )
            
            if auto_approved:
                result = ApprovalResult(
                    approved=True,
                    reason=f"工具 '{tool_name}' 已设为自动批准",
                    approver="auto",
                    timestamp=timestamp,
                    approval_required=False
                )
            else:
                caps_info = [
                    {
                        "capability": c.value,
                        "risk": CAPABILITY_PROFILES[c].risk_level.value if c in CAPABILITY_PROFILES else "unknown",
                        "description": CAPABILITY_PROFILES[c].description if c in CAPABILITY_PROFILES else "",
                    }
                    for c in caps if c in CAPABILITY_PROFILES
                ]
                prompt = (
                    f"⚠️ 工具 '{tool_name}' 需要审批\n"
                    f"风险等级: {risk_level.value}\n"
                    f"涉及能力: {', '.join(c['capability'] for c in caps_info)}\n"
                    f"说明: {'; '.join(c['description'] for c in caps_info)}\n"
                    f"是否允许执行此操作？"
                )
                result = ApprovalResult(
                    approved=False,
                    reason=f"工具 '{tool_name}' 需要审批（风险等级: {risk_level.value}）",
                    approver="pending",
                    timestamp=timestamp,
                    approval_required=True,
                    approval_prompt=prompt
                )
        else:
            result = ApprovalResult(
                approved=True,
                reason=f"工具 '{tool_name}' 风险等级 {risk_level.value}，已通过" + (" (dry-run)" if dry_run else ""),
                approver="auto",
                timestamp=timestamp
            )
        
        self._approval_history.append({
            "approved": result.approved, "reason": result.reason, "approver": result.approver, "timestamp": result.timestamp
        })
        
        return result
    
    def get_approval_history(self, limit: int = 20) -> List[dict]:
        """获取审批历史"""
        return self._approval_history[-limit:]
    
    def get_status_report(self) -> Dict[str, Any]:
        """获取能力状态报告"""
        return {
            "disabled_capabilities": [c.value for c in self._disabled_capabilities],
            "auto_approve_enabled": {c.value: v for c, v in self._auto_approve_enabled.items()},
            "total_tools_mapped": len(TOOL_CAPABILITY_MAP),
            "recent_approvals": self._approval_history[-5:],
        }


def get_capability_manager() -> CapabilityManager:
    """获取能力管理器实例"""
    return CapabilityManager()
# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
