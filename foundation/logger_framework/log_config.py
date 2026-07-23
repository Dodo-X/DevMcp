"""日志初始化配置。"""

import logging

from foundation.logger_framework.log_format import DATE_FORMAT, DEFAULT_FORMAT

_configured = False


def setup_logging(level: str = "INFO") -> None:
    """初始化根 logger（幂等）。"""
    global _configured
    if _configured:
        return
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=DEFAULT_FORMAT,
        datefmt=DATE_FORMAT,
    )
    _configured = True
