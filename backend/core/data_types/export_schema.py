"""MD 导出接口结构体（前后端契约）。"""

from dataclasses import dataclass


@dataclass
class ExportResult:
    ok: bool = False
    file_path: str = ""
    message: str = ""
