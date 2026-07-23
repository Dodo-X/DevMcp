"""业务异常基类。"""

from foundation.config.error_code import ErrorCode


class BizException(Exception):
    """业务异常：携带统一 error_code，可直接渲染为标准返回。"""

    def __init__(self, message: str = "业务异常", code: int = ErrorCode.INTERNAL_ERROR, data=None):
        super().__init__(message)
        self.code = int(code)
        self.message = message
        self.data = data
