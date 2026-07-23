"""文件通用工具。"""

import os


def read_text(path: str, default: str | None = None) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return default


def write_text(path: str, content: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False
