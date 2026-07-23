"""前端请求全局中间件（预留）。

规划：
  - cors_middleware:     跨域放行前端域名
  - auth_middleware:     Token 鉴权，解析工作空间
  - trace_middleware:    读取前端 X-Trace-Id 注入 foundation.trace_tracker 上下文
  - limiter_middleware:  限流
  - exception_middleware:全局异常拦截，统一返回标准 JSON（foundation.exception_framework）

当前 MCP/Starlette 侧的 CORS 已在 mcp_service.mcp_server 中配置。
"""
