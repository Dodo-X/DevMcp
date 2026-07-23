"""全局枚举再导出。

领域枚举（会话/步骤状态与类型）定义在 backend.core.data_types.enums，
此处统一再导出，便于前后端从 foundation 层引用。
"""

try:
    from backend.core.data_types.enums import (  # noqa: F401
        ConversationStatus,
        StepStatus,
        StepType,
    )
except Exception:  # pragma: no cover - 领域层不可用时保持 foundation 可导入
    ConversationStatus = StepStatus = StepType = None

__all__ = ["ConversationStatus", "StepStatus", "StepType"]
