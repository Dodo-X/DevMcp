"""
DevPartner MCP 服务器 v9.5
==========================

🎯 项目定位:
  以 MCP (Model Context Protocol) 形式对外提供服务的智能助手系统。
  专注于对话全程记录与分析，不重复提供 CodeBuddy 已具备的通用工具。

📦 系统架构 (v9.5 MCP 工具精简):
  server.py (薄壳 MCP 入口)
  ├── 核心 MCP 工具 (3个) — 对话记录三件套
  │   ├── start_conversation
  │   ├── record_step
  │   └── finalize_conversation
  │
  ├── prompts/              Prompt 层 (5个 Prompt 模板)
  │
  └── devpartner_agent/     智能管家层
      ├── core/             核心引擎层 (对话/知识/系统/日报/LLM/调度)
      ├── services/          无状态服务层
      └── skills/            技能层

🔄 协议:
  ✅ Streamable HTTP + /mcp 端点

📍 访问地址:
  本地开发:  http://127.0.0.1:7860/mcp

作者：DevPartner Team
版本：9.5 | 更新: 2026-07-20
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
    instructions=f"""DevPartner v{VERSION} - 智能开发助手 · 对话全程记录系统

【强制流程】每次对话必须按顺序调用：
  1. start_conversation  → 开启会话（对话开始时）
  2. record_step         → 每完成一个子任务立即调用（可多次）
  3. finalize_conversation → 结束会话（所有任务完成后）

