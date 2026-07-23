"""统一日志格式。"""

DEFAULT_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
TRACE_FORMAT = "[%(asctime)s] [%(levelname)s] [trace=%(trace_id)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
