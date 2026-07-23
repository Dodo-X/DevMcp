"""
DevPartner 统一启动入口
=======================
用法:
  python main.py 7860        # 启动 MCP 服务（默认端口 7860，复用 backend 底层能力）

分层架构:
  foundation/    全局基础框架（配置 / 日志 / 埋点 / 异常 / 通用工具 / 统一返回体）
  backend/       后端 core 底层能力 + business 业务 + api_gateway 网关 + templates 模板
  mcp_service/   MCP 工具模块（start_conversation / record_step / finalize_conversation）
  frontend/      前端（预留，前后端分离）

说明:
  MCP 通过注解暴露工具，仅被 MCP 客户端调用，与 Web 网关互不冲突，
  两者共用 foundation / backend/core / backend/business 底层。
"""

import os
import runpy
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


if __name__ == "__main__":
    # 复用 mcp_service.mcp_server 的启动逻辑（保持 sys.argv 传递端口参数）
    runpy.run_module("mcp_service.mcp_server", run_name="__main__", alter_sys=True)
