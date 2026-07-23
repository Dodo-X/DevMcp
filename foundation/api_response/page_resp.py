"""PageResponse —— 分页统一封装。"""

from dataclasses import dataclass
from typing import Any


@dataclass
class PageResponse:
    """分页数据载荷，作为 StandardResponse.data 使用。"""

    items: list[Any]
    total: int
    page: int = 1
    page_size: int = 20

    @property
    def total_pages(self) -> int:
        if self.page_size <= 0:
            return 0
        return (self.total + self.page_size - 1) // self.page_size

    def to_dict(self) -> dict:
        return {
            "items": self.items,
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }
