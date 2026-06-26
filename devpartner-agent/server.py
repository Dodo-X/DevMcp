"""
DevPartner Agent - MCP 智能管家服务器 v2.0.0

定位：有状态、有记忆、有自我进化能力的智能管家层。
职责：对话记录、知识管理、自我迭代、规则引擎、跨AI协作。

与 devpartner-tools 的关系：
- Agent 依赖 Tools 层提供基础工具能力
- Agent 在 Tools 之上增加了状态管理和智能决策
- Agent 通过 MCP 协议调用 Tools 的工具函数

启动方式：
    python server.py          # stdio 模式（推荐）
    python server.py sse      # SSE 模式（远程部署）

数据存储：
    ./data/databases/  - SQLite 数据库（WAL模式，高性能）
    ./data/logs/       - 对话日志（自动归档清理）
    ./data/backups/    - 进化备份
    ./data/temp/       - 临时协同文件

作者：DevPartner Team
版本：2.0.0
"""

import sys
import os
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP

# 创建 MCP 实例
mcp = FastMCP("devpartner-agent")

print("=" * 60)
print("  DevPartner Agent v2.0.0 启动中...")
print("  智能管家层 - 有状态 | 有记忆 | 自进化")
print("=" * 60)


# ============================================================
# 核心初始化
# ============================================================

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
        
        _core_initialized = True
        return True
    except Exception as e:
        print(f"[WARN] 核心模块初始化失败: {e}")
        print("[WARN] Agent 将以降级模式运行（仅基础功能可用）")
        return False


# ============================================================
# 对话记录与日志（保留原有逻辑）
# ============================================================

@mcp.tool()
def log_conversation(topic: str, task_type: str, user_intent: str,
                     actions: str, files_touched: str = "[]",
                     problems: str = "", solutions: str = "",
                     decisions: str = "", self_reflection: str = "",
                     thinking_steps: str = "[]") -> str:
    """
    记录对话到日志系统
    
    每次实质性对话后自动调用，记录关键信息用于后续分析和优化。
    这是 Agent 层的核心功能之一，保持有状态的历史记录。
    
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
    import json
    from datetime import datetime
    
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
        
        # 同时写入数据库
        try:
            from core.database import get_db
            db = get_db()
            db.insert_conversation(data)
        except Exception:
            pass
        
        return json.dumps({"success": True, "log_file": log_file, "topic": topic}, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_daily_summary(date: str = "") -> str:
    """
    获取每日工作总结
    
    从日志中提取指定日期的工作摘要，分析工作模式和效率。
    
    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天
    
    Returns:
        JSON: 当日工作总结
    """
    import json
    
    _ensure_core()
    
    try:
        from skills.daily_summary import generate_daily_summary
        result = generate_daily_summary(date)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 跨AI对话（保留原有逻辑）
# ============================================================

@mcp.tool()
def send_agent_message(target_agent: str, message: str,
                       message_type: str = "info",
                       priority: int = 1) -> str:
    """
    发送跨AI消息
    
    在多个AI实例之间传递消息，实现协作。
    
    Args:
        target_agent: 目标AI标识
        message: 消息内容
        message_type: 消息类型（info/warning/error/question）
        priority: 优先级（1-5）
    
    Returns:
        JSON: 发送结果
    """
    import json
    from datetime import datetime
    
    _ensure_core()
    
    try:
        from services.dialogue_service import get_dialogue_service
        dialogue_svc = get_dialogue_service()
        
        msg_data = {
            "from": "devpartner-agent",
            "to": target_agent,
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
def check_agent_messages() -> str:
    """
    检查未读的跨AI消息
    
    Returns:
        JSON: 未读消息列表
    """
    import json
    
    _ensure_core()
    
    try:
        from services.dialogue_service import get_dialogue_service
        dialogue_svc = get_dialogue_service()
        messages = dialogue_svc.get_unread_messages()
        return json.dumps({"success": True, "messages": messages, "count": len(messages)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 自我迭代引擎（🌟 核心保留功能）
# ============================================================

@mcp.tool()
def self_iterate(mode: str = "auto", dry_run: bool = False,
                 require_approval: bool = False) -> str:
    """
    执行自我迭代流程（带审批链）
    
    借鉴 Goose 的审批链模式，支持：
    - dry_run: 预览模式，仅分析不执行变更
    - require_approval: 高风险操作需要人工审批
    
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
    import json
    
    _ensure_core()
    
    try:
        from skills.self_iterate import run_self_iterate
        from core.approval_chain import ApprovalChain, create_approval_request
        
        # 初始化审批链
        chain = ApprovalChain(
            auto_approve_enabled=True,
            ai_approve_enabled=False,
            user_approve_enabled=require_approval,
            dry_run=dry_run or mode == "analyze"
        )
        
        # 创建审批请求
        approval_req = create_approval_request(
            operation="self_iterate",
            description=f"自我迭代分析 - 模式: {mode}",
            risk_level="medium" if mode in ("full", "auto") else "low",
            mode=mode,
            dry_run=dry_run or mode == "analyze"
        )
        
        # 审批链检查
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
            # Dry-run 模式：仍执行分析但标记为跳过
            mode = "analyze"
        
        # 执行自我迭代
        result = run_self_iterate(mode)
        
        # 附加审批信息
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
    """
    自我升级 - 修改自身代码
    
    通过进化引擎安全地修改项目文件：
    - 自动备份原文件
    - 语法验证（Python文件）
    - 失败自动回滚
    - 记录进化日志
    
    Args:
        file_path: 相对于项目根目录的文件路径
        new_content: 新的文件内容
        validate: 是否进行语法验证（Python文件）
    
    Returns:
        JSON: {success, file, backup, action}
    """
    import json
    
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
    """
    自我创建新文件
    
    通过进化引擎安全地创建新文件。
    
    Args:
        file_path: 相对于项目根目录的文件路径
        content: 文件内容
        validate: 是否验证语法
    
    Returns:
        JSON: {success, file, action}
    """
    import json
    
    _ensure_core()
    
    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.create_file(file_path, content, validate)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 规则引擎（保留原有逻辑）
