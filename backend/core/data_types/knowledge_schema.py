"""知识点接口结构体（前后端契约）。"""

from dataclasses import dataclass


@dataclass
class KnowledgePoint:
    id: int | None = None
    title: str = ""
    domain: str = ""
    content: str = ""
    source_id: str = ""
