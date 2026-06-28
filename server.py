"""
DevPartner MCP 服务器 v2.2.0
=============================

合并 devpartner-tools 和 devpartner-agent 为单一入口。
ModelScope 等云平台限制只能暴露两个端口之一（7860 / 8080）。

架构：
  server.py (单一端口)
  ├── devpartner-tools  (纯工具层，无状态，25个工具)
  └── devpartner-agent  (智能管家层，有状态，42个工具)

启动方式：
    python server.py          # stdio 模式（推荐本地）
    python server.py sse      # SSE 模式（远程部署，默认 7860）
    python server.py sse 8080 # SSE 模式指定端口（7860 或 8080）

数据存储：
    ./data/databases/  - SQLite 数据库（WAL模式，高性能）
    ./data/logs/       - 对话日志（自动归档清理）
    ./data/backups/    - 进化备份
    ./data/temp/       - 临时协同文件

作者：DevPartner Team
版本：2.2.0
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP

# 创建统一 MCP 实例
mcp = FastMCP("devpartner")

print("=" * 60)
print("  DevPartner 服务器 v2.2.0 启动中...")
print("  devpartner-tools + devpartner-agent → 单一入口")
print("=" * 60)


# ============================================================
# 注册 devpartner-tools 的所有工具（无状态纯工具层）
# ============================================================

print("[INFO] 加载 devpartner-tools 工具层...")

try:
    sys.path.insert(0, str(Path(__file__).parent / "devpartner-tools"))

    from tools.filesystem import (
        read_file, write_file, list_directory, search_files, search_content
    )
    from tools.git_operations import (
        git_status, git_log, git_diff
    )
    from tools.web_requests import (
        fetch_url, github_search_code, github_search_repositories, context7_search
    )
    from tools.reasoning import (
        sequential_think, generate_mindmap, generate_mindmap_from_tree, list_mindmaps
    )
    from tools.system_utils import (
        execute_system_command, detect_client, environment_scan, validate_path
    )
    from tools.mcp_discovery import (
        discover_mcp_servers, list_known_mcp_servers, test_mcp_server,
        get_rules_summary, generate_config_snippet
    )

    # 注册所有工具
    mcp.tool()(read_file)
    mcp.tool()(write_file)
    mcp.tool()(list_directory)
    mcp.tool()(search_files)
    mcp.tool()(search_content)
    mcp.tool()(git_status)
    mcp.tool()(git_log)
    mcp.tool()(git_diff)
    mcp.tool()(fetch_url)
    mcp.tool()(github_search_code)
    mcp.tool()(github_search_repositories)
    mcp.tool()(context7_search)
    mcp.tool()(sequential_think)
    mcp.tool()(generate_mindmap)
    mcp.tool()(generate_mindmap_from_tree)
    mcp.tool()(list_mindmaps)
    mcp.tool()(execute_system_command)
    mcp.tool()(detect_client)
    mcp.tool()(environment_scan)
    mcp.tool()(validate_path)
    mcp.tool()(discover_mcp_servers)
    mcp.tool()(list_known_mcp_servers)
    mcp.tool()(test_mcp_server)
    mcp.tool()(get_rules_summary)
    mcp.tool()(generate_config_snippet)

    _tools_count = 25
    print(f"[INFO] devpartner-tools: {_tools_count} 个纯工具已注册")

except Exception as e:
    print(f"[WARN] devpartner-tools 加载失败: {e}")
    print("[WARN] 纯工具层将不可用，仅管家层运行")
    _tools_count = 0


# ============================================================
# 注册 devpartner-agent 的所有工具（智能管家层）
# ============================================================

print("[INFO] 加载 devpartner-agent 智能管家层...")

sys.path.insert(0, str(Path(__file__).parent / "devpartner-agent"))

# ── 核心初始化 ──────────────────────────────────────────────
_core_initialized = False

def _ensure_core():
    """确保核心模块已初始化（首次调用时初始化DB）"""
    global _core_initialized
    if _core_initialized:
        return True

    try:
        from core.config import get_config
        from core.database import get_db

        cfg = get_config()
        db_path = str(Path(cfg.data.databases_dir) / "devpartner.db")
        get_db().init_local(db_path)

        # 预热其他核心模块
        from core.rule_engine import get_rule_engine
        from core.identity import get_identity
        from core.evolution import get_evolution_engine

        # 启动自动清理调度器
        try:
            from services.cleanup_scheduler import get_cleanup_scheduler
            scheduler = get_cleanup_scheduler()
            cleanup_interval = (
                cfg.data_lifecycle.auto_cleanup_interval_hours
                if hasattr(cfg.data_lifecycle, 'auto_cleanup_interval_hours')
                else 24
            )
            if cfg.data_lifecycle.auto_cleanup:
                scheduler.start(interval_hours=cleanup_interval)
                print(f"[INFO] 自动清理调度器已启动，间隔 {cleanup_interval} 小时")
        except Exception as e:
            print(f"[WARN] 自动清理调度器启动失败: {e}")

        _core_initialized = True
        return True
    except Exception as e:
        print(f"[WARN] 核心模块初始化失败: {e}")
        print("[WARN] Agent 将以降级模式运行（仅基础功能可用）")
        return False


# ── 对话记录 ─────────────────────────────────────────────────
@mcp.tool()
def log_conversation(topic: str, task_type: str, user_intent: str,
                     actions: str, files_touched: str = "[]",
                     problems: str = "", solutions: str = "",
                     decisions: str = "", self_reflection: str = "",
                     thinking_steps: str = "[]") -> str:
    """
    记录对话到日志系统

    每次实质性对话后自动调用，记录关键信息用于后续分析和优化。

    Args:
        topic: 对话主题
        task_type: 任务类型（修改/创建/删除/查询/配置/部署/设计）
        user_intent: 用户意图描述
        actions: 执行的操作列表（JSON数组）
        files_touched: 涉及的文件列表（JSON数组）
        problems: 遇到的问题
        solutions: 解决方案
        decisions: 做出的决策
        self_reflection: 自我反思
        thinking_steps: 思考步骤（JSON数组）

    Returns:
        JSON: {success, log_file, topic}
    """
    _ensure_core()
    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()

        data = {
            "topic": topic,
            "task_type": task_type,
            "user_intent": user_intent,
            "actions": json.loads(actions) if isinstance(actions, str) else actions,
            "files_touched": json.loads(files_touched) if isinstance(files_touched, str) else files_touched,
            "problems": problems,
            "solutions": solutions,
            "decisions": decisions,
            "self_reflection": self_reflection,
            "thinking_steps": json.loads(thinking_steps) if isinstance(thinking_steps, str) else thinking_steps,
            "timestamp": datetime.now().isoformat()
        }

        log_file = log_svc.append_to_daily_log(data)

        try:
            from core.database import get_db
            db = get_db()
            db.insert_conversation(data)
        except Exception:
            pass

        return json.dumps({"success": True, "log_file": log_file, "topic": topic}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 模块协作消息 ─────────────────────────────────────────────
@mcp.tool()
def send_module_message(target_module: str, message: str,
                        message_type: str = "info",
                        priority: int = 1) -> str:
    """
    发送模块间协作消息（devpartner-tools ↔ devpartner-agent 内部通信）

    用于 devpartner-tools 和 devpartner-agent 两个模块之间的消息传递，
    实现工具层和管家层之间的内部协作。

    Args:
        target_module: 目标模块标识（"tools" 或 "agent"）
        message: 消息内容
        message_type: 消息类型（info/warning/error/question）
        priority: 优先级（1-5）

    Returns:
        JSON: 发送结果
    """
    _ensure_core()
    try:
        from services.dialogue_service import get_dialogue_service
        dialogue_svc = get_dialogue_service()

        msg_data = {
            "from": "devpartner-agent" if target_module == "tools" else "devpartner-tools",
            "to": target_module,
            "message": message,
            "type": message_type,
            "priority": priority,
            "timestamp": datetime.now().isoformat()
        }

        result = dialogue_svc.send_message(msg_data)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def check_module_messages() -> str:
    """
    检查未读的模块间消息

    查看是否有来自另一个模块（tools 或 agent）的未读消息。

    Returns:
        JSON: 未读消息列表
    """
    _ensure_core()
    try:
        from services.dialogue_service import get_dialogue_service
        dialogue_svc = get_dialogue_service()
        messages = dialogue_svc.get_unread_messages()
        return json.dumps({"success": True, "messages": messages, "count": len(messages)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 自我迭代引擎 ─────────────────────────────────────────────
@mcp.tool()
def self_iterate(mode: str = "auto", dry_run: bool = False,
                 require_approval: bool = False) -> str:
    """
    执行自我迭代流程（带审批链）

    这是 DevPartner 最核心的自我进化能力：
    1. 收集系统数据（使用频率、错误日志、用户反馈）
    2. 通过 AI 分析生成改进建议
    3. 识别可自动执行的代码变更
    4. 审批链检查（自动→AI→用户）
    5. 在安全模式下执行变更（备份+回滚+Git提交）

    Args:
        mode: 运行模式
            - 'auto': 自动选择（无Git则本地模式，有Git则完整模式）
            - 'local': 本地模式（仅生成变更，不执行Git操作）
            - 'full': 完整模式（Git分支+提交+PR）
            - 'analyze': 仅分析不执行变更（同 dry_run=True）
        dry_run: 预览模式，不实际执行变更
        require_approval: 是否要求高风险操作经过审批

    Returns:
        JSON: 迭代结果（包含建议、变更、审批状态、Git状态等）
    """
    _ensure_core()
    try:
        from skills.self_iterate import run_self_iterate
        from core.approval_chain import ApprovalChain, create_approval_request

        chain = ApprovalChain(
            auto_approve_enabled=True,
            ai_approve_enabled=False,
            user_approve_enabled=require_approval,
            dry_run=dry_run or mode == "analyze"
        )

        approval_req = create_approval_request(
            operation="self_iterate",
            description=f"自我迭代分析 - 模式: {mode}",
            risk_level="medium" if mode in ("full", "auto") else "low",
            mode=mode,
            dry_run=dry_run or mode == "analyze"
        )

        approval_result = chain.process(approval_req)

        if approval_result.status.value == "rejected":
            return json.dumps({
                "success": False,
                "error": f"审批被拒绝: {approval_result.reason}",
                "approval": {
                    "status": approval_result.status.value,
                    "reason": approval_result.reason,
                    "approved_by": approval_result.approved_by,
                }
            }, ensure_ascii=False)

        if approval_result.status.value == "skipped":
            mode = "analyze"

        result = run_self_iterate(mode)

        result["approval"] = {
            "status": approval_result.status.value,
            "reason": approval_result.reason,
            "approved_by": approval_result.approved_by,
            "approved_at": approval_result.approved_at,
        }
        result["approval_summary"] = chain.get_summary()

        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e), "steps": []}, ensure_ascii=False)


@mcp.tool()
def self_upgrade(file_path: str, new_content: str,
                 validate: bool = True) -> str:
    """自我升级 - 修改自身代码（备份+验证+回滚）"""
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.upgrade_file(file_path, new_content, validate)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def self_create_file(file_path: str, content: str,
                     validate: bool = True) -> str:
    """自我创建新文件"""
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.create_file(file_path, content, validate)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 规则引擎 ─────────────────────────────────────────────────
@mcp.tool()
def get_rules() -> str:
    """获取所有已注册的规则"""
    _ensure_core()
    try:
        from core.rule_engine import get_rule_engine
        engine = get_rule_engine()
        rules = engine.get_all_rules()
        return json.dumps({"success": True, "rules": rules, "count": len(rules)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def trigger_rule(rule_name: str, context: str = "{}") -> str:
    """手动触发指定规则"""
    _ensure_core()
    try:
        from core.rule_engine import get_rule_engine
        engine = get_rule_engine()
        ctx = json.loads(context) if isinstance(context, str) else context
        result = engine.trigger(rule_name, ctx)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 日志管理 ─────────────────────────────────────────────────
@mcp.tool()
def get_daily_summary(date: str = "") -> str:
    """获取每日工作总结"""
    _ensure_core()
    try:
        from skills.daily_summary import generate_daily_summary
        result = generate_daily_summary(date)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def read_daily_log(date: str = "") -> str:
    """读取指定日期的对话日志"""
    _ensure_core()
    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()
        result = log_svc.read_daily_log(date if date else None)
        return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def list_logs() -> str:
    """列出所有日志文件"""
    _ensure_core()
    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()
        logs = log_svc.list_logs()
        return json.dumps({"success": True, "logs": logs, "count": len(logs)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def check_log_gaps(date: str = "") -> str:
    """检查日志时间间隙"""
    _ensure_core()
    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()
        result = log_svc.gap_check(date if date else None)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 每日总结数据接口 ─────────────────────────────────────────
@mcp.tool()
def get_daily_work_data(date: str = "", fallback_to_log: bool = True) -> str:
    """获取指定日期的工作原始数据（供 AI 客户端分析用）"""
    _ensure_core()
    try:
        from skills.daily_summary import get_daily_work_data as get_data
        result = get_data(date if date else None, fallback_to_log)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def save_daily_analysis(analysis_json: str) -> str:
    """保存 AI 客户端的每日分析结果"""
    _ensure_core()
    try:
        from skills.daily_summary import save_daily_analysis as save_analysis
        result = save_analysis(analysis_json)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_weekly_work_data() -> str:
    """获取最近7天的工作数据概览"""
    _ensure_core()
    try:
        from skills.daily_summary import get_weekly_work_data as get_weekly
        result = get_weekly()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_work_schema_guide() -> str:
    """获取 save_daily_analysis 所需的数据结构说明"""
    schema = {
        "description": "每日工作总结数据结构（用于 save_daily_analysis）",
        "fields": {
            "date": "日期 YYYY-MM-DD（必填）",
            "summary": "一句话总结今日工作（必填）",
            "experience": {"deep_dive": "深度复盘", "lesson": "教训"},
            "skills": {"new_skills": [], "patterns": [], "tools": []},
            "knowledge": {"must_remember": [], "insights": []},
            "danger_signals": {"repeated_mistakes": [], "tech_debt": [], "hot_files": []},
            "tomorrow_plan": "明天最优先做的事",
            "self_analysis": {"strengths": [], "weaknesses": [], "growth_suggestions": []},
        }
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


@mcp.tool()
def import_daily_log_to_db(date: str = "") -> str:
    """将本地 Markdown 日志导入到 SQLite 数据库"""
    _ensure_core()
    try:
        from skills.daily_summary import import_daily_log_to_db as import_log
        result = import_log(date if date else None)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sync_all_logs_to_db() -> str:
    """批量同步所有本地日志到数据库"""
    _ensure_core()
    try:
        from skills.daily_summary import sync_all_logs_to_db as sync_all
        result = sync_all()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 并行任务分解引擎 ─────────────────────────────────────────
@mcp.tool()
def parallel_plan(tasks: str) -> str:
    """
    并行任务分解引擎

    分析任务列表，找出可并行执行的任务，生成最优执行计划。
    支持串行依赖检查和并行分组。

    Args:
        tasks: 任务列表（JSON数组，每个任务包含 name 和 dependencies）

    Returns:
        JSON: {parallel_groups, sequential_chains, execution_order, critical_path}
    """
    try:
        task_list = json.loads(tasks) if isinstance(tasks, str) else tasks
        return json.dumps(_analyze_parallel_plan(task_list), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def _analyze_parallel_plan(tasks):
    """分析并行执行计划"""
    if not tasks:
        return {"success": False, "error": "任务列表为空"}

    result = {
        "success": True,
        "total_tasks": len(tasks),
        "parallel_groups": [],
        "sequential_chains": [],
        "execution_order": [],
        "critical_path": []
    }

    # 构建依赖图
    task_map = {}
    for task in tasks:
        name = task.get("name", task.get("id", str(len(task_map))))
        deps = task.get("dependencies", task.get("deps", []))
        task_map[name] = {"name": name, "deps": deps if isinstance(deps, list) else []}

    # 拓扑排序分组
    remaining = set(task_map.keys())
    group_index = 0

    while remaining:
        available = set()
        for name in remaining:
            if all(d not in remaining for d in task_map[name]["deps"]):
                available.add(name)

        if not available:
            result["execution_order"].append(list(remaining))
            result["parallel_groups"].append(list(remaining))
            break

        result["parallel_groups"].append(list(available))
        for name in available:
            result["execution_order"].append(name)
        remaining -= available
        group_index += 1

    # 构建串行链
    chain = [name for name in result["execution_order"]]
    if chain:
        result["sequential_chains"].append(chain)
        result["critical_path"] = chain

    return result


# ── 注册表管理 ───────────────────────────────────────────────
@mcp.tool()
def get_tool_registry() -> str:
    """
    获取工具注册表

    查看所有注册的工具、分类、使用频率等统计信息。

    Returns:
        JSON: {tools, categories, stats}
    """
    _ensure_core()
    try:
        from core.tool_registry import get_tool_registry as get_registry
        registry = get_registry()
        result = registry.get_summary()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def register_custom_tool(tool_name: str, tool_code: str,
                         category: str = "custom") -> str:
    """
    注册自定义工具

    动态注册新的 MCP 工具，支持热加载。

    Args:
        tool_name: 工具名称
        tool_code: 工具代码（Python 函数定义）
        category: 分类标签

    Returns:
        JSON: {success, tool_name, registered}
    """
    _ensure_core()
    try:
        from core.tool_registry import get_tool_registry as get_registry
        registry = get_registry()
        result = registry.register(tool_name, tool_code, category)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 能力授权 ─────────────────────────────────────────────────
@mcp.tool()
def get_capabilities() -> str:
    """
    获取当前能力授权状态

    查看各模块的能力授权配置，包括已授权和未授权的模块。

    Returns:
        JSON: {authorized, unauthorized, config}
    """
    _ensure_core()
    try:
        from core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        result = mgr.get_status()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def authorize_capability(module: str, capability: str,
                         reason: str = "") -> str:
    """
    授权指定模块的能力

    对指定的模块授予特定的能力（如文件写入、Git操作等）。

    Args:
        module: 模块名称
        capability: 能力名称
        reason: 授权理由

    Returns:
        JSON: {success, module, capability, authorized}
    """
    _ensure_core()
    try:
        from core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        result = mgr.authorize(module, capability, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def revoke_capability(module: str, capability: str,
                      reason: str = "") -> str:
    """
    撤销指定模块的能力授权

    Args:
        module: 模块名称
        capability: 能力名称
        reason: 撤销理由

    Returns:
        JSON: {success, module, capability, revoked}
    """
    _ensure_core()
    try:
        from core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        result = mgr.revoke(module, capability, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 审批链管理 ───────────────────────────────────────────────
@mcp.tool()
def get_approval_chain(operation: str = "") -> str:
    """
    获取审批链状态

    查看审批链的配置和最近审批记录。

    Args:
        operation: 操作名称（可选，不传则返回全部）

    Returns:
        JSON: {success, approvals, config}
    """
    _ensure_core()
    try:
        from core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        result = chain.get_status(operation) if operation else chain.get_all_status()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def approve_operation(operation_id: str, reason: str = "") -> str:
    """
    手动审批操作

    Args:
        operation_id: 操作ID
        reason: 审批理由

    Returns:
        JSON: {success, operation_id, approved}
    """
    _ensure_core()
    try:
        from core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        result = chain.manual_approve(operation_id, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def reject_operation(operation_id: str, reason: str) -> str:
    """
    拒绝审批操作

    Args:
        operation_id: 操作ID
        reason: 拒绝理由

    Returns:
        JSON: {success, operation_id, rejected}
    """
    _ensure_core()
    try:
        from core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        result = chain.manual_reject(operation_id, reason)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 规则检测 ─────────────────────────────────────────────────
@mcp.tool()
def check_rule(rule_name: str, content: str = "") -> str:
    """
    检查指定规则是否会被触发

    用于测试规则配置，预览触发效果。

    Args:
        rule_name: 规则名称
        content: 待检测内容

    Returns:
        JSON: {success, triggered, rule, matches}
    """
    _ensure_core()
    try:
        from core.rule_engine import get_rule_engine
        engine = get_rule_engine()
        result = engine.check_rule(rule_name, content)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 热重载 ───────────────────────────────────────────────────
@mcp.tool()
def hot_reload(module: str = "all") -> str:
    """
    热重载指定模块

    无需重启服务，动态重载模块代码。

    Args:
        module: 模块名称（"all" 表示全部，"tools" 或 "agent" 表示指定层）

    Returns:
        JSON: {success, reloaded, failed, timestamp}
    """
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.hot_reload(module)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 安全审计 ─────────────────────────────────────────────────
@mcp.tool()
def security_audit(scope: str = "quick") -> str:
    """
    执行安全审计

    扫描代码中的安全风险（密钥泄露、不安全的依赖等）。

    Args:
        scope: 审计范围（"quick" 快速扫描 / "full" 完整扫描）

    Returns:
        JSON: {success, findings, risk_level, recommendations}
    """
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.security_audit(scope)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 系统诊断 ─────────────────────────────────────────────────
@mcp.tool()
def system_diagnose() -> str:
    """
    系统诊断

    检查系统状态：数据库连接、日志完整性、模块健康状态等。

    Returns:
        JSON: {success, health, issues, recommendations}
    """
    _ensure_core()
    try:
        from core.database import get_db

        issues = []
        checks = {}

        # 数据库检查
        try:
            db = get_db()
            checks["database"] = "healthy"
        except Exception as e:
            checks["database"] = f"unhealthy: {e}"
            issues.append(f"数据库异常: {e}")

        # 日志目录检查
        try:
            from core.config import get_config
            cfg = get_config()
            log_dir = Path(cfg.data.logs_dir)
            if log_dir.exists():
                log_count = len(list(log_dir.glob("*.md")))
                checks["logs"] = f"healthy ({log_count} 个日志文件)"
            else:
                checks["logs"] = "missing"
                issues.append("日志目录不存在")
        except Exception as e:
            checks["logs"] = f"error: {e}"

        # 规则引擎检查
        try:
            from core.rule_engine import get_rule_engine
            engine = get_rule_engine()
            rules = engine.get_all_rules()
            checks["rules"] = f"healthy ({len(rules)} 条规则)"
        except Exception as e:
            checks["rules"] = f"error: {e}"

        return json.dumps({
            "success": True,
            "health": "healthy" if not issues else "degraded",
            "checks": checks,
            "issues": issues,
            "recommendations": ["重启服务"] if issues else []
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── 数据清理 ─────────────────────────────────────────────────
@mcp.tool()
def cleanup_data(scope: str = "all", dry_run: bool = False) -> str:
    """
    数据清理

    清理过期日志、临时文件、旧备份等。

    Args:
        scope: 清理范围（"all" / "logs" / "temp" / "backups"）
        dry_run: 是否仅预览不执行

    Returns:
        JSON: {success, cleaned, freed_size, details}
    """
    _ensure_core()
    try:
        from services.cleanup_scheduler import get_cleanup_scheduler
        scheduler = get_cleanup_scheduler()
        result = scheduler.cleanup(scope, dry_run)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ── Git 版本控制 ─────────────────────────────────────────────
@mcp.tool()
def git_auto_branch(description: str, base_branch: str = "main") -> str:
    """
    自动创建 Git 分支

    根据描述自动生成分支名、创建分支并推送。

    Args:
        description: 分支描述（用于生成分支名，如 "修复日志Bug"）
        base_branch: 基础分支

    Returns:
        JSON: {success, branch_name, created, pushed}
    """
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.git_auto_branch(description, base_branch)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def git_auto_commit(message: str, files: str = "[]",
                    auto_push: bool = False) -> str:
    """
    自动提交 Git 变更

    Args:
        message: 提交信息
        files: 要提交的文件列表（JSON数组，空表示全部）
        auto_push: 是否自动推送

    Returns:
        JSON: {success, committed, pushed, commit_hash}
    """
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        file_list = json.loads(files) if isinstance(files, str) else files
        result = engine.git_auto_commit(message, file_list, auto_push)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def git_auto_push(remote: str = "origin", branch: str = "") -> str:
    """
    自动推送 Git 变更到远程仓库

    Args:
        remote: 远程仓库名
        branch: 分支名（留空使用当前分支）

    Returns:
        JSON: {success, pushed, remote, branch}
    """
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.git_auto_push(remote, branch)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def git_rollback(commit_hash: str = "HEAD~1", hard: bool = False) -> str:
    """
    Git 回滚

    回滚到指定的提交。

    Args:
        commit_hash: 目标提交哈希（默认 HEAD~1 回滚到上一个提交）
        hard: 是否硬回滚（会丢弃工作区变更）

    Returns:
        JSON: {success, rolled_back_to, hard, current_hash}
    """
    _ensure_core()
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.git_rollback(commit_hash, hard)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 启动入口
# ============================================================

ALLOWED_PORTS = {7860, 8080}
DEFAULT_PORT = 7860

if __name__ == "__main__":
    print("")
    print(f"  工具层: {_tools_count} 个纯工具")
    agent_ok = _ensure_core()
    print(f"  管家层: {'已加载' if agent_ok else '降级模式'}")
    print("")
    print("  能力: 文件系统 | Git | Web | 推理 | MCP发现 | 系统工具")
    print("        对话记录 | 模块协作 | 自我进化 | 数据清理")
    print("        审批链 | 能力授权 | 注册表 | 并行任务分解")
    print("        日志管理 | 每日总结 | 系统诊断 | 规则检测")
    print("        热重载 | 安全审计 | Git版本控制")
    print("=" * 60)

    if len(sys.argv) > 1 and sys.argv[1] == "sse":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_PORT
        if port not in ALLOWED_PORTS:
            print(f"[ERROR] 不允许的端口 {port}，仅支持: {sorted(ALLOWED_PORTS)}")
            sys.exit(1)
        print(f"  监听端口: {port}")
        print("  待命状态: 等待 AI 客户端连接...")
        print("=" * 60)
        mcp.run(transport="sse", host="0.0.0.0", port=port)
    else:
        print("  待命状态: 等待 AI 客户端连接...")
        print("=" * 60)
        mcp.run()