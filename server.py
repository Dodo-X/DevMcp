"""
DevPartner MCP 服务器 v8.3
==========================

🎯 项目定位:
  以 MCP (Model Context Protocol) 形式对外提供服务的智能助手系统。

📦 系统架构 (v8.3 清理自迭代子系统后):
  server.py (薄壳 MCP 入口, ~200行)
  ├── devpartner_tools/     工具层 (13个纯工具, 无状态)
  │
  └── devpartner_agent/     智能管家层 (智能工具, 有状态)
      ├── core/             核心引擎层 (5个领域引擎 + 公共组件)
      │   ├── conversation_engine.py    对话引擎
      │   ├── knowledge_engine.py       知识引擎
      │   ├── system_engine.py          系统引擎
      │   ├── daily_engine.py           日报引擎
      │   ├── optimization_engine.py    优化引擎
      │   ├── llm_engine.py             LLM 推理引擎
      │   ├── bootstrap.py              启动与初始化
      │   └── decorators.py             统一装饰器
      │
      ├── routes/            HTTP 路由层
      │   └── rest_api.py    REST API 端点
      │
      └── services/          无状态服务层 (task_queue, vault_exporter 等)

🔄 协议:
  ✅ Streamable HTTP + /mcp 端点

📍 访问地址:
  本地开发:  http://127.0.0.1:7860/mcp
  云端部署:  https://modelscope.cn/studios/Pisces43/Dev-partner/mcp

作者：DevPartner Team
版本：8.0 | 更新: 2026-07-14
"""

import sys
import json
from pathlib import Path

_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
import os as _os
import logging

from devpartner_agent.core.config import get_project_version

VERSION = get_project_version()

_diag_logger = logging.getLogger("devpartner.diag")
_diag_logger.setLevel(logging.INFO)

DEFAULT_PORT = 7860
ALLOWED_PORTS = {7860, 8000, 8080, 3000}

mcp = FastMCP(
    "devpartner",
    instructions="DevPartner v8.0 - 智能开发助手",
)

_tools_count = 0


def _register_tool_layer():
    """注册工具层的所有纯工具到 MCP"""
    global _tools_count

    try:
        from devpartner_tools.tools.filesystem import register_filesystem_tools
        register_filesystem_tools(mcp)
        _tools_count += 6
    except Exception:
        pass

    try:
        from devpartner_tools.tools.web_requests import register_web_request_tools
        register_web_request_tools(mcp)
        _tools_count += 3
    except Exception:
        pass

    try:
        from devpartner_tools.tools.system_utils import register_system_tools
        register_system_tools(mcp)
        _tools_count += 4
    except Exception:
        pass

    try:
        from devpartner_tools.tools.growth_analytics import register_growth_analytics_tools
        register_growth_analytics_tools(mcp)
        _tools_count += 10
    except Exception:
        pass


def _register_agent_engines():
    """注册智能管家层的所有领域引擎到 MCP"""
    global _tools_count

    engines = [
        ("conversation", "devpartner_agent.core.conversation_engine"),
        ("knowledge", "devpartner_agent.core.knowledge_engine"),
        ("system", "devpartner_agent.core.system_engine"),
        ("daily", "devpartner_agent.core.daily_engine"),
        ("optimization", "devpartner_agent.core.optimization_engine"),
    ]

    for name, module in engines:
        try:
            mod = __import__(module, fromlist=[f"register_{name}_tools"])
            func = getattr(mod, f"register_{name}_tools")
            func(mcp)
            _tools_count += 10
        except Exception as e:
            print(f"[WARN] 注册 {name} 引擎失败: {e}")


def _register_rest_routes():
    """注册 HTTP REST 路由"""
    try:
        from devpartner_agent.routes.rest_api import register_rest_routes
        register_rest_routes(mcp)
    except Exception as e:
        print(f"[WARN] 注册 REST 路由失败: {e}")