# ============================================================

@mcp.tool()
def get_rules() -> str:
    """
    获取所有已注册的规则
    
    Returns:
        JSON: 规则列表
    """
    import json
    
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
    """
    手动触发指定规则
    
    Args:
        rule_name: 规则名称
        context: 触发上下文（JSON格式）
    
    Returns:
        JSON: 触发结果
    """
    import json
    
    _ensure_core()
    
    try:
        from core.rule_engine import get_rule_engine
        engine = get_rule_engine()
        ctx = json.loads(context) if isinstance(context, str) else context
        result = engine.trigger(rule_name, ctx)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 日志读取与管理（补回丢失的核心工具）
# ============================================================

@mcp.tool()
def read_daily_log(date: str = "") -> str:
    """
    读取指定日期的对话日志

    从 Markdown 日志文件中读取指定日期的完整对话记录。

    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天

    Returns:
        JSON: {date, content, size_bytes} 或错误信息
    """
    import json

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
    """
    列出所有日志文件

    扫描 daily_logs 目录，返回所有对话日志文件的日期、大小等信息。

    Returns:
        JSON: [{date, file, size_bytes, path}, ...]
    """
    import json

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
    """
    检查日志时间间隙

    分析指定日期日志中各条目之间的时间间隔，检测超过30分钟的间隙（可能是遗漏记录）。

    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天

    Returns:
        JSON: {has_gaps, gap_count, gaps: [{from, to, gap_minutes}], total_entries}
    """
    import json

    _ensure_core()

    try:
        from services.log_service import get_log_service
        log_svc = get_log_service()
        result = log_svc.gap_check(date if date else None)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 每日总结数据接口（AI-Client-Driven 模式）
# ============================================================

@mcp.tool()
def get_daily_work_data(date: str = "", fallback_to_log: bool = True) -> str:
    """
    获取指定日期的工作原始数据（供 AI 客户端分析用）

    v3.0 架构：MCP 提供纯数据，AI 客户端用自己的 LLM 做分析。
    返回日志内容、结构化对话记录、统计数据、涉及文件列表等。

    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天
        fallback_to_log: DB无数据时是否降级读取本地日志（默认True）

    Returns:
        JSON: {date, log_content, conversations, stats, files_touched, data_source}
    """
    import json

    _ensure_core()

    try:
        from skills.daily_summary import get_daily_work_data as get_data
        result = get_data(date if date else None, fallback_to_log)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def save_daily_analysis(analysis_json: str) -> str:
    """
    保存 AI 客户端的每日分析结果

    将 AI 分析后的总结（含经验、技能、知识、危险信号、自我分析）保存到数据库并生成报告。

    Args:
        analysis_json: JSON 字符串，格式见 get_work_schema_guide

    Returns:
        JSON: {success, date, steps, report_path}
    """
    import json

    _ensure_core()

    try:
        from skills.daily_summary import save_daily_analysis as save_analysis
        result = save_analysis(analysis_json)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_weekly_work_data() -> str:
    """
    获取最近7天的工作数据概览

    返回每天对话数量、任务类型分布、总计等，适合生成周报。

    Returns:
        JSON: {week_start, week_end, days: [{date, conversation_count, tasks}], total_conversations}
    """
    import json

    _ensure_core()

    try:
        from skills.daily_summary import get_weekly_work_data as get_weekly
        result = get_weekly()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_work_schema_guide() -> str:
    """
    获取 save_daily_analysis 所需的数据结构说明

    返回分析 JSON 的完整 schema，供 AI 客户端参考如何组织分析数据。

    Returns:
        JSON: schema 说明文档
    """
    import json

    schema = {
        "description": "每日工作总结数据结构（用于 save_daily_analysis）",
        "fields": {
            "date": "日期 YYYY-MM-DD（必填）",
            "summary": "一句话总结今日工作（必填）",
            "experience": {
                "deep_dive": "深度复盘：今日最重要的技术收获",
                "lesson": "教训：今日踩坑和学到的经验",
            },
            "skills": {
                "new_skills": ["新掌握的技能/工具/方法"],
                "patterns": ["发现的可用模式/模板"],
                "tools": ["使用的新工具"],
            },
            "knowledge": {
                "must_remember": ["必须记住的知识点"],
                "insights": ["洞察和领悟"],
            },
            "danger_signals": {
                "repeated_mistakes": ["重复犯的错误"],
                "tech_debt": ["积累的技术债"],
                "hot_files": ["被频繁修改的文件（可能设计问题）"],
            },
            "tomorrow_plan": "明天最优先做的事",
            "self_analysis": {
                "strengths": ["今日表现好的方面"],
                "weaknesses": ["需要改进的方面"],
                "growth_suggestions": ["具体改进建议"],
            },
            "cross_insight": {
                "title": "跨AI洞察标题（可选）",
                "content": "分享给其他AI的经验（可选）",
                "to": "目标AI名称（可选）",
            },
        },
        "example": {
            "date": "2026-06-27",
            "summary": "完成了 Agent 层 8 个核心工具的补回",
            "experience": {
                "deep_dive": "MCP 工具暴露需要考虑导入路径，入口文件用绝对导入，模块内部用相对导入",
                "lesson": "先读代码再动手，避免重复造轮子",
            },
            "skills": {
                "new_skills": ["FastMCP 工具注册", "SQLite WAL 模式优化"],
                "patterns": ["审批链模式：自动→AI→用户三级审批"],
            },
            "knowledge": {
                "must_remember": ["server.py 入口文件必须用绝对导入"],
            },
            "tomorrow_plan": "继续补回日志和进化引擎相关工具",
        },
    }
    return json.dumps(schema, ensure_ascii=False, indent=2)


