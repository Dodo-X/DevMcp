"""代码块耗时埋点装饰器。"""

import functools
import time

from foundation.logger_framework.logger_proxy import get_logger

logger = get_logger("trace.span")


def span(name: str = ""):
    """装饰器：记录被装饰函数的耗时（毫秒）。"""

    def deco(fn):
        label = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                cost_ms = (time.perf_counter() - t0) * 1000
                logger.debug("[span] %s cost=%.1fms", label, cost_ms)

        return wrapper

    return deco
