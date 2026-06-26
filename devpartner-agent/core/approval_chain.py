"""
审批链引擎 - Approval Chain

借鉴 Goose 的审批链模式：
- 支持多级审批（自动审批→AI审批→用户审批）
- 审批策略可配置
- 审批历史可追溯
- 支持 dry-run 预览模式

审批链流程：
    操作请求 → 风险评级 → 自动审批规则 → AI审批 → 用户审批 → 执行/拒绝
"""

import json
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


class ApprovalStatus(Enum):
    """审批状态"""
    PENDING = "pending"
    AUTO_APPROVED = "auto_approved"
    AI_APPROVED = "ai_approved"
    USER_APPROVED = "user_approved"
    REJECTED = "rejected"
    SKIPPED = "skipped"  # dry-run 模式


@dataclass
class ApprovalRequest:
    """审批请求"""
    operation: str
    description: str
    risk_level: str  # "safe" | "low" | "medium" | "high" | "critical"
    details: Dict[str, Any] = field(default_factory=dict)
    requested_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class ApprovalResult:
    """审批结果"""
    request: ApprovalRequest
    status: ApprovalStatus
    reason: str
    approved_by: str  # "auto" | "ai" | "user" | "system"
    approved_at: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)


class ApprovalChain:
    """
    审批链
    
    审批流程：
    1. 自动审批规则检查（安全操作直接通过）
    2. AI 审批（中等风险，AI 判断是否合理）
    3. 用户审批（高风险操作，必须人工确认）
    """
    
    # 自动审批规则：这些操作模式自动通过
    AUTO_APPROVE_PATTERNS = [
        "只读",
        "查询",
        "搜索",
        "列表",
        "统计",
        "分析",
        "预览",
        "dry.run",
        "dry_run",
        "检查",
        "检测",
        "验证",
        "获取",
        "读取",
        "查看",
        "显示",
        "汇总",
        "报告",
    ]
    
    # 需要用户审批的操作模式
    REQUIRE_USER_APPROVAL = [
        "删除",
        "destroy",
        "drop",
        "truncate",
        "格式化",
        "format",
        "清空",
        "重装",
        "卸载",
        "卸载",
    ]
    
    def __init__(self, 
                 auto_approve_enabled: bool = True,
                 ai_approve_enabled: bool = False,
                 user_approve_enabled: bool = True,
                 dry_run: bool = False):
        self._auto_approve_enabled = auto_approve_enabled
        self._ai_approve_enabled = ai_approve_enabled
        self._user_approve_enabled = user_approve_enabled
        self._dry_run = dry_run
        self._history: List[ApprovalResult] = []
        self._user_approval_callback: Optional[Callable] = None
    
    def set_user_approval_callback(self, callback: Callable) -> None:
        """设置用户审批回调（用于需要人工确认时）"""
        self._user_approval_callback = callback
    
    def set_dry_run(self, enabled: bool) -> None:
        """设置 dry-run 模式"""
        self._dry_run = enabled
    
    def process(self, request: ApprovalRequest) -> ApprovalResult:
        """
        处理审批请求
        
        返回审批结果，如果被拒绝则抛出异常的建议。
        """
        # Dry-run 模式：跳过所有实际操作
        if self._dry_run:
            result = ApprovalResult(
                request=request,
                status=ApprovalStatus.SKIPPED,
                reason=f"[DRY-RUN] 跳过操作: {request.operation}",
                approved_by="system",
                metadata={"dry_run": True, "would_execute": True}
            )
            self._history.append(result)
            return result
        
        # Step 1: 自动审批规则
        if self._auto_approve_enabled:
            auto_result = self._check_auto_approve(request)
            if auto_result:
                self._history.append(auto_result)
                return auto_result
        
        # Step 2: AI 审批（中等风险）
        if self._ai_approve_enabled and request.risk_level in ("medium", "low"):
            ai_result = self._check_ai_approve(request)
            if ai_result and ai_result.status == ApprovalStatus.AI_APPROVED:
                self._history.append(ai_result)
                return ai_result
        
        # Step 3: 用户审批（高风险或 AI 无法判断）
        if self._user_approve_enabled:
            user_result = self._check_user_approve(request)
            if user_result:
                self._history.append(user_result)
                return user_result
        
        # 默认拒绝
        result = ApprovalResult(
            request=request,
            status=ApprovalStatus.REJECTED,
            reason=f"操作 '{request.operation}' 未通过审批链",
            approved_by="system",
        )
        self._history.append(result)
        return result
    
    def _check_auto_approve(self, request: ApprovalRequest) -> Optional[ApprovalResult]:
        """检查自动审批规则"""
        # 安全级别直接通过
        if request.risk_level == "safe":
            return ApprovalResult(
                request=request,
                status=ApprovalStatus.AUTO_APPROVED,
                reason="安全操作，自动通过",
                approved_by="auto",
            )
        
        # 检查操作描述是否匹配自动批准模式
        desc_lower = request.description.lower()
        operation_lower = request.operation.lower()
        
        for pattern in self.AUTO_APPROVE_PATTERNS:
            if pattern.lower().replace(".", "_") in desc_lower or pattern.lower().replace(".", "_") in operation_lower:
                return ApprovalResult(
                    request=request,
                    status=ApprovalStatus.AUTO_APPROVED,
                    reason=f"匹配自动批准规则: {pattern}",
                    approved_by="auto",
                )
        
        return None
    
    def _check_ai_approve(self, request: ApprovalRequest) -> Optional[ApprovalResult]:
        """AI 审批检查（预留接口）"""
        # 如果 AI 审批未启用或不可用，返回 None 让用户审批
        return None
    
    def _check_user_approve(self, request: ApprovalRequest) -> Optional[ApprovalResult]:
        """用户审批检查"""
        # 检查是否需要用户审批
        desc_lower = request.description.lower()
        for pattern in self.REQUIRE_USER_APPROVAL:
            if pattern.lower() in desc_lower:
                if self._user_approval_callback:
                    user_approved = self._user_approval_callback(request)
                    if user_approved:
                        return ApprovalResult(
                            request=request,
                            status=ApprovalStatus.USER_APPROVED,
                            reason="用户确认执行",
                            approved_by="user",
                        )
                    else:
                        return ApprovalResult(
                            request=request,
                            status=ApprovalStatus.REJECTED,
                            reason="用户拒绝执行",
                            approved_by="user",
                        )
        
        # 非高风险操作，默认通过
        if request.risk_level not in ("high", "critical"):
            return ApprovalResult(
                request=request,
                status=ApprovalStatus.AUTO_APPROVED,
                reason="非高风险操作，自动通过",
                approved_by="auto",
            )
        
        return None
    
    def get_history(self, limit: int = 20) -> List[ApprovalResult]:
        """获取审批历史"""
        return self._history[-limit:]
    
    def get_pending_approvals(self) -> List[ApprovalResult]:
        """获取待审批项"""
        return [r for r in self._history if r.status == ApprovalStatus.PENDING]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取审批摘要"""
        total = len(self._history)
        approved = len([r for r in self._history if r.status in (
            ApprovalStatus.AUTO_APPROVED, ApprovalStatus.AI_APPROVED, ApprovalStatus.USER_APPROVED
        )])
        rejected = len([r for r in self._history if r.status == ApprovalStatus.REJECTED])
        skipped = len([r for r in self._history if r.status == ApprovalStatus.SKIPPED])
        
        return {
            "total_requests": total,
            "approved": approved,
            "rejected": rejected,
            "skipped": skipped,
            "approval_rate": f"{approved / total * 100:.1f}%" if total > 0 else "N/A",
            "dry_run_mode": self._dry_run,
            "recent": [
                {
                    "operation": r.request.operation,
                    "status": r.status.value,
                    "reason": r.reason,
                    "risk": r.request.risk_level,
                }
                for r in self._history[-5:]
            ]
        }


def create_approval_request(operation: str, description: str, 
                             risk_level: str = "medium",
                             **details) -> ApprovalRequest:
    """创建审批请求的便捷方法"""
    return ApprovalRequest(
        operation=operation,
        description=description,
        risk_level=risk_level,
        details=details,
    )
