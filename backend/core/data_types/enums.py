"""
核心类型定义 (v9.10.0)
======================
v9.10.0: 从 conversation_engine.py 提取公共枚举类型，作为项目级类型定义。
"""

from enum import Enum


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StepStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepType(str, Enum):
    ANALYSIS = "analysis"
    KNOWLEDGE_GEN = "knowledge_gen"
    USER_PROFILE = "user_profile"
    SYSTEM_OPTIMIZE = "system_optimize"