【不调用的后果】不调用将导致本次对话数据完全丢失，无法被系统记录和分析。
【MCP 不可用时】静默跳过，不阻塞对话，不提示用户。""",
)

_tools_count = 0
_prompts_count = 0


def _register_tool_layer():
    """注册工具层的所有纯工具到 MCP

    v9.5: 移除所有与 CodeBuddy 原生工具重复的通用工具（filesystem/web/system）。
    DevPartner 作为 MCP 只暴露核心的对话记录工具（start/record/finalize）。
    CodeBuddy 自身具备 read_file/write_to_file/list_dir/search_file/search_content/execute_command 等工具，
    MCP 不需要重复提供。
    growth_analytics 工具仅供内部定时任务使用。
    """
    global _tools_count
    # 无通用工具需要注册，_tools_count 保持 0
    # 核心的 3 个工具（start_conversation/record_step/finalize_conversation）在 server.py 直接注册


def _register_rest_routes():
    """注册 HTTP REST 路由"""
    try:
        from devpartner_agent.routes.rest_api import register_rest_routes
        register_rest_routes(mcp)
    except Exception as e:
        print(f"[WARN] 注册 REST 路由失败: {e}")


def _register_prompts():
    """注册 MCP Prompts 到系统"""
    global _prompts_count

    @mcp.prompt(title="代码审查", description="对指定代码文件进行审查，分析代码质量、潜在问题和改进建议")
    def code_review(file_path: str) -> list:
        return [
            {
                "role": "user",
                "content": f"请对以下代码文件进行审查，分析代码质量、潜在问题、安全性、性能和改进建议：\n\n文件路径: {file_path}\n\n请使用 read_file 工具读取文件内容，然后进行审查。"
            }
        ]
    _prompts_count += 1

    @mcp.prompt(title="每日总结", description="生成今日工作内容总结，包含关键技术点和待办事项")
    def daily_summary() -> list:
        return [
            {
                "role": "user",
                "content": "请根据今日的对话记录，生成一份工作总结，包含：\n1. 今日完成的主要工作\n2. 涉及的关键技术点\n3. 遇到的问题及解决方案\n4. 明日待办事项\n\n请使用 get_recent_conversations 工具获取今日对话数据。"
            }
        ]
    _prompts_count += 1

    @mcp.prompt(title="技术方案", description="根据需求描述生成技术方案，包含架构设计、技术选型和实施计划")
    def tech_solution(requirement: str) -> list:
        return [
            {
                "role": "user",
                "content": f"请根据以下需求，生成一份完整的技术方案：\n\n{requirement}\n\n请包含：\n1. 需求分析\n2. 架构设计\n3. 技术选型及理由\n4. 数据库/接口设计\n5. 实施计划\n6. 风险与应对措施"
            }
        ]
    _prompts_count += 1

    @mcp.prompt(title="知识提取", description="从对话内容中提取关键知识点，生成结构化知识卡片")
    def knowledge_extraction(topic: str = "") -> list:
        topic_hint = f"关于 {topic} " if topic else ""
        return [
            {
                "role": "user",
                "content": f"请从对话记录中提取{topic_hint}的关键知识点，以结构化知识卡片的形式输出。\n\n请使用 get_recent_conversations 工具获取对话数据，然后提取知识点。"
            }
        ]
    _prompts_count += 1

    @mcp.prompt(title="项目分析", description="分析项目代码结构，生成项目概览报告")
    def project_analysis(project_path: str = ".") -> list:
        return [
            {
                "role": "user",
                "content": f"请分析项目 {project_path} 的代码结构，生成项目概览报告：\n\n1. 使用 list_dir 工具浏览项目目录结构\n2. 识别主要模块和依赖关系\n3. 分析技术栈和架构模式\n4. 评估代码质量和组织方式\n5. 提出改进建议"
            }
        ]
    _prompts_count += 1

    print(f"  [OK] prompts: {_prompts_count} 个 Prompt 已注册")


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
        from devpartner_agent.core.daily_engine import register_task_handlers as register_daily
        register_daily()
    except Exception as e:
        print(f"[WARN] 注册日报任务处理器失败: {e}")


@mcp.tool()
def start_conversation(client: str = "unknown", topic: str = "",
                       task_type: str = "general", user_intent: str = "",
                       priority: str = "medium",
                       system_id: str = "default",
                       user_raw_input: str = "",
                       ai_analysis: str = "",
                       trace_id: str = "",
                       request_id: str = "",
                       external_conv_id: str = "") -> str:
    """【必须调用·总分总·总】每次对话开始时必须调用，创建会话记录并获取 conversation_id。

    不调用将导致本次对话的所有步骤无法被系统记录。
    v9.1: 新增 ai_analysis — AI 对用户意图的分析推理过程，系统异步分析。
    v9.3: 新增 trace_id/request_id/external_conv_id — 外部调用链追踪三件套。"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()
        result = engine.start_conversation(
            client=client, topic=topic, task_type=task_type,
            user_intent=user_intent, priority=priority,
            system_id=system_id, user_raw_input=user_raw_input,
            ai_analysis=ai_analysis,
            trace_id=trace_id,
            request_id=request_id,
            external_conv_id=external_conv_id,
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


@mcp.tool()
def record_step(conversation_id: str = "", step_number: int = 0,
                step_name: str = "", step_type: str = "general",
                step_input: str = "{}",
                content: str = "", files_changed: str = "",
                symptom: str = "", root_cause: str = "",
                solution: str = "", knowledge_points: str = "",
                user_question: str = "", ai_reasoning: str = "",
                user_requirement: str = "", commands_executed: str = "",
                client_request_id: str = "") -> str:
    """【必须调用·总分总·分】每完成一个子任务立即调用，记录步骤详情。

    不可合并多个步骤为一次调用，不可等所有任务做完才补录。
    不调用将导致该步骤数据丢失，无法被系统分析。
    v9.1: 同时支持 step_input JSON 和独立参数，独立参数优先。
    v9.1.1: 新增 client_request_id — AI 端幂等键。"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()

        if not conversation_id or step_number is None or not step_name:
            return json.dumps({
                "error": "缺少必要参数: conversation_id, step_number, step_name",
                "success": False
            }, ensure_ascii=False)

        # v9.1: 合并 step_input JSON 和独立参数，独立参数优先
        input_data = json.loads(step_input) if isinstance(step_input, str) else (step_input or {})
        if isinstance(input_data, dict):
            # 独立参数优先于 step_input JSON
            for key, val in [
                ("content", content), ("files_changed", files_changed),
                ("symptom", symptom), ("root_cause", root_cause),
                ("solution", solution), ("knowledge_points", knowledge_points),
                ("user_question", user_question), ("ai_reasoning", ai_reasoning),
                ("user_requirement", user_requirement), ("commands_executed", commands_executed),
            ]:
                if val:  # 独立参数非空时覆盖
                    input_data[key] = val
            input_data.setdefault("client_request_id", f"{conversation_id}-{step_number}")
            # v9.1.1: 独立参数 client_request_id 优先
            if client_request_id:
                input_data["client_request_id"] = client_request_id
            step_input = json.dumps(input_data, ensure_ascii=False, default=str)

        result = engine.record_step(
            conversation_id=conversation_id,
            step_name=step_name,
            step_type=step_type,
            content=input_data.get("content", ""),
            files_changed=input_data.get("files_changed", ""),
            symptom=input_data.get("symptom", ""),
            root_cause=input_data.get("root_cause", ""),
            solution=input_data.get("solution", ""),
            knowledge_points=input_data.get("knowledge_points", ""),
            user_question=input_data.get("user_question", ""),
            client_request_id=input_data.get("client_request_id", f"{conversation_id}-{step_number}"),
            ai_reasoning=input_data.get("ai_reasoning", ""),
            user_requirement=input_data.get("user_requirement", ""),
            commands_executed=input_data.get("commands_executed", ""),
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


@mcp.tool()
def finalize_conversation(conversation_id: str = "", ai_summary: str = "") -> str:
    """【必须调用·总分总·总】所有任务完成后必须调用，结束对话并触发全局分析。

    不调用将导致本次对话标记为未完成，无法触发后续分析和知识提取。
    AI 传入 conversation_id + ai_summary（AI的最终分析总结），
    服务端合并 DB 结构化数据 + AI 文本分析触发全局分析。
    v9.1 重构: AI 传分析文本，系统从 DB 读结构化数据，双向互补。"""
    from devpartner_agent.core.bootstrap import ensure_ready
    ensure_ready()

    try:
        from devpartner_agent.core.conversation_engine import get_conversation_engine
        engine = get_conversation_engine()

        if not conversation_id:
            return json.dumps({"error": "需要 conversation_id 参数", "success": False}, ensure_ascii=False)

        result = engine.finalize_conversation(
            conversation_id=conversation_id,
            ai_summary=ai_summary,
        )
        return json.dumps(result, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "success": False}, ensure_ascii=False)


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
    _register_rest_routes()
    _register_prompts()

    _register_task_handlers()

    agent_ok = ensure_ready()
    print("")
    print(f"  MCP工具: {_tools_count + 3} 个 (3核心 + 0通用)")
    print(f"  Prompts: {_prompts_count} 个 Prompt 已注册")
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
        print("     [MCP层] 3个核心工具: start/record/finalize (对话记录三件套)")
        print("     [智能层] devpartner_agent/core/: 领域引擎 + LLM + 调度器")
        print("")
        print("  [可用功能]")
        print(f"     [MCP] POST {access_url}")
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