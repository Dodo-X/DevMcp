"""会话接口入参/出参结构体（前后端契约）。

采用标准库 dataclass，避免引入额外依赖；如需严格校验可后续切换 Pydantic。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StartConversationReq:
    client: str = "unknown"
    topic: str = ""
    task_type: str = "general"
    user_intent: str = ""
    system_id: str = "default"
    user_raw_input: str = ""
    ai_analysis: str = ""


@dataclass
class RecordStepReq:
    conversation_id: str
    step_name: str
    step_type: str = "general"
    content: str = ""
    ai_reasoning: str = ""
    commands_executed: str = ""
    files_changed: str = ""


@dataclass
class ConversationResp:
    conversation_id: str
    status: str = "active"
    steps: list[dict[str, Any]] = field(default_factory=list)
    summary: str | None = None
