"""
对话引擎扩展类型定义 (v9.10.1)
==============================
dataclass 结构化入参/返回值，替换魔法字典。
"""

from dataclasses import asdict, dataclass, field
from typing import Any

# ══════════════════════════════════════════════════════════
# 会话元数据
# ══════════════════════════════════════════════════════════


@dataclass
class ConversationMeta:
    """创建会话时的元数据"""

    client: str = "codebuddy"
    topic: str = ""
    task_type: str = "general"
    user_intent: str = ""
    system_id: str = "default"
    user_raw_input: str = ""
    ai_analysis: str = ""


@dataclass
class ConversationRow:
    """conversations 表行数据"""

    conversation_id: str = ""
    topic: str = ""
    system_id: str = "default"
    client: str = "unknown"
    user_raw_input: str = ""
    self_reflection: str = ""
    ai_analysis: str = ""
    task_type: str = "general"
    status: str = "active"
    total_steps: int = 0
    completed_steps: int = 0
    analyzed: int = 0
    summary_generated: int = 0
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ConversationRow":
        return cls(**{k: row.get(k, "") for k in cls.__dataclass_fields__})


# ══════════════════════════════════════════════════════════
# 步骤相关
# ══════════════════════════════════════════════════════════


@dataclass
class StepInput:
    """record_step 的入参（替代 14 个独立参数）"""

    step_name: str
    step_type: str = "general"
    content: str = ""
    files_changed: str = ""
    symptom: str = ""
    root_cause: str = ""
    solution: str = ""
    knowledge_points: str = ""
    user_question: str = ""
    client_request_id: str = ""
    ai_reasoning: str = ""
    user_requirement: str = ""
    commands_executed: str = ""


@dataclass
class StepRecord:
    """conversation_steps 表行数据"""

    step_id: str = ""
    conversation_id: str = ""
    step_name: str = ""
    step_type: str = "general"
    step_order: int = 0
    status: str = "pending"
    input_data: dict = field(default_factory=dict)
    output_data: dict = field(default_factory=dict)
    error_message: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    priority: int = 5
    duration_ms: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "StepRecord":
        return cls(
            **{
                k: row.get(k, "")
                for k in cls.__dataclass_fields__
                if k not in ("input_data", "output_data")
            },
            input_data=row.get("input_data", {}),
            output_data=row.get("output_data", {}),
        )


# ══════════════════════════════════════════════════════════
# Finalize 相关
# ══════════════════════════════════════════════════════════


@dataclass
class FinalizeContext:
    """handle_conversation_finalize 构造的子任务共享上下文"""

    conversation_id: str
    topic: str = ""
    system_id: str = "default"
    client: str = "unknown"
    user_raw_input: str = ""
    project_context: str = ""
    summary: str = ""
    self_reflection: str = ""
    user_traits: dict = field(default_factory=dict)
    key_decisions: list = field(default_factory=list)
    steps_summary: list = field(default_factory=list)
    ai_analysis: str = ""
    ai_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskPayload:
    """任务队列 payload"""

    task_type: str
    conversation_id: str
    step_id: str = ""
    payload: dict = field(default_factory=dict)
    priority: int = 8
    estimated_memory_mb: int = 100


# ══════════════════════════════════════════════════════════
# 分析结果
# ══════════════════════════════════════════════════════════


@dataclass
class StepAnalysisResult:
    """步骤分析结果"""

    skill_domains: list = field(default_factory=list)
    llm_analyzed: bool = False
    step_summary: str = ""
    difficulty: str = "medium"
    problem_solving_pattern: dict = field(default_factory=dict)
    thinking_patterns: list = field(default_factory=list)
    commands_used: list = field(default_factory=list)
    complexity_level: str = "simple"
    key_insights: list = field(default_factory=list)
    improvement_suggestions: list = field(default_factory=list)
    related_tools: list = field(default_factory=list)
    llm_knowledge_points: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in asdict(self).items()
            if v not in ([], {}, 0, False, "") or k in ("llm_analyzed", "llm_knowledge_points")
        }


@dataclass
class FinalizeResult:
    """finalize 子任务结果"""

    conversation_id: str
    dimension: str = ""
    success: bool = False
    error: str | None = None
    sub_tasks_queued: int = 0
    sub_task_ids: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}