# ============================================================
# 日志导入数据库（降级恢复能力）
# ============================================================

@mcp.tool()
def import_daily_log_to_db(date: str = "") -> str:
    """
    将本地 Markdown 日志导入到 SQLite 数据库

    解决"刚部署数据库无历史数据"问题：从 daily_logs/ 解析 Markdown 日志并灌入数据库。

    Args:
        date: 日期字符串（YYYY-MM-DD），默认今天

    Returns:
        JSON: {success, date, imported_count, skipped_count}
    """
    import json

    _ensure_core()

    try:
        from skills.daily_summary import import_daily_log_to_db as import_log
        result = import_log(date if date else None)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def sync_all_logs_to_db() -> str:
    """
    批量同步所有本地日志到数据库

    扫描 daily_logs 目录下所有日志文件，逐个导入数据库。
    适用于首次部署或数据迁移场景。

    Returns:
        JSON: {success, synced_dates, total_imported, total_skipped}
    """
    import json

    _ensure_core()

    try:
        from skills.daily_summary import sync_all_logs_to_db as sync_all
        result = sync_all()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 数据库管理
# ============================================================

@mcp.tool()
def query_database(query: str, params: str = "[]") -> str:
    """
    查询本地数据库
    
    Agent 层的数据库操作，用于查询对话历史、统计数据等。
    
    Args:
        query: SQL 查询语句
        params: 查询参数（JSON数组）
    
    Returns:
        JSON: 查询结果
    """
    import json
    
    _ensure_core()
    
    try:
        from core.database import get_db
        db = get_db()
        p = json.loads(params) if isinstance(params, str) else params
        result = db.execute_query(query, p)
        return json.dumps({"success": True, "result": result, "row_count": len(result) if result else 0}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def search_conversations(keyword: str, limit: int = 20) -> str:
    """
    搜索历史对话记录

    在对话数据库中全文搜索包含指定关键词的记录。

    Args:
        keyword: 搜索关键词
        limit: 返回条数限制（默认20）

    Returns:
        JSON: {results: [{timestamp, topic, task_type, ...}], total_found}
    """
    import json

    _ensure_core()

    try:
        from core.database import get_db
        db = get_db()
        results = db.query_local(
            """SELECT timestamp, topic, task_type, user_intent, actions, problems, decisions
               FROM conversations
               WHERE topic LIKE ? OR user_intent LIKE ? OR actions LIKE ? OR problems LIKE ? OR decisions LIKE ?
               ORDER BY timestamp DESC LIMIT ?""",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", limit),
        )
        total = db.query_local(
            """SELECT COUNT(*) as cnt FROM conversations
               WHERE topic LIKE ? OR user_intent LIKE ? OR actions LIKE ? OR problems LIKE ? OR decisions LIKE ?""",
            (f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
        )
        return json.dumps({
            "success": True,
            "keyword": keyword,
            "results": results,
            "total_found": total[0]["cnt"] if total else 0,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_db_stats() -> str:
    """
    获取数据库统计信息

    返回数据库中各表的记录数、数据库文件大小、每日对话统计等。

    Returns:
        JSON: {tables: {table_name: row_count}, total_size, daily_stats}
    """
    import json
    import os

    _ensure_core()

    try:
        from core.database import get_db
        from core.config import get_config
        db = get_db()
        cfg = get_config()

        tables = ["conversations", "rule_executions", "evolution_log", "mcp_discovery",
                   "knowledge_graph", "mindmaps", "system_improvements"]
        stats = {}
        for table in tables:
            try:
                r = db.query_local(f"SELECT COUNT(*) as cnt FROM {table}")
                stats[table] = r[0]["cnt"] if r else 0
            except Exception:
                stats[table] = 0

        # 数据库文件大小
        db_path = os.path.join(cfg.data.databases_dir, "devpartner.db")
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0

        return json.dumps({
            "success": True,
            "tables": stats,
            "total_records": sum(stats.values()),
            "db_size_bytes": db_size,
            "db_size_mb": round(db_size / (1024 * 1024), 2),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 进化引擎与系统状态（补回丢失的核心工具）
# ============================================================

@mcp.tool()
def get_system_status() -> str:
    """
    获取系统运行状态

    返回版本信息、数据库状态、规则数量、MCP服务数量、今日升级次数等。

    Returns:
        JSON: {version, database_ok, rules_count, mcp_servers_known, upgrades_today, ...}
    """
    import json

    _ensure_core()

    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        status = engine.get_system_status()
        return json.dumps(status, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def self_diagnose() -> str:
    """
    运行系统自诊断

    检查目录结构、核心文件完整性、依赖安装状态，返回健康报告。

    Returns:
        JSON: {healthy, checks: {dir_xxx, file_xxx, fastmcp_installed}, issues: [...]}
    """
    import json

    _ensure_core()

    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.self_diagnose()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_evolution_history(limit: int = 50) -> str:
    """
    获取自我进化历史

    查看系统历次自我更新的记录：文件变更、版本变化、成功/失败状态。

    Args:
        limit: 返回记录数（默认50）

    Returns:
        JSON: [{timestamp, version_from, version_to, change_type, description, files_changed, success}, ...]
    """
    import json

    _ensure_core()

    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        history = engine.get_evolution_history()
        return json.dumps({
            "success": True,
            "history": history[:limit],
            "total": len(history),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_pending_improvements() -> str:
    """
    获取待处理的系统改进建议

    返回所有状态为 pending 的改进建议，按优先级排序。
    这些建议来自每日总结的 danger_signals、cross_insight 等。

    Returns:
        JSON: [{id, timestamp, category, suggestion, priority, status}, ...]
    """
    import json

    _ensure_core()

    try:
        from core.database import get_db
        db = get_db()
        improvements = db.get_pending_improvements()
        return json.dumps({
            "success": True,
            "pending": improvements,
            "count": len(improvements),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def detect_rules(user_input: str) -> str:
    """
    根据用户输入检测应触发的规则

    分析用户输入内容，匹配所有自动触发规则的关键词，返回应触发的规则列表。

    Args:
        user_input: 用户输入的文本/意图描述

    Returns:
        JSON: {triggered_rules: [{name, description, priority, trigger_keywords}], count}
    """
    import json

    _ensure_core()

    try:
        from core.rule_engine import get_rule_engine
        engine = get_rule_engine()
        triggered = engine.detect_triggers(user_input)
        rules_info = [
            {
                "name": r.name,
                "description": r.description,
                "priority": r.priority,
                "trigger_keywords": r.trigger_keywords,
                "auto_trigger": r.auto_trigger,
            }
            for r in triggered
        ]
        return json.dumps({
            "success": True,
            "input": user_input,
            "triggered_rules": rules_info,
            "count": len(rules_info),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def hot_reload_module(module_name: str) -> str:
    """
    热重载 Python 模块（无需重启服务）

    对指定模块执行 importlib.reload，适用于代码自我进化后无需重启的场景。

    Args:
        module_name: 模块名，如 "core.config" 或 "services.log_service"

    Returns:
        JSON: {success, module, action: "reloaded"|"imported"}
    """
    import json

    _ensure_core()

    try:
        from core.evolution import get_evolution_engine
        engine = get_evolution_engine()
        result = engine.hot_reload_module(module_name)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# MCP 服务发现（discovery_service 暴露为工具）
# ============================================================

@mcp.tool()
def list_recommended_mcp_servers() -> str:
    """
    列出推荐的免费 MCP 服务

    返回所有已收录的免费/有免费额度的 MCP 服务列表，含分类和免费级别标记。

    Returns:
        JSON: {total, servers: {name: {package, description, tools, free_tier, category}}}
    """
    import json

    _ensure_core()

    try:
        from services.discovery_service import get_discovery
        discovery = get_discovery()
        servers = discovery.get_recommended_servers()
        return json.dumps(servers, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def scan_new_mcp_servers() -> str:
    """
    扫描并发现新的 MCP 服务

    从 npm registry 搜索新的 @modelcontextprotocol 包，测试可用性，返回新发现的服务。

    Returns:
        JSON: {total_found, new_discovered, discovered: [{name, description, version}], known_count}
    """
    import json

    _ensure_core()

    try:
        from services.discovery_service import get_discovery
        discovery = get_discovery()
        result = discovery.scan_and_discover()
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_discovery_status() -> str:
    """
    获取 MCP 服务发现状态

    查看已发现的 MCP 服务数量、已集成的服务、最近的扫描记录。

    Returns:
        JSON: {total_discovered, integrated, recent: [...]}
    """
    import json

    _ensure_core()

    try:
        from services.discovery_service import get_discovery
        discovery = get_discovery()
        status = discovery.get_scan_status()
        return json.dumps(status, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 安全审计（自动+手动）
# ============================================================

@mcp.tool()
def run_security_audit(scan_paths: str = "[]") -> str:
    """
    运行安全审计——扫描代码中的常见安全问题

    自动检查以下安全问题：
    - 硬编码密钥/密码/Token
    - SQL 注入风险
    - 危险导入（pickle, eval, exec）
    - 不安全命令执行（os.system, shell=True）
    - 日志中泄露敏感信息
    - 弱哈希算法（MD5/SHA1）
    - 不安全的反序列化
    - Debug 模式泄露

    此工具也可被 security-audit 规则自动触发。

    Args:
        scan_paths: 要扫描的路径列表（JSON数组），默认 ["devpartner-agent", "devpartner-tools"]

    Returns:
        JSON: {
            findings: [{rule_id, severity, file, line, line_content, message, remediation}],
            severity_summary: {critical, high, medium, low},
            total_findings, files_scanned, recommendations
        }
    """
    import json

    _ensure_core()

    try:
        paths = json.loads(scan_paths) if isinstance(scan_paths, str) else scan_paths
        if not paths:
            paths = ["devpartner-agent", "devpartner-tools"]

        from core.rule_engine import get_rule_engine
        engine = get_rule_engine()
        result = engine._run_security_audit({"scan_paths": paths})
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# AI 优化器
# ============================================================

@mcp.tool()
def optimize_prompt(prompt: str, context: str = "{}") -> str:
    """
    优化提示词
    
    使用 AI 优化器分析并改进提示词，提升 AI 输出质量。
    
    Args:
        prompt: 原始提示词
        context: 上下文信息（JSON）
    
    Returns:
        JSON: {original, optimized, suggestions}
    """
    import json
    
    _ensure_core()
    
    try:
        from services.ai_optimizer import get_ai_optimizer
        optimizer = get_ai_optimizer()
        ctx = json.loads(context) if isinstance(context, str) else context
        result = optimizer.optimize(prompt, ctx)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 数据生命周期管理
# ============================================================

@mcp.tool()
def cleanup_old_data(retention_days: int = 0, dry_run: bool = False) -> str:
    """
    清理过期数据（支持 dry-run 预览模式）
    
    自动清理超过保留天数的旧日志和数据库记录。
    
    Args:
        retention_days: 保留天数（0=使用配置文件默认值）
        dry_run: 预览模式（True=仅列出将删除的内容，不实际删除）
    
    Returns:
        JSON: 清理结果（dry_run 模式下包含 will_delete 预览）
    """
    import json
    from datetime import datetime, timedelta
    
    _ensure_core()
    
    try:
        from core.config import get_config
        cfg = get_config()
        
        days = retention_days if retention_days > 0 else cfg.data_lifecycle.log_retention_days
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        if dry_run:
            result = {
                "success": True,
                "mode": "dry_run",
                "retention_days": days,
                "cutoff_date": cutoff,
                "will_delete": {},
                "message": "预览模式：未实际删除任何数据"
            }
            
            # 预览数据库旧对话
            try:
                from core.database import get_db
                db = get_db()
                r = db.query_local(
                    "SELECT COUNT(*) as cnt FROM conversations WHERE date(timestamp) < ?", (cutoff,)
                )
                result["will_delete"]["conversations"] = r[0]["cnt"] if r else 0
            except Exception as e:
                result["will_delete"]["conversations_error"] = str(e)
            
            # 预览旧日志文件
            try:
                from services.log_service import get_log_service
                log_svc = get_log_service()
                old_logs = log_svc.list_old_logs(days) if hasattr(log_svc, "list_old_logs") else []
                result["will_delete"]["log_files"] = len(old_logs) if old_logs else 0
                result["will_delete"]["log_file_list"] = old_logs[:10] if old_logs else []
            except Exception as e:
                result["will_delete"]["log_files_error"] = str(e)
            
            return json.dumps(result, ensure_ascii=False)
        
        # 实际删除模式
        result = {"success": True, "retention_days": days, "cutoff_date": cutoff, "cleaned": {}}
        
        # 清理数据库旧对话
        try:
            from core.database import get_db
            db = get_db()
            r = db.query_local(
                "DELETE FROM conversations WHERE date(timestamp) < ?", (cutoff,)
            )
            result["cleaned"]["conversations"] = r[0].get("affected_rows", 0) if r else 0
        except Exception as e:
            result["cleaned"]["conversations_error"] = str(e)
        
        # 清理旧日志文件
        try:
            from services.log_service import get_log_service
            log_svc = get_log_service()
            archived = log_svc.archive_old_logs(days)
            result["cleaned"]["log_files"] = len(archived) if archived else 0
        except Exception as e:
            result["cleaned"]["log_files_error"] = str(e)
        
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 工具注册表管理（P2 - 统一 Registry）
# ============================================================

@mcp.tool()
def get_tool_registry_status() -> str:
    """
    获取工具注册表状态

    查看所有已注册工具、启用/禁用/废弃状态、调用统计、冲突检测。

    Returns:
        JSON: 注册表统计信息（总数、来源分布、作用域分布、Top10 最常用工具）
    """
    import json

    _ensure_core()

    try:
        from core.tool_registry import get_tool_registry
        registry = get_tool_registry()
        stats = registry.get_stats()
        return json.dumps(stats, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def export_tool_manifest() -> str:
    """
    导出完整工具清单（JSON）

    包含所有工具的名称、描述、来源、作用域、启用状态、废弃标记、调用次数。

    Returns:
        JSON: 完整工具清单
    """
    import json

    _ensure_core()

    try:
        from core.tool_registry import get_tool_registry
        registry = get_tool_registry()
        return registry.export_manifest()
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def enable_tool(tool_name: str) -> str:
    """
    启用工具

    Args:
        tool_name: 工具名称

    Returns:
        JSON: 操作结果
    """
    import json

    _ensure_core()

    try:
        from core.tool_registry import get_tool_registry
        registry = get_tool_registry()
        ok = registry.enable(tool_name)
        return json.dumps({"success": ok, "tool": tool_name, "action": "enable"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def disable_tool(tool_name: str) -> str:
    """
    禁用工具（不删除，仅标记禁用）

    Args:
        tool_name: 工具名称

    Returns:
        JSON: 操作结果
    """
    import json

    _ensure_core()

    try:
        from core.tool_registry import get_tool_registry
        registry = get_tool_registry()
        ok = registry.disable(tool_name)
        return json.dumps({"success": ok, "tool": tool_name, "action": "disable"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def deprecate_tool(tool_name: str, message: str = "") -> str:
    """
    标记工具为废弃

    Args:
        tool_name: 工具名称
        message: 废弃原因和迁移说明

    Returns:
        JSON: 操作结果
    """
    import json

    _ensure_core()

    try:
        from core.tool_registry import get_tool_registry
        registry = get_tool_registry()
        ok = registry.deprecate(tool_name, message or f"工具 '{tool_name}' 已废弃")
        return json.dumps({"success": ok, "tool": tool_name, "action": "deprecate"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 审批链管理（P1a - 三级审批）
# ============================================================

@mcp.tool()
def get_approval_status() -> str:
    """
    获取审批链状态

    查看审批历史、待审批项、审批率、dry-run 模式状态。

    Returns:
        JSON: 审批摘要
    """
    import json

    _ensure_core()

    try:
        from core.approval_chain import ApprovalChain
        chain = ApprovalChain()
        summary = chain.get_summary()
        return json.dumps(summary, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_capability_status() -> str:
    """
    获取能力授权状态

    查看已禁用的能力、自动批准配置、最近审批记录。

    Returns:
        JSON: 能力状态报告
    """
    import json

    _ensure_core()

    try:
        from core.capabilities import get_capability_manager
        mgr = get_capability_manager()
        report = mgr.get_status_report()
        return json.dumps(report, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def set_auto_approve(capability: str, enabled: bool = True) -> str:
    """
    设置能力的自动批准

    Args:
        capability: 能力名称（如 file_write, database, evolution）
        enabled: 是否启用自动批准

    Returns:
        JSON: 操作结果
    """
    import json

    _ensure_core()

    try:
        from core.capabilities import get_capability_manager, Capability
        mgr = get_capability_manager()

        # 查找能力枚举
        cap = None
        for c in Capability:
            if c.value == capability:
                cap = c
                break

        if cap is None:
            return json.dumps({
                "success": False,
                "error": f"未知能力: {capability}",
                "available": [c.value for c in Capability]
            }, ensure_ascii=False)

        mgr.set_auto_approve(cap, enabled)
        return json.dumps({
            "success": True,
            "capability": capability,
            "auto_approve": enabled,
            "risk_level": mgr.get_risk_level(capability)
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 并行任务分解引擎（加速利器）
# ============================================================

@mcp.tool()
def decompose_task(task: str, max_subtasks: int = 5) -> str:
    """
    将复杂任务拆解为可并行的子任务

    分析任务依赖关系，识别可以并行执行的子任务组。
    这是加速复杂任务的关键能力——让 AI 客户端把子任务分派给多个并行 agent。

    Args:
        task: 任务描述
        max_subtasks: 最大子任务数（3-8）

    Returns:
        JSON: {
            task, subtasks: [{id, description, dependencies, estimated_effort, can_parallelize}],
            parallel_groups: [[可并行的任务组]],
            total_estimated_effort: "总预估工作量",
            suggestion: "执行建议"
        }
    """
    import json

    _ensure_core()

    try:
        # 分析任务关键词，识别可并行的子任务
        task_lower = task.lower()

        # 常见并行模式识别
        subtasks = []
        task_id = 0

        # 模式1：多文件操作 → 可并行
        if any(kw in task_lower for kw in ["文件", "file", "文档", "模块", "component", "组件"]):
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "识别所有需要修改/创建的文件和模块",
                "dependencies": [],
                "estimated_effort": "1-2min",
                "can_parallelize": False,
                "category": "analysis"
            })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "并行处理各文件/模块的修改",
                "dependencies": [1],
                "estimated_effort": "2-5min (并行)",
                "can_parallelize": True,
                "category": "implementation",
                "parallel_hint": "每个文件可以独立处理，互不依赖"
            })

        # 模式2：代码+测试+文档 → 可并行
        if any(kw in task_lower for kw in ["代码", "测试", "文档", "code", "test", "doc"]):
            if task_id == 0:
                task_id += 1
                subtasks.append({
                    "id": task_id,
                    "description": "分析需求，确定接口/数据结构",
                    "dependencies": [],
                    "estimated_effort": "1-2min",
                    "can_parallelize": False,
                    "category": "analysis"
                })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "实现核心代码逻辑",
                "dependencies": [1],
                "estimated_effort": "3-5min",
                "can_parallelize": True,
                "category": "implementation"
            })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "编写单元测试",
                "dependencies": [1],
                "estimated_effort": "2-3min",
                "can_parallelize": True,
                "category": "test"
            })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "更新文档/README",
                "dependencies": [1],
                "estimated_effort": "1-2min",
                "can_parallelize": True,
                "category": "documentation"
            })

        # 模式3：前后端分离 → 可并行
        if any(kw in task_lower for kw in ["前后端", "前端", "后端", "frontend", "backend", "api", "接口", "ui"]):
            if task_id == 0:
                task_id += 1
                subtasks.append({
                    "id": task_id,
                    "description": "定义 API 接口契约/数据模型",
                    "dependencies": [],
                    "estimated_effort": "1-2min",
                    "can_parallelize": False,
                    "category": "design"
                })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "实现后端 API 逻辑",
                "dependencies": [1],
                "estimated_effort": "3-5min",
                "can_parallelize": True,
                "category": "backend"
            })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "实现前端 UI/交互",
                "dependencies": [1],
                "estimated_effort": "3-5min",
                "can_parallelize": True,
                "category": "frontend"
            })

        # 模式4：搜索/研究 → 可并行多源搜索
        if any(kw in task_lower for kw in ["搜索", "search", "研究", "research", "查找", "find", "分析", "analy"]):
            if task_id == 0:
                task_id += 1
                subtasks.append({
                    "id": task_id,
                    "description": "分解搜索关键词/研究维度",
                    "dependencies": [],
                    "estimated_effort": "1min",
                    "can_parallelize": False,
                    "category": "analysis"
                })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "并行多源搜索（代码搜索 + 文档搜索 + Web搜索）",
                "dependencies": [1],
                "estimated_effort": "2-3min (并行)",
                "can_parallelize": True,
                "category": "search",
                "parallel_hint": "每个搜索源独立，可同时执行"
            })

        # 通用模式：汇总阶段
        if subtasks:
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "汇总所有并行结果，生成最终输出",
                "dependencies": [t["id"] for t in subtasks if t["can_parallelize"]],
                "estimated_effort": "1-2min",
                "can_parallelize": False,
                "category": "summary"
            })

        # 如果没有匹配到模式，生成通用分解
        if not subtasks:
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "分析任务需求，制定执行计划",
                "dependencies": [],
                "estimated_effort": "1-2min",
                "can_parallelize": False,
                "category": "analysis"
            })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "执行核心任务逻辑",
                "dependencies": [1],
                "estimated_effort": "3-5min",
                "can_parallelize": False,
                "category": "implementation"
            })
            task_id += 1
            subtasks.append({
                "id": task_id,
                "description": "验证和检查结果",
                "dependencies": [2],
                "estimated_effort": "1-2min",
                "can_parallelize": False,
                "category": "verification"
            })

        # 构建并行组
        parallel_tasks = [t for t in subtasks if t.get("can_parallelize")]
        parallel_groups = []
        if parallel_tasks:
            # 简单策略：所有无相互依赖的可并行任务放在同一组
            parallel_groups.append([t["id"] for t in parallel_tasks])

        # 计算总工作量
        total_min = sum(
            int(t["estimated_effort"].split("-")[-1].replace("min", "").replace("(并行)", "").strip())
            for t in subtasks
        )
        # 并行加速比
        parallel_min = total_min
        if parallel_tasks:
            # 并行任务取最长的
            parallel_cost = max(
                int(t["estimated_effort"].split("-")[-1].replace("min", "").replace("(并行)", "").strip())
                for t in parallel_tasks
            )
            sequential_cost = sum(
                int(t["estimated_effort"].split("-")[-1].replace("min", "").replace("(并行)", "").strip())
                for t in parallel_tasks
            )
            speedup = round(sequential_cost / max(parallel_cost, 1), 1)
            parallel_min = total_min - sequential_cost + parallel_cost

        speedup = total_min / max(parallel_min, 1) if parallel_min > 0 else 1.0
        if speedup > 1.5:
            suggestion = f"建议使用并行执行，预计加速 {speedup:.1f}x。将并行组的子任务分派给不同 agent 同时执行。"
        elif speedup > 1.1:
            suggestion = f"部分任务可并行，预计小幅加速 {speedup:.1f}x。"
        else:
            suggestion = "此任务并行空间有限，建议顺序执行。"

        return json.dumps({
            "task": task,
            "subtasks": subtasks,
            "parallel_groups": parallel_groups,
            "parallel_count": len(parallel_tasks),
            "total_subtasks": len(subtasks),
            "total_estimated_effort": f"{total_min}min (顺序)",
            "parallel_estimated_effort": f"{parallel_min}min (并行)" if parallel_tasks else f"{total_min}min",
            "speedup_factor": round(total_min / max(parallel_min, 1), 1) if parallel_min > 0 else 1.0,
            "suggestion": suggestion,
            "usage": "将 parallel_groups 中的子任务分派给不同 AI agent 并行执行，最后汇总结果"
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool()
def parallel_agent_plan(task: str, available_agents: str = "[]") -> str:
    """
    为多 Agent 并行协作生成执行计划

    输入任务描述和可用的 Agent 列表，输出分派方案。
    适合 CodeBuddy 的 Task（team mode）场景——把子任务分派给不同 team member 并行执行。

    Args:
        task: 主任务描述
        available_agents: 可用 Agent 列表（JSON数组），如 ["code-explorer", "frontend-dev", "backend-dev"]

    Returns:
        JSON: {
            plan: [{agent, subtask, priority, expected_output}],
            dependencies: [{from, to}],
            estimated_duration: "预计总耗时"
        }
    """
    import json

    _ensure_core()

    try:
        agents = json.loads(available_agents) if isinstance(available_agents, str) else available_agents
        if not agents:
            agents = ["agent-1", "agent-2"]

        task_lower = task.lower()

        # 根据任务类型推荐 Agent 角色
        plan = []

        # 分析任务类型
        if any(kw in task_lower for kw in ["文件", "file", "搜索", "search", "查找", "find", "代码", "code"]):
            plan.append({
                "agent": agents[0] if len(agents) > 0 else "code-explorer",
                "role": "代码探索者",
                "subtask": "搜索和分析相关代码文件，理解现有实现",
                "priority": "high",
                "expected_output": "代码分析报告，标注关键文件和函数",
                "estimated_duration": "1-2min"
            })

        if any(kw in task_lower for kw in ["重构", "refactor", "修改", "fix", "bug", "优化", "optimize"]):
            plan.append({
                "agent": agents[1] if len(agents) > 1 else agents[0] if agents else "coder",
                "role": "代码执行者",
                "subtask": "执行代码修改/重构/优化",
                "priority": "high",
                "expected_output": "修改后的代码文件列表",
                "estimated_duration": "3-5min",
                "depends_on": [0] if plan else []
            })

        if any(kw in task_lower for kw in ["测试", "test", "验证", "verify", "检查", "check"]):
            plan.append({
                "agent": agents[-1] if len(agents) > 1 else agents[0] if agents else "reviewer",
                "role": "验证者",
                "subtask": "验证修改结果，运行检查",
                "priority": "medium",
                "expected_output": "验证报告",
                "estimated_duration": "1-2min",
                "depends_on": [i for i in range(len(plan))] if plan else []
            })

        if any(kw in task_lower for kw in ["文档", "doc", "readme", "总结", "summary", "报告", "report"]):
            plan.append({
                "agent": agents[0] if agents else "writer",
                "role": "文档编写者",
                "subtask": "更新文档和变更记录",
                "priority": "low",
                "expected_output": "更新的文档文件",
                "estimated_duration": "1min"
            })

        # 如果没有匹配到特定模式，生成通用计划
        if not plan:
            plan = [
                {
                    "agent": agents[0] if len(agents) > 0 else "analyzer",
                    "role": "分析者",
                    "subtask": "分析任务需求，收集上下文信息",
                    "priority": "high",
                    "expected_output": "任务分析报告",
                    "estimated_duration": "1min"
                },
                {
                    "agent": agents[1] if len(agents) > 1 else agents[0] if agents else "executor",
                    "role": "执行者",
                    "subtask": "执行核心任务",
                    "priority": "high",
                    "expected_output": "执行结果",
                    "estimated_duration": "3-5min",
                    "depends_on": [0]
                },
                {
                    "agent": agents[-1] if len(agents) > 1 else agents[0] if agents else "reviewer",
                    "role": "审查者",
                    "subtask": "审查结果，确保质量",
                    "priority": "medium",
                    "expected_output": "审查报告",
                    "estimated_duration": "1-2min",
                    "depends_on": [1]
                }
            ]

        # 统计总时长
        max_chain = 0
        for p in plan:
            chain_len = 1 + len(p.get("depends_on", []))
            max_chain = max(max_chain, chain_len)

        return json.dumps({
            "task": task,
            "plan": plan,
            "total_agents": len(set(p["agent"] for p in plan)),
            "total_steps": len(plan),
            "parallel_opportunities": max(0, len(plan) - max_chain),
            "estimated_duration": "3-8min (并行) vs 6-15min (顺序)",
            "usage_hint": "使用 CodeBuddy 的 Task 工具，将 plan 中每个 agent 的 subtask 分派为独立 team member，depends_on 标识依赖关系"
        }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


# ============================================================
# 启动入口
# ============================================================

if __name__ == "__main__":
    print("")
    print("核心模块:", "已加载" if _ensure_core() else "降级模式")
    print("工具总数: 43 个 Agent 工具")
    print("")
    print("  能力:")
    print("    📝 对话记录 | 💬 跨AI协作 | 🔄 自我进化")
    print("    🧹 数据清理 | 🛡️ 审批链 | 🔐 能力授权")
    print("    📊 注册表管理 | ⚡ 并行任务分解")
    print("    📋 日志管理 | 📈 每日总结 | 🔍 系统诊断")
    print("    🔧 规则检测 | 🔌 MCP发现 | 🚀 热重载")
    print("    🛡️ 安全审计 | 自动扫描硬编码密钥/注入/SQL注入等")
    print("")
    print("待命状态: 等待 AI 客户端连接...")
    print("=" * 60)
    
    if len(sys.argv) > 1 and sys.argv[1] == "sse":
        mcp.run(transport="sse", host="0.0.0.0", port=8082)
    else:
        mcp.run()


