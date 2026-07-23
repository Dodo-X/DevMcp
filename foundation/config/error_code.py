"""统一业务错误码（前后端共用一套）。"""

from enum import IntEnum


class ErrorCode(IntEnum):
    SUCCESS = 0

    # 通用（1xxx）
    INTERNAL_ERROR = 1000
    INVALID_PARAM = 1001
    NOT_FOUND = 1002
    UNAUTHORIZED = 1003
    FORBIDDEN = 1004
    RATE_LIMITED = 1005

    # 对话/任务（2xxx）
    CONVERSATION_NOT_FOUND = 2001
    STEP_INVALID = 2002
    TASK_ENQUEUE_FAILED = 2003

    # LLM（3xxx）
    LLM_UNAVAILABLE = 3001
    LLM_TIMEOUT = 3002

    # 数据/DB（4xxx）
    DB_ERROR = 4001
    DB_LOCKED = 4002
