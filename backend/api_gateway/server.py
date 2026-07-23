"""API 网关聚合入口。

当前后端以 FastMCP 的底层 Starlette 应用承载 HTTP 路由（见 rest_api.py），
MCP 工具与 Web/REST 路由共用同一进程与底层 backend 能力。

register_gateway(mcp)：把 REST 路由注册到 MCP/Starlette 实例。
后续若引入独立 FastAPI 实例，可在此聚合 routes/ 下的路由与 middlewares/。
"""

from backend.api_gateway.rest_api import register_rest_routes


def register_gateway(app) -> None:
    """把所有网关路由注册到应用实例（MCP/Starlette/FastAPI）。"""
    register_rest_routes(app)


__all__ = ["register_gateway", "register_rest_routes"]