def _register_task_handlers():
    """注册各模块的任务处理器到 task_queue（v8.1 全模块 handler 注册）"""
    try:
        from devpartner_agent.core.conversation_engine import register_task_handlers
        register_task_handlers()
    except Exception as e:
        print(f"[WARN] 注册对话任务处理器失败: {e}")

    try:
        from devpartner_agent.services.vault_exporter import register_task_handlers as register_vault
        register_vault()
    except Exception as e:
        print(f"[WARN] 注册 Vault 导出任务处理器失败: {e}")

    try:
        from devpartner_agent.services.cleanup_service import register_task_handlers as register_cleanup
        register_cleanup()
    except Exception as e:
        print(f"[WARN] 注册清理任务处理器失败: {e}")

    try:
        from devpartner_agent.services.optimization_loop import register_task_handlers as register_optimization
        register_optimization()
    except Exception as e:
        print(f"[WARN] 注册优化任务处理器失败: {e}")

    try:
        from devpartner_agent.core.daily_engine import register_task_handlers as register_daily
        register_daily()
    except Exception as e:
        print(f"[WARN] 注册日报任务处理器失败: {e}")


@mcp.tool()
def start_conversation(client: str = "unknown", topic: str = "",
                       task_type: str = "general", user_intent: str = "",
                       priority: str = "medium",
                       system_id: str = "default",
                       user_raw_input: str = "") -> str:
    """【总分总·总】开始一次新对话，创建会话并获取唯一 conversation_id。v8.0: 支持 system_id 多系统隔离"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()
        result = engine.start_conversation(
            client=client, topic=topic, task_type=task_type,
            user_intent=user_intent, priority=priority,
            system_id=system_id, user_raw_input=user_raw_input,
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


@mcp.tool()
def record_step(conversation_id: str = "", step_number: int = 0,
                step_name: str = "", step_type: str = "",
                step_input: str = "{}") -> str:
    """【总分总·分】记录对话步骤，支持幂等性检查和 LLM 语义扩展"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()

        if not conversation_id or not step_number or not step_name:
            return json.dumps({
                "error": "缺少必要参数: conversation_id, step_number, step_name",
                "success": False
            }, ensure_ascii=False)

        input_data = json.loads(step_input) if isinstance(step_input, str) else step_input
        if isinstance(input_data, dict):
            input_data.setdefault("client_request_id", f"{conversation_id}-{step_number}")
            step_input = json.dumps(input_data, ensure_ascii=False, default=str)

        result = engine.record_step(
            conversation_id=conversation_id,
            step_number=step_number,
            step_name=step_name,
            step_type=step_type,
            step_input=step_input,
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


@mcp.tool()
def finalize_conversation(conversation_id: str = "") -> str:
    """【总分总·总】结束一次对话，生成最终总结并归档"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()

        if not conversation_id:
            return json.dumps({"error": "需要 conversation_id 参数", "success": False}, ensure_ascii=False)

        result = engine.finalize_conversation(conversation_id=conversation_id)
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


@mcp.tool()
def question_with_context(question: str = "", context: str = "") -> str:
    """【总分总·分】基于上下文提问，自动检索知识库并使用 LLM 回答"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()

        if not question:
            return json.dumps({
                "error": "请输入问题内容",
                "success": False,
                "answer": None,
                "sources": []
            }, ensure_ascii=False)

        result = engine.question_with_context(
            question=question,
            context=context,
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({
            "error": str(e),
            "success": False,
            "answer": f"处理问题时发生错误: {str(e)}",
            "sources": []
        }, ensure_ascii=False)


if __name__ == "__main__":
    print("")
    print("=" * 60)
    print("  DevPartner v" + VERSION + " (Engine Pattern)")
    print("  架构: server.py(薄壳) → core/*_engine.py(业务)")
    print("=" * 60)
    print("")

    from devpartner_agent.core.bootstrap import apply_patches, ensure_ready

    apply_patches()

    from devpartner_agent.core.config import get_config
    _cfg = get_config()
    _os.environ.setdefault("OLLAMA_NUM_PARALLEL", str(_cfg.llm.ollama_num_parallel))

    _register_tool_layer()
    _register_agent_engines()
    _register_rest_routes()

    _register_task_handlers()

    agent_ok = ensure_ready()
    print("")
    print(f"  工具层: {_tools_count} 个工具已注册")
    print(f"  管家层: {'已加载' if agent_ok else '降级模式'}")
    print(f"  LLM并行: OLLAMA_NUM_PARALLEL={_os.environ.get('OLLAMA_NUM_PARALLEL', '1')}")
    print("")

    def _run_mcp_service(port):

        is_docker = _os.path.exists("/.dockerenv")
        is_modelscope = _os.environ.get("MODELSCOPE_ENVIRONMENT") == "true"

        if is_docker or is_modelscope:
            env_name = "ModelScope 云端" if is_modelscope else "Docker 容器"
            access_url = f"https://modelscope.cn/studios/Pisces43/Dev-partner/mcp"
        else:
            env_name = "本地开发"
            access_url = f"http://127.0.0.1:{port}/mcp"

        print("  启动模式: MCP 服务 (Streamable HTTP)")
        print(f"  运行环境: {env_name}")
        print(f"  监听端口: {port}")
        print(f"  MCP端点: {access_url}")
        print("")
        print("  [系统架构]")
        print("     [工具层] devpartner_tools: 21个纯工具 (无状态)")
        print("     [智能层] devpartner_agent/core/: 6个领域引擎 (有状态)")
        print("")
        print("  [可用功能]")
        print(f"     [MCP] POST {access_url}")
        print(f"     [仪表盘] http://localhost:{port}/dashboard")
        print(f"     [健康检查] http://localhost:{port}/health")
        print("")
        print("  待命状态: 等待 MCP 客户端连接...")
        print("=" * 60)

        from starlette.middleware import Middleware as _Middleware
        from starlette.middleware.cors import CORSMiddleware as _CORSMiddleware

        try:
            from mcp.server.streamable_http import StreamableHTTPServerTransport as _ST
            if not getattr(_ST._validate_accept_header, '_patched', False):
                async def _patched_validate(self, request, scope, send):
                    return True
                _ST._validate_accept_header = _patched_validate
                _ST._validate_accept_header._patched = True
                print("[INFO] Accept header 检查已禁用")
        except Exception as _e:
            print(f"[WARN] Accept header 补丁失败: {_e}")

        mcp.run(transport="streamable-http",
                 host="0.0.0.0",
                 port=port,
                 json_response=True,
                 stateless_http=True,
                 middleware=[_Middleware(
                     _CORSMiddleware,
                     allow_origins=["*"],
                     allow_credentials=True,
                     allow_methods=["*"],
                     allow_headers=["*"],
                     expose_headers=["Mcp-Session-Id"],
                 )])

    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg.isdigit():
            port = int(arg)
            if port not in ALLOWED_PORTS:
                print(f"[ERROR] 不允许的端口 {port}，仅支持: {sorted(ALLOWED_PORTS)}")
                sys.exit(1)
            _run_mcp_service(port)
        elif arg.lower() == "streamable":
            port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
            if port not in ALLOWED_PORTS:
                print(f"[ERROR] 不允许的端口 {port}，仅支持: {sorted(ALLOWED_PORTS)}")
                sys.exit(1)
            _run_mcp_service(port)
        else:
            print(f"[ERROR] 未知参数: {arg}")
            print("")
            print("  用法:")
            print("    python server.py 7860          # 启动 MCP 服务（推荐）")
            sys.exit(1)
    else:
        print("  [INFO] 未指定端口，使用默认配置")
        print("  [INFO] 启动 MCP 服务 (端口: 7860)")
        _run_mcp_service(DEFAULT_PORT)