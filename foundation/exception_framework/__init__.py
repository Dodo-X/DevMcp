"""全局异常体系，自动转前端标准返回。

- base_exc.BizException: 业务异常基类（携带 error_code）
- error_render:          异常 -> StandardResponse 渲染
- global_catcher:        统一捕获装饰器
"""

from foundation.exception_framework.base_exc import BizException
from foundation.exception_framework.error_render import render_exception
from foundation.exception_framework.global_catcher import catch

__all__ = ["BizException", "render_exception", "catch"]
