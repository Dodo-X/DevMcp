"""logger 代理：统一入口获取 logger。"""

import logging


def get_logger(name: str) -> logging.Logger:
    """获取模块 logger。后续可在此注入 trace_id 等上下文过滤器。"""
    return logging.getLogger(name)
