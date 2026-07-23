"""文件通用工具。"""

import logging
import os

logger = logging.getLogger(__name__)


def read_text(path: str, default: str | None = None) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        logger.warning("read_text: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return default


def write_text(path: str, content: str) -> bool:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        logger.warning("write_text: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return False
