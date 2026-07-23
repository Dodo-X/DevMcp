"""统一异常捕获装饰器。"""

import functools

from foundation.exception_framework.error_render import render_exception
from foundation.logger_framework.logger_proxy import get_logger

logger = get_logger("exc.catcher")


def catch(fn):
    """装饰同步函数：异常时记录并返回标准失败返回体。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            logger.exception("[catch] %s 异常: %s", fn.__name__, e)
            return render_exception(e)

    return wrapper
