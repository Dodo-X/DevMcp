"""全局统一日志框架（自动携带 trace/会话 ID）。

- log_config.setup_logging: 初始化根 logger
- log_format:               统一日志格式
- logger_proxy.get_logger:  获取带上下文的 logger
"""

from foundation.logger_framework.log_config import setup_logging
from foundation.logger_framework.logger_proxy import get_logger

__all__ = ["get_logger", "setup_logging"]
