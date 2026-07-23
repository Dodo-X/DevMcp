"""前后端统一返回体契约（核心对接规范）。

- base_resp.StandardResponse: 标准结构 { code, message, data, trace_id }
- page_resp.PageResponse:     分页统一封装
- resp_factory:               快捷生成成功/失败返回
"""

from foundation.api_response.base_resp import StandardResponse
from foundation.api_response.page_resp import PageResponse
from foundation.api_response.resp_factory import fail, ok, page

__all__ = ["StandardResponse", "PageResponse", "ok", "fail", "page"]
