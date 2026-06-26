#!/usr/bin/env python3
"""
devPartner - 自我进化的全能 MCP 服务 v4.0
===========================================
v4.0 重大更新：
  ✅ 进化流程：采集数据 → 识别变更 → 创建分支 → 提交 PR 到 GitHub
v3.0 重大架构升级：
  ❌ 移除本地 Ollama 依赖（太慢、不支持远程部署）
  ✅ AI-Client-Driven 数据工具：MCP 提供原始数据，AI客户端LLM自己分析
  ✅ 适配 ModelScope 远程部署（环境变量配置 + Docker）
  ✅ 多AI客户端适配（CodeBuddy/Trae/Cursor 均可调用）

覆盖能力：
  🛠️  工具聚合：文件/GitHub/SQLite/Git/URL/思考/记忆/Context7
  📝  对话日志：自动记录/每日总结/间隙检测
  💬  跨AI对话：CodeBuddy ↔ Trae ↔ 你 三方圆桌
  🧠  思维导图：Mermaid 格式生成、HTML 渲染
  🔄  涡轮效应：系统自改进、自动优化
  🎯  规则引擎：嵌入式规则、自动触发
  🔍  MCP发现：自动扫描、测试、集成新服务
  🧬  自我进化：代码自更新 → Git分支 → PR到GitHub ★v4.0
  📊  AI分析接口：提供数据，让AI客户端自己做深度分析
  🆔  身份识别：自动检测/注册AI客户端
  ☁️  云盘同步：坚果云/阿里云盘 WAL防冲突

架构理念：
  MCP 服务 = 数据层（CRUD工具）
  AI 客户端 LLM = 分析层（比本地Ollama更强大）
  做到真正的"AI自己分析自己的工作数据"

启动: python server.py
默认: 通过 config.yaml 配置传输方式与端口（支持环境变量覆盖）

ModelScope 部署: python server.py --host 0.0.0.0 --port $PORT
"""

import sys
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP

# ============================================================
# 初始化
# ============================================================
mcp = FastMCP("devPartner")

# 延迟导入，避免循环依赖
_core_loaded = False


def _ensure_core():
    """延迟初始化核心模块"""
    global _core_loaded
    if _core_loaded:
        return
    from core.config import ConfigManager
    from core.database import Database
    cfg = ConfigManager().load()

    # 初始化本地数据库（支持云盘WAL模式）
    local_db = cfg.database.local_db
    use_wal = cfg.cloud_sync.enabled
    Database().init_local(local_db, use_wal=use_wal)

    # 尝试连接共享数据库
    try:
        Database().init_shared(cfg.database.shared_db)
    except Exception:
        pass

    # 初始化身份管理器
    try:
        from core.identity import get_identity
        identity = get_identity()
        if cfg.identity.auto_detect and not identity.get_active_client().get("known"):
            # 尝试自动检测客户端
            import os
            ws = os.getcwd()
            detected = identity.detect_client(ws)
            if detected.get("detected") and detected["confidence"] >= 0.6:
                identity.register(detected["detected"], ws)
    except Exception:
        pass

    _core_loaded = True


# ============================================================
# 工具分类 1: 文件系统操作（原生 Python）
# ============================================================
@mcp.tool()
def fs_read_file(file_path: str, encoding: str = "utf-8") -> str:
    """读取文件内容 - 原生 Python 实现，高性能"""
    _ensure_core()
    from tools.filesystem import read_file
    return read_file(file_path, encoding)


@mcp.tool()
def fs_write_file(file_path: str, content: str, encoding: str = "utf-8", append: bool = False) -> str:
    """写入文件内容 - 原生 Python 实现"""
    _ensure_core()
    from tools.filesystem import write_file
    return write_file(file_path, content, encoding, append)


@mcp.tool()
def fs_list_directory(dir_path: str = ".", max_depth: int = 3, filter_pattern: str = "") -> str:
    """列出目录内容 - 支持递归和过滤"""
    _ensure_core()
    from tools.filesystem import list_directory
    return list_directory(dir_path, max_depth, filter_pattern)


@mcp.tool()
def fs_search_files(directory: str, pattern: str, recursive: bool = True, max_results: int = 100) -> str:
    """搜索文件 - 支持通配符"""
    _ensure_core()
    from tools.filesystem import search_files
    return search_files(directory, pattern, recursive, max_results=max_results)


@mcp.tool()
def fs_search_content(directory: str, pattern: str, file_pattern: str = "*",
                      case_sensitive: bool = False, max_results: int = 50,
                      context_lines: int = 0) -> str:
    """搜索文件内容 - 类似 ripgrep"""
    _ensure_core()
    from tools.filesystem import search_content
    return search_content(directory, pattern, file_pattern, case_sensitive, max_results, context_lines)


# ============================================================
# 工具分类 2: Git 操作（原生 Python）
# ============================================================
@mcp.tool()
def git_status(repo_path: str = ".") -> str:
    """查看 Git 仓库状态"""
    _ensure_core()
    from tools.native_tools import git_status as _git_status
    return _git_status(repo_path)


@mcp.tool()
def git_log(repo_path: str = ".", limit: int = 10) -> str:
    """查看 Git 提交历史"""
    _ensure_core()
    from tools.native_tools import git_log as _git_log
    return _git_log(repo_path, limit)


@mcp.tool()
def git_diff(repo_path: str = ".", staged: bool = False) -> str:
    """查看 Git diff"""
    _ensure_core()
    from tools.native_tools import git_diff as _git_diff
    return _git_diff(repo_path, staged)


# ============================================================
# 工具分类 3: 网络与数据库（原生 Python）
# ============================================================
@mcp.tool()
def fetch_url(url: str, method: str = "GET", headers: str = "{}",
              body: str = "", timeout: int = 30) -> str:
    """获取 URL 内容 - 使用 httpx"""
    _ensure_core()
    from tools.native_tools import fetch_url as _fetch_url
    return _fetch_url(url, method, headers, body, timeout)


@mcp.tool()
def db_query(sql: str, db_path: str = "") -> str:
    """
    执行 SQL 查询
    db_path 为空时使用共享数据库 D:/trae-archive/toptown_tracker/work_tracker.db
    """
    _ensure_core()
    from tools.native_tools import db_query as _db_query
    return _db_query(sql, db_path)


# ============================================================
# 工具分类 4: 思考与记忆（原生 Python）
# ============================================================
@mcp.tool()
def sequential_think(thought: str, thought_number: int, total_thoughts: int,
                     next_thought_needed: bool = True) -> str:
    """链式思考推理 - 分步拆解复杂问题"""
    _ensure_core()
    from tools.native_tools import sequential_think as _seq_think
    return _seq_think(thought, thought_number, total_thoughts, next_thought_needed)


@mcp.tool()
def save_memory(key: str, value: str) -> str:
    """保存知识记忆"""
    _ensure_core()
    from tools.native_tools import save_memory as _save_memory
    return _save_memory(key, value)


@mcp.tool()
def get_memory(key: str) -> str:
    """读取知识记忆"""
    _ensure_core()
    from tools.native_tools import get_memory as _get_memory
    return _get_memory(key)


@mcp.tool()
def list_memories() -> str:
    """列出所有记忆"""
    _ensure_core()
    from tools.native_tools import list_memories as _list_memories
    return _list_memories()


# ============================================================
# 工具分类 5: GitHub 搜索（subprocess 代理）
# ============================================================
@mcp.tool()
def github_search_code(query: str) -> str:
    """在 GitHub 上搜索代码（需设置 GITHUB_TOKEN 环境变量）"""
    _ensure_core()
    from tools.subprocess_tools import github_search_code as _gh_search
    return _gh_search(query)


@mcp.tool()
def github_search_repositories(query: str) -> str:
    """搜索 GitHub 仓库（需设置 GITHUB_TOKEN 环境变量）"""
    _ensure_core()
    from tools.subprocess_tools import github_search_repositories as _gh_repo
    return _gh_repo(query)


@mcp.tool()
def context7_search(query: str) -> str:
    """搜索代码库上下文（Context7 MCP）"""
    _ensure_core()
    from tools.subprocess_tools import context7_search as _ctx7
    return _ctx7(query)


# ============================================================
# 工具分类 6: 对话日志系统
# ============================================================
@mcp.tool()
def log_conversation(topic: str, task_type: str, user_intent: str, actions: str,
                     files_touched: str = "[]", problems: str = "", solutions: str = "",
                     decisions: str = "", self_reflection: str = "",
                     thinking_steps: str = "[]") -> str:
    """
    记录对话到日志系统
    files_touched, thinking_steps 应为 JSON 数组字符串
    """
    _ensure_core()
    from services.log_service import get_log_service
    log_svc = get_log_service()

    try:
        files = json.loads(files_touched) if isinstance(files_touched, str) else files_touched
    except json.JSONDecodeError:
        files = [files_touched]

    try:
        steps = json.loads(thinking_steps) if isinstance(thinking_steps, str) else thinking_steps
    except json.JSONDecodeError:
        steps = []

    data = {
        "agent": "devpartner",
        "topic": topic,
        "task_type": task_type,
        "user_intent": user_intent,
        "actions": actions,
        "files_touched": files,
        "problems": problems,
        "solutions": solutions,
        "decisions": decisions,
        "self_reflection": self_reflection,
        "thinking_steps": steps,
        "timestamp": datetime.now().isoformat(),
    }

    # 写入 pending + 直接追加
    log_svc.write_pending_log(data)
    log_file = log_svc.append_to_daily_log(data)

    # 同时写入数据库
    try:
        from core.database import get_db
        db = get_db()
        db.insert_conversation(data)
    except Exception:
        pass

    return json.dumps({"success": True, "log_file": log_file, "topic": topic}, ensure_ascii=False)


@mcp.tool()
def read_daily_log(date_str: str = "") -> str:
    """读取指定日期的日志"""
    _ensure_core()
    from services.log_service import get_log_service
    log_svc = get_log_service()
    return log_svc.read_daily_log(date_str or None)


@mcp.tool()
def list_logs() -> str:
    """列出所有日志文件"""
    _ensure_core()
    from services.log_service import get_log_service
    logs = get_log_service().list_logs()
    return json.dumps({"logs": logs, "count": len(logs)}, ensure_ascii=False)


@mcp.tool()
def check_log_gaps(date_str: str = "") -> str:
    """检查日志间隙（超过30分钟的空白）"""
    _ensure_core()
    from services.log_service import get_log_service
    result = get_log_service().gap_check(date_str or None)
    return json.dumps(result, ensure_ascii=False)


# ============================================================
# 工具分类 7: 跨AI对话系统
# ============================================================
@mcp.tool()
def check_cross_dialogue() -> str:
    """检查跨AI对话中的新消息"""
    _ensure_core()
    from services.dialogue_service import get_dialogue
    dialogue = get_dialogue()
    result = dialogue.check_for_messages()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def read_cross_dialogue() -> str:
    """读取完整的跨AI对话文件"""
    _ensure_core()
    from services.dialogue_service import get_dialogue
    return get_dialogue().read_dialogue()


@mcp.tool()
def write_cross_dialogue(content: str, to: str = "所有人", priority: str = "medium") -> str:
    """写入条目到跨AI对话"""
    _ensure_core()
    from services.dialogue_service import get_dialogue
    result = get_dialogue().write_entry(content, to, priority=priority)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def reply_cross_dialogue(entry_id: int, content: str, to: str = "所有人") -> str:
    """回复跨AI对话中的条目"""
    _ensure_core()
    from services.dialogue_service import get_dialogue
    result = get_dialogue().write_reply(entry_id, content, to)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def mark_dialogue_read(entry_ids: str) -> str:
    """标记跨AI对话条目为已读（JSON数组字符串）"""
    _ensure_core()
    from services.dialogue_service import get_dialogue
    try:
        ids = json.loads(entry_ids)
        get_dialogue().mark_as_read(ids)
        return json.dumps({"success": True, "marked": ids}, ensure_ascii=False)
    except json.JSONDecodeError:
        return json.dumps({"error": "entry_ids 应为 JSON 数组"}, ensure_ascii=False)


# ============================================================
# 工具分类 8: 思维导图生成
# ============================================================
@mcp.tool()
def generate_mindmap(title: str, data_json: str, output_format: str = "mermaid") -> str:
    """
    生成思维导图
    data_json: 结构化数据 JSON {"categories": [{"name": "分类", "items": ["项1"]}]}
    output_format: mermaid / html / txt
    """
    _ensure_core()
    from services.mindmap_service import get_mindmap, MindMapService
    mindmap = get_mindmap()

    try:
        data = json.loads(data_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "data_json 不是有效 JSON"}, ensure_ascii=False)

    mermaid_code = mindmap.generate_from_data(title, data)
    file_path = mindmap.save_mindmap(title, mermaid_code, output_format)

    return json.dumps({
        "success": True,
        "title": title,
        "format": output_format,
        "file_path": file_path,
        "mermaid_code": mermaid_code,
    }, ensure_ascii=False)


@mcp.tool()
def generate_mindmap_from_tree(title: str, tree_json: str, output_format: str = "mermaid") -> str:
    """
    从节点树生成思维导图
    tree_json: {"name": "根", "children": [{"name": "子节点", "shape": "rounded", "children": []}]}
    """
    _ensure_core()
    from services.mindmap_service import get_mindmap

    try:
        tree = json.loads(tree_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "tree_json 不是有效 JSON"}, ensure_ascii=False)

    mindmap = get_mindmap()
    mermaid_code = mindmap.generate_mermaid(title, tree)
    file_path = mindmap.save_mindmap(title, mermaid_code, output_format)

    return json.dumps({
        "success": True,
        "title": title,
        "format": output_format,
        "file_path": file_path,
        "mermaid_code": mermaid_code,
    }, ensure_ascii=False)


@mcp.tool()
def list_mindmaps() -> str:
    """列出所有生成的思维导图"""
    _ensure_core()
    from services.mindmap_service import get_mindmap
    maps = get_mindmap().list_mindmaps()
    return json.dumps({"mindmaps": maps, "count": len(maps)}, ensure_ascii=False)


# ============================================================
# 工具分类 9: AI-Client-Driven 每日总结数据接口（v3.0 替代 Ollama）
# ============================================================
# 理念：MCP 提供纯数据，AI 客户端用自己的 LLM（比本地 Ollama 强大得多）分析
# 流程：AI调 get_daily_work_data → 拿到数据 → 用自己的LLM分析 → 调 save_daily_analysis
@mcp.tool()
def get_daily_work_data(date_str: str = "") -> str:
    """
    获取指定日期的工作数据（供 AI 客户端分析用）
    
    返回当日所有对话记录、原始日志、统计数据，
    AI客户端拿到这些数据后用自己的 LLM 做深度分析总结。
    比本地 Ollama 7B 模型强大得多！
    
    date_str: 可选，格式 YYYY-MM-DD，为空则返回今日数据
    """
    _ensure_core()
    from skills.daily_summary import get_daily_work_data as _get_data
    
    target = date_str or datetime.now().strftime("%Y-%m-%d")
    data = _get_data(target)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def save_daily_analysis(analysis_json: str) -> str:
    """
    保存 AI 客户端的每日分析结果
    
    AI客户端调用 get_daily_work_data 获取数据后，
    用自己的 LLM 分析，然后调用此工具保存结果。
    
    analysis_json: JSON 字符串，格式：
    {
      "date": "YYYY-MM-DD",
      "summary": "一句话总结",
      "experience": {"deep_dive": "技术深挖", "lesson": "教训"},
      "skills": {"new_skills": [], "patterns": [], "tools": []},
      "knowledge": {"must_remember": [], "insights": []},
      "danger_signals": {"repeated_mistakes": [], "tech_debt": [], "hot_files": []},
      "tomorrow_plan": "明日计划",
      "self_analysis": {"strengths": [], "weaknesses": [], "growth_suggestions": []},
      "cross_insight": {"title": "跨AI洞察", "content": "...", "to": "trae"}
    }
    """
    _ensure_core()
    from skills.daily_summary import save_daily_analysis as _save
    
    result = _save(analysis_json)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_weekly_work_data() -> str:
    """
    获取最近 7 天的工作数据概览
    
    返回每周统计：总对话数、各天对话数、任务类型分布等
    适合 AI 客户端做周度总结
    """
    _ensure_core()
    from skills.daily_summary import get_weekly_work_data as _get_weekly
    
    data = _get_weekly()
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def get_work_schema_guide() -> str:
    """
    获取工作数据结构说明和 AI 分析指南
    
    返回数据库表结构、日志格式说明，
    帮助 AI 客户端理解数据并写出更好的分析
    """
    _ensure_core()
    guide = {
        "version": "3.0",
        "description": "devPartner 工作数据分析指南",
        "analysis_workflow": {
            "step1": "调用 get_daily_work_data(date) 获取原始工作数据",
            "step2": "用你自己的 LLM 分析这些数据（你是 Claude/GPT，比本地7B模型强）",
            "step3": "调用 save_daily_analysis(analysis_json) 保存分析结果",
        },
        "data_structure": {
            "conversations": "每次对话的结构化记录（topic/task_type/problems/solutions等）",
            "log_content": "原始 Markdown 日志全文",
            "stats": "统计数据（总对话数/类型分布）",
            "files_touched": "涉及到的所有文件路径",
            "thinking_data": "AI 的思考历程（think步骤/关键决策/自我反思）",
        },
        "analysis_dimensions": [
            "技术深度：今天解决了什么核心技术问题？",
            "经验教训：从今天的经历中学到了什么？",
            "技能成长：掌握了哪些新技能或模式？",
            "危险信号：有没有重复踩坑？技术债积累？",
            "明日方向：基于今天，明天应该优先做什么？",
            "跨AI洞察：有什么可以分享给其他AI（如Trae）的经验？",
        ],
        "save_format": {
            "summary": "string - 一句话总结",
            "experience.deep_dive": "string - 技术深挖",
            "experience.lesson": "string - 核心教训",
            "skills.new_skills": "string[] - 新技能",
            "skills.patterns": "string[] - 可复用模式",
            "knowledge.must_remember": "string[] - 必记知识点",
            "knowledge.insights": "string[] - 技术洞察",
            "danger_signals.repeated_mistakes": "string[] - 重复踩坑",
            "danger_signals.tech_debt": "string[] - 技术债",
            "danger_signals.hot_files": "string[] - 高频改动文件",
            "tomorrow_plan": "string - 明日计划",
            "self_analysis.strengths": "string[] - 优势",
            "self_analysis.weaknesses": "string[] - 短板",
            "self_analysis.growth_suggestions": "string[] - 成长建议",
            "cross_insight": "object - 跨AI分享 {title, content, to, priority}",
        },
    }
    return json.dumps(guide, ensure_ascii=False, indent=2)


# ============================================================
# 工具分类 11: 自我迭代 / 涡轮效应
# ============================================================
@mcp.tool()
def run_self_iterate(mode: str = "auto") -> str:
    """
    执行自我迭代流程，自动检测环境选择合适模式

    Args:
        mode: 运行模式
            - "auto" (默认): 自动检测 — 有 git 则走完整流程，否则走本地模式
            - "local": 本地模式 — 仅分析 + 返回变更方案，适合远程部署到 ModelScope
            - "full": 完整模式 — Git 分支 + commit + push + GitHub PR（需要本地 git 仓库和 GITHUB_TOKEN）

    本地模式流程：
        收集系统数据 → 生成改进建议 → 识别代码变更 → 返回变更方案
        → CodeBuddy 将变更写入本地项目 → 你审查后决定是否推送
    
    完整模式流程：
        收集系统数据 → 生成改进建议 → 识别代码变更 →
        创建 Git 分支 → 应用变更 → commit → push → 创建 GitHub PR
    """
    _ensure_core()
    from skills.self_iterate import execute_self_iterate

    async def _run():
        return await execute_self_iterate(mode=mode)

    try:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(asyncio.run, _run())
            result = future.result(timeout=600)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def get_pending_improvements() -> str:
    """获取待处理的系统改进建议"""
    _ensure_core()
    try:
        from core.database import get_db
        improvements = get_db().get_pending_improvements()
        return json.dumps({
            "count": len(improvements),
            "improvements": improvements,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ============================================================
# 工具分类 12: MCP 服务发现
# ============================================================
@mcp.tool()
def discover_mcp_servers() -> str:
    """自动发现新的 MCP 服务（npm search + 已知列表）"""
    _ensure_core()
    from services.discovery_service import get_discovery
    result = get_discovery().scan_and_discover()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def list_known_mcp_servers() -> str:
    """列出所有已知的 MCP 服务（含推荐）"""
    _ensure_core()
    from services.discovery_service import get_discovery
    servers = get_discovery().get_recommended_servers()
    return json.dumps(servers, ensure_ascii=False)


@mcp.tool()
def test_mcp_server(package: str) -> str:
    """测试 MCP 服务是否可用"""
    _ensure_core()
    from services.discovery_service import get_discovery
    result = get_discovery().test_server(package)
    return json.dumps(result, ensure_ascii=False)


# ============================================================
# 工具分类 13: 自我进化引擎
# ============================================================
@mcp.tool()
def self_upgrade(file_path: str, new_content: str) -> str:
    """
    自我进化：更新自身代码文件
    自动备份 → 写入新代码 → 语法验证 → 失败回滚
    """
    _ensure_core()
    from core.evolution import get_evolution
    result = get_evolution().upgrade_file(file_path, new_content)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def self_create_file(file_path: str, content: str) -> str:
    """
    自我进化：创建新文件
    自动验证 Python 语法
    """
    _ensure_core()
    from core.evolution import get_evolution
    result = get_evolution().create_new_file(file_path, content)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def self_hot_reload(module_name: str) -> str:
    """
    热重载 Python 模块
    修改代码后可用此工具让修改生效
    """
    _ensure_core()
    from core.evolution import get_evolution
    result = get_evolution().hot_reload_module(module_name)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def self_diagnose() -> str:
    """自诊断：检查服务健康状况"""
    _ensure_core()
    from core.evolution import get_evolution
    result = get_evolution().self_diagnose()
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_system_status() -> str:
    """获取系统完整状态"""
    _ensure_core()
    from core.evolution import get_evolution
    status = get_evolution().get_system_status()
    return json.dumps(status, ensure_ascii=False)


@mcp.tool()
def get_evolution_history() -> str:
    """获取自我进化历史"""
    _ensure_core()
    from core.evolution import get_evolution
    history = get_evolution().get_evolution_history()
    return json.dumps({"history": history, "count": len(history)}, ensure_ascii=False)


# ============================================================
# 工具分类 14: 规则引擎
# ============================================================
@mcp.tool()
def get_rules_summary() -> str:
    """获取所有内置规则摘要"""
    _ensure_core()
    from core.rule_engine import get_engine
    return get_engine().get_rules_summary()


@mcp.tool()
def detect_rules(user_input: str) -> str:
    """根据用户输入检测应该触发的规则"""
    _ensure_core()
    from core.rule_engine import get_engine
    triggered = get_engine().detect_triggers(user_input)
    result = [{"name": r.name, "description": r.description, "priority": r.priority}
              for r in triggered]
    return json.dumps({"triggered": result, "count": len(result)}, ensure_ascii=False)


@mcp.tool()
def execute_system_command(command: str, cwd: str = ".", timeout: int = 60) -> str:
    """执行系统命令"""
    _ensure_core()
    from tools.native_tools import execute_command as _exec
    return _exec(command, cwd, timeout)


# ============================================================
# 工具分类 15: SQLite 数据总结
# ============================================================
@mcp.tool()
def get_db_stats() -> str:
    """获取数据库统计信息"""
    _ensure_core()
    try:
        from core.database import get_db
        db = get_db()

        tables = db.query_local(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )

        stats = {}
        for t in tables:
            tname = t.get("name", "")
            if tname:
                cnt = db.query_local(f"SELECT COUNT(*) as cnt FROM [{tname}]")
                stats[tname] = cnt[0]["cnt"] if cnt else 0

        daily = db.get_daily_stats()
        return json.dumps({
            "tables": stats,
            "today": daily,
            "total_conversations": stats.get("conversations", 0),
            "pending_improvements": stats.get("system_improvements", 0),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@mcp.tool()
def search_conversations(query: str, limit: int = 20) -> str:
    """搜索历史对话记录"""
    _ensure_core()
    try:
        from core.database import get_db
        db = get_db()
        results = db.query_local(
            """SELECT * FROM conversations 
               WHERE topic LIKE ? OR user_intent LIKE ? OR actions LIKE ?
               ORDER BY timestamp DESC LIMIT ?""",
            (f"%{query}%", f"%{query}%", f"%{query}%", limit),
        )
        return json.dumps({
            "results": results,
            "count": len(results),
            "query": query,
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ============================================================
# 工具分类 16: 多AI身份识别与注册
# ============================================================
@mcp.tool()
def devpartner_register(client_name: str, workspace_root: str = "") -> str:
    """
    注册当前AI客户端身份
    
    让 devPartner 知道是谁在调用它。
    client_name: 'codebuddy' | 'trae' | 'cursor' | 自定义名称
    workspace_root: 项目工作区根路径（可选，用于自动识别）
    """
    _ensure_core()
    from core.identity import get_identity
    identity = get_identity()
    result = identity.register(client_name, workspace_root)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def devpartner_whoami() -> str:
    """
    查询当前客户端身份
    
    返回当前已注册的客户端信息，或提示需要注册
    """
    _ensure_core()
    from core.identity import get_identity
    identity = get_identity()
    client = identity.get_active_client()
    recent = identity.get_recent_calls(5)
    return json.dumps({
        "client": client,
        "recent_calls": recent,
    }, ensure_ascii=False)


@mcp.tool()
def devpartner_list_clients() -> str:
    """列出所有已注册的AI客户端"""
    _ensure_core()
    from core.identity import get_identity
    clients = get_identity().get_all_clients()
    return json.dumps({"clients": clients, "count": len(clients)}, ensure_ascii=False)


@mcp.tool()
def devpartner_detect_client(workspace_path: str = "") -> str:
    """
    自动检测AI客户端身份
    
    扫描工作区中的 .codebuddy/ .trae/ .cursor/ 等目录
    """
    _ensure_core()
    from core.identity import get_identity
    import os
    ws = workspace_path or os.getcwd()
    result = get_identity().detect_client(ws)
    return json.dumps(result, ensure_ascii=False)


# ============================================================
# 工具分类 17: 配置向导（Setup Wizard）
# ============================================================
@mcp.tool()
def devpartner_setup() -> str:
    """
    运行配置向导
    
    检测是否需要配置，扫描环境，生成配置建议。
    返回结构化结果供AI展示给用户选择。
    """
    _ensure_core()
    from services.setup_service import get_setup

    wizard = get_setup()

    # 1. 检查是否需要设置
    check = wizard.check_setup_needed()
    if not check["needed"]:
        return json.dumps({
            "status": "ok",
            "message": "devPartner 已正确配置，无需额外设置",
            "config_file": str(wizard.config_path),
        }, ensure_ascii=False)

    # 2. 扫描环境
    scan = wizard.scan_environment()

    # 3. 生成建议
    suggestions = wizard.generate_suggestions(scan)

    return json.dumps({
        "status": "setup_needed",
        "reasons": check["reasons"],
        "scan": {
            "cloud_drives": scan["cloud_drives"],
            "ai_clients": scan["ai_clients"],
            "existing_databases": scan["existing_databases"],
            "workspace_projects": scan["workspace_projects"],
            "suggested_data_root": scan["suggested_data_root"],
        },
        "suggestions": suggestions,
        "next_step": "请查看扫描结果，告诉我你想使用哪个数据存储路径（或直接确认建议的路径）",
    }, ensure_ascii=False)


@mcp.tool()
def devpartner_scan() -> str:
    """
    完整环境扫描（不触发设置向导）
    
    扫描云盘、AI客户端、已有数据库、工作区项目
    """
    _ensure_core()
    from services.setup_service import get_setup
    scan = get_setup().scan_environment()
    return json.dumps(scan, ensure_ascii=False)


@mcp.tool()
def devpartner_apply_config(data_root: str = "",
                             clients_json: str = "[]") -> str:
    """
    应用配置更改
    
    data_root: 数据存储根路径（如 D:/Nutstore/devPartner-data）
    clients_json: 客户端注册列表 JSON, 如 [{"name":"codebuddy","workspace":"D:/project"}]
    """
    _ensure_core()
    from services.setup_service import get_setup

    try:
        clients = json.loads(clients_json)
    except json.JSONDecodeError:
        clients = []

    choices = {}
    if data_root:
        choices["data_root"] = data_root
    if clients:
        choices["clients"] = clients

    result = get_setup().apply_config(choices)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def devpartner_generate_mcp_snippet() -> str:
    """
    生成 MCP 连接配置片段
    
    返回可直接粘贴到 CodeBuddy/Trae 的 mcp.json 中的配置
    """
    _ensure_core()
    from services.setup_service import get_setup
    from core.config import get_config
    cfg = get_config()
    snippet = get_setup().generate_mcp_config_snippet(cfg.host, cfg.port)
    return json.dumps({
        "mcp_config": {
            "devpartner": snippet,
        },
        "instruction": "将以上配置添加到你的 mcp.json 文件的 mcpServers 字段中",
    }, ensure_ascii=False)


# ============================================================
# 工具分类 18: 云同步存储管理
# ============================================================
@mcp.tool()
def devpartner_cloud_info() -> str:
    """
    检测云盘安装情况
    
    扫描坚果云/阿里云盘/OneDrive/百度网盘等
    """
    _ensure_core()
    from core.cloud_sync import CloudDriveDetector
    drives = CloudDriveDetector.detect_all()
    result = []
    for d in drives:
        result.append({
            "name": d.name,
            "icon": d.icon,
            "path": d.path,
            "status": d.status,
        })

    suggested = CloudDriveDetector.suggest_sync_path()
    return json.dumps({
        "drives": result,
        "found_count": sum(1 for d in drives if d.status == "found_accessible"),
        "suggested_sync_path": suggested,
    }, ensure_ascii=False)


@mcp.tool()
def devpartner_validate_path(path: str) -> str:
    """
    验证路径是否可用（用于配置前的检查）
    """
    _ensure_core()
    from services.setup_service import get_setup
    result = get_setup().validate_path(path)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def devpartner_check_sync_status() -> str:
    """
    检查云同步状态
    
    检查数据库WAL模式、同步目录状态等
    """
    _ensure_core()
    from core.config import get_config
    from pathlib import Path
    import os

    cfg = get_config()
    data_root = cfg.cloud_sync.data_root or "data"

    status = {
        "wal_enabled": cfg.cloud_sync.enabled,
        "data_root": data_root,
        "data_root_exists": Path(data_root).exists(),
        "sync_drive": cfg.cloud_sync.sync_drive,
        "local_db": str(Path(cfg.database.local_db)),
        "local_db_exists": Path(cfg.database.local_db).exists(),
        "shared_db": str(Path(cfg.database.shared_db)),
        "shared_db_exists": Path(cfg.database.shared_db).exists(),
    }

    # 检查 WAL 文件
    wal_path = Path(str(cfg.database.local_db) + "-wal")
    shm_path = Path(str(cfg.database.local_db) + "-shm")
    status["wal_file_exists"] = wal_path.exists()
    status["shm_file_exists"] = shm_path.exists()
    if wal_path.exists():
        status["wal_size_bytes"] = wal_path.stat().st_size

    return json.dumps(status, ensure_ascii=False)


# ============================================================
# 工具分类 19: AI客户端配置分析与优化
# ============================================================
@mcp.tool()
def devpartner_analyze_ai(client_name: str = "", workspace_root: str = "") -> str:
    """
    分析AI客户端配置并给出优化建议
    
    扫描 CodeBuddy/Trae 的 MCP 配置、Rules、Skills 等，
    发现可优化点和冗余配置。
    
    client_name: 要分析的客户端名称，为空则分析当前活跃客户端
    workspace_root: 工作区路径，为空则自动检测
    """
    _ensure_core()
    from services.ai_optimizer import get_optimizer
    from core.identity import get_identity
    import os

    optimizer = get_optimizer()
    identity = get_identity()

    # 确定分析目标
    if not client_name:
        active = identity.get_active_client()
        if active.get("known"):
            client_name = active["client"]
        else:
            return json.dumps({
                "error": "未知客户端，请先注册 (devpartner_register) 或指定 client_name",
                "known_clients": identity.get_all_clients(),
            }, ensure_ascii=False)

    if not workspace_root:
        # 尝试从注册表获取
        for c in identity.get_all_clients():
            if c["name"] == client_name:
                workspace_root = c.get("workspace", "")
                break
        if not workspace_root:
            workspace_root = os.getcwd()

    analysis = optimizer.analyze_client(client_name, workspace_root)
    return json.dumps(analysis, ensure_ascii=False)


@mcp.tool()
def devpartner_get_suggestions(client_name: str = "") -> str:
    """
    获取待处理的AI配置优化建议
    
    如果之前运行过 devpartner_analyze_ai，
    可以查看尚未应用的优化建议
    """
    _ensure_core()
    from services.ai_optimizer import get_optimizer
    from core.identity import get_identity

    optimizer = get_optimizer()
    identity = get_identity()

    if not client_name:
        active = identity.get_active_client()
        if active.get("known"):
            client_name = active["client"]
        else:
            client_name = "unknown"

    summary = optimizer.get_summary(client_name)
    pending = optimizer.get_pending_suggestions()

    return json.dumps({
        "summary": summary,
        "pending_suggestions": pending,
    }, ensure_ascii=False)


# ============================================================
# 启动服务
# ============================================================
if __name__ == "__main__":
    # Windows CMD 兼容: 强制 UTF-8 输出
    import io as _io
    if sys.platform == "win32":
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    
    # 读取配置（支持环境变量覆盖）
    from core.config import ConfigManager
    cfg = ConfigManager().load()
    
    print("=" * 60)
    print("  🧬 devPartner - 自我进化 MCP 服务 v4.0")
    print("=" * 60)
    print(f"  传输: {cfg.transport}")
    print(f"  地址: {cfg.host}:{cfg.port}")
    print(f"  工具数: 70+ (19个分类)")
    print()
    print("  能力:")
    print("    🛠️  工具聚合: 文件/GitHub/SQLite/Git/URL/思考/记忆")
    print("    📝  对话日志: 自动记录/每日总结/间隙检测")
    print("    💬  跨AI对话: 三方圆桌/消息检测/自动回复")
    print("    🧠  思维导图: Mermaid生成/HTML渲染")
    print("    🔄  涡轮效应: 系统自改进/自动优化")
    print("    🔍  MCP发现: 自动扫描/测试/集成新服务")
    print("    🧬  自我进化: 代码自更新 → Git分支 → PR到GitHub ★v4.0")
    print("    📊  AI分析接口: 数据提供给AI客户端自行分析 ★v3.0")
    print("    🆔  身份识别: CodeBuddy/Trae/Cursor 自动检测")
    print("    ☁️  云盘同步: 坚果云/阿里云盘 WAL防冲突")
    print("    🧙  配置向导: 智能检测/引导配置/路径验证")
    print("    🎯  AI优化: 客户端配置分析/去重建议")
    print("=" * 60)

    # 初始化核心
    _ensure_core()
    print("  ✅ 核心模块已初始化")
    print("  ✅ 本地数据库已就绪")
    print(f"  🚀 服务启动中...")
    print("=" * 60)

    mcp.run(transport=cfg.transport, host=cfg.host, port=cfg.port)
