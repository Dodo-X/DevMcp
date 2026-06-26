"""
自我迭代技能 v4.0 — 提交 PR 到 GitHub
======================================
v4.0 变更：
  - ❌ 移除"仅生成建议存DB"的旧模式
  - ✅ 进化流程改为：收集数据 → 生成改进 → 创建分支 → 应用变更 → 提交 PR 到 GitHub
  - ✅ 自动 git 操作：branch / add / commit / push / create PR
  - ✅ 通过 GitHub API 创建 Pull Request（需 GITHUB_TOKEN）
"""
import json
import os
import re
import subprocess
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional


async def execute_self_iterate(context: dict = None) -> dict:
    """执行自我迭代流程 → 最终提交 PR 到 GitHub"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "steps": [],
        "improvements_applied": [],
        "suggestions_generated": [],
        "pr_url": None,
        "branch_name": None,
    }

    # Step 1: 收集系统数据
    system_data = _collect_system_data()
    result["steps"].append({"step": "collect_data", "status": "ok"})
    result["system_data"] = system_data

    # Step 2: 生成数据驱动的改进建议（含可执行的代码变更）
    suggestions = []
    try:
        suggestions = _generate_data_driven_suggestions(system_data)
        result["suggestions_generated"] = suggestions

        # 保存建议到数据库（可追溯）
        for suggestion in suggestions:
            try:
                from core.database import get_db
                db = get_db()
                db.insert_improvement(
                    category=suggestion.get("category", "general"),
                    suggestion=suggestion.get("suggestion", ""),
                    priority=suggestion.get("priority", "medium"),
                )
            except Exception:
                pass

        result["steps"].append({"step": "generate_suggestions", "status": "ok",
                                 "count": len(suggestions)})
    except Exception as e:
        result["steps"].append({"step": "generate_suggestions", "status": "error",
                                 "error": str(e)})

    # Step 3: 识别可执行的代码变更
    code_changes = _identify_code_changes(suggestions, system_data)
    result["code_changes"] = code_changes

    if not code_changes:
        result["steps"].append({"step": "identify_changes", "status": "ok",
                                 "note": "无可自动执行的代码变更，跳过 PR 创建"})
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    result["steps"].append({"step": "identify_changes", "status": "ok",
                             "change_count": len(code_changes)})

    # Step 4: 创建 Git 分支
    branch_name = f"devpartner-evolve-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    result["branch_name"] = branch_name

    try:
        _git_create_branch(branch_name)
        result["steps"].append({"step": "create_branch", "status": "ok",
                                 "branch": branch_name})
    except Exception as e:
        result["steps"].append({"step": "create_branch", "status": "error",
                                 "error": str(e)})
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # Step 5: 应用代码变更
    try:
        applied = _apply_code_changes(code_changes)
        result["improvements_applied"] = applied
        result["steps"].append({"step": "apply_changes", "status": "ok",
                                 "applied_count": len(applied)})
    except Exception as e:
        result["steps"].append({"step": "apply_changes", "status": "error",
                                 "error": str(e)})
        # 回滚分支
        _git_checkout_previous()
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # Step 6: Git add + commit + push
    commit_msg = _build_commit_message(suggestions, code_changes)
    try:
        _git_add_all()
        _git_commit(commit_msg)
        result["steps"].append({"step": "git_commit", "status": "ok",
                                 "message": commit_msg})
    except Exception as e:
        result["steps"].append({"step": "git_commit", "status": "error",
                                 "error": str(e)})
        _git_checkout_previous()
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    try:
        push_output = _git_push(branch_name)
        result["steps"].append({"step": "git_push", "status": "ok",
                                 "output": push_output[:500]})
    except Exception as e:
        result["steps"].append({"step": "git_push", "status": "error",
                                 "error": str(e)})
        report = _generate_iteration_report(result)
        result["report"] = report
        return result

    # Step 7: 创建 GitHub Pull Request
    try:
        pr_result = _create_github_pr(branch_name, _get_base_branch(), commit_msg,
                                       suggestions)
        result["pr_url"] = pr_result.get("html_url", "")
        result["pr_number"] = pr_result.get("number")
        result["steps"].append({"step": "create_pr", "status": "ok",
                                 "pr_url": result["pr_url"],
                                 "pr_number": result["pr_number"]})
    except Exception as e:
        result["steps"].append({"step": "create_pr", "status": "error",
                                 "error": str(e)})

    # Step 8: 清理：切回原分支
    try:
        _git_checkout_previous()
    except Exception:
        pass

    # Step 9: 生成改进报告
    report = _generate_iteration_report(result)
    result["report"] = report

    return result


def _collect_system_data() -> dict:
    """收集系统当前状态数据"""
    data = {}

    # 配置信息
    try:
        from core.config import get_config
        cfg = get_config()
        data["config"] = {
            "version": cfg.version,
            "evolution_enabled": cfg.evolution.enabled,
            "cloud_sync_enabled": cfg.cloud_sync.enabled,
            "identity_auto_detect": cfg.identity.auto_detect,
        }
    except Exception:
        data["config"] = {"error": "配置加载失败"}

    # 规则统计
    try:
        from core.rule_engine import get_engine
        engine = get_engine()
        data["rules"] = {
            "total": len(engine.get_all()),
            "auto_triggers": len(engine.get_auto_triggers()),
            "names": list(engine.get_all().keys()),
        }
    except Exception:
        data["rules"] = {}

    # 数据库统计
    try:
        from core.database import get_db
        db = get_db()
        conversations = db.query_local("SELECT COUNT(*) as cnt FROM conversations")
        improvements = db.query_local("SELECT COUNT(*) as cnt FROM system_improvements WHERE status='pending'")
        data["database"] = {
            "conversations": conversations[0]["cnt"] if conversations else 0,
            "pending_improvements": improvements[0]["cnt"] if improvements else 0,
        }
    except Exception:
        data["database"] = {}

    # 服务发现统计
    try:
        from services.discovery_service import get_discovery
        discovery = get_discovery()
        data["mcp_servers"] = discovery.get_scan_status()
    except Exception:
        data["mcp_servers"] = {}

    # 跨AI对话统计
    try:
        from services.dialogue_service import get_dialogue
        dialogue = get_dialogue()
        data["dialogue"] = dialogue.get_statistics()
    except Exception:
        data["dialogue"] = {}

    return data


def _generate_data_driven_suggestions(system_data: dict) -> list[dict]:
    """
    基于系统数据生成改进建议（数据驱动，不依赖Ollama）
    
    分析维度：
    - 数据库膨胀：对话数过多需要归档
    - 规则健康度：规则触发频率
    - MCP服务状态：可用服务数
    - 跨AI对话活跃度：消息数/未读数
    """
    suggestions = []

    # 1. 数据库健康检查
    db_data = system_data.get("database", {})
    conv_count = db_data.get("conversations", 0)
    if conv_count > 1000:
        suggestions.append({
            "category": "database_health",
            "suggestion": f"数据库对话记录已达 {conv_count} 条，建议归档清理",
            "priority": "medium",
        })

    pending_improvements = db_data.get("pending_improvements", 0)
    if pending_improvements > 20:
        suggestions.append({
            "category": "maintenance",
            "suggestion": f"有 {pending_improvements} 条待处理改进建议，建议逐步应用或清理",
            "priority": "high" if pending_improvements > 50 else "medium",
        })

    # 2. 规则引擎检查
    rules = system_data.get("rules", {})
    if rules.get("total", 0) == 0:
        suggestions.append({
            "category": "rule_engine",
            "suggestion": "规则引擎中没有规则，建议添加至少一个自动触发规则",
            "priority": "medium",
        })

    # 3. MCP服务发现建议
    mcp = system_data.get("mcp_servers", {})
    known = mcp.get("known", 0)
    if known < 5:
        suggestions.append({
            "category": "mcp_discovery",
            "suggestion": f"已知 MCP 服务仅 {known} 个，建议运行 discover_mcp_servers 扩充服务库",
            "priority": "high" if known == 0 else "medium",
        })

    # 4. 跨AI对话健康度
    dialogue = system_data.get("dialogue", {})
    unread = dialogue.get("unread", 0)
    if unread > 5:
        suggestions.append({
            "category": "cross_dialogue",
            "suggestion": f"跨AI对话有 {unread} 条未读消息，建议及时查看和回复",
            "priority": "high",
        })

    # 5. 配置建议
    config = system_data.get("config", {})
    if not config.get("cloud_sync_enabled"):
        suggestions.append({
            "category": "setup",
            "suggestion": "云同步未启用，建议运行 devpartner_setup 配置数据同步",
            "priority": "medium",
        })

    return suggestions


def _identify_code_changes(suggestions: list[dict],
                            system_data: dict) -> list[dict]:
    """
    将改进建议转化为可执行的代码变更

    返回变更列表，每条包含：
    - file: 目标文件路径（相对项目根目录）
    - action: create / modify / delete
    - description: 变更描述
    - content: 新内容（create/modify 时）
    """
    changes = []

    rules = system_data.get("rules", {})
    rule_names = rules.get("names", [])

    # 1. 规则引擎为空 → 添加一个默认规则文件
    if rules.get("total", 0) == 0:
        default_rule = '''"""
devPartner 自动生成规则
由自我进化引擎生成，可自行修改
"""
from core.rule_engine import Rule


RULES = [
    Rule(
        name="daily_summary_reminder",
        description="每日下班前提醒记录工作总结",
        triggers=["总结", "今天做了什么", "下班", "工作总结", "daily summary"],
        priority="medium",
        auto_trigger=True,
        action="suggest_daily_summary",
    ),
    Rule(
        name="dependency_check",
        description="修改 requirements.txt 后提醒检查依赖",
        triggers=["pip install", "requirements", "依赖"],
        priority="low",
        auto_trigger=False,
        action="check_dependencies",
    ),
    Rule(
        name="git_commit_reminder",
        description="大量文件变更后提醒提交",
        triggers=["git commit", "提交", "更新了很多"],
        priority="high",
        auto_trigger=True,
        action="remind_git_commit",
    ),
]
'''
        existing_default = "default" in rule_names if rule_names else False
        if not existing_default:
            changes.append({
                "file": "rules/default_rules.py",
                "action": "create",
                "description": "添加默认自动触发规则（每日总结提醒 / 依赖检查 / Git提交提醒）",
                "content": default_rule,
            })

    # 2. MCP 服务太少 → 更新 config.yaml 自动补全已知服务列表
    mcp = system_data.get("mcp_servers", {})
    known = mcp.get("known", 0)
    if known < 5:
        # 读取配置文件，追加推荐的服务
        changes.append({
            "file": "config.yaml",
            "action": "modify",
            "description": f"自动扩充 known_mcp_servers（当前仅 {known} 个，推荐添加更多免费服务）",
            "merge_mcp_servers": [
                "@modelcontextprotocol/server-filesystem",
                "@modelcontextprotocol/server-github",
                "@modelcontextprotocol/server-sequential-thinking",
                "@modelcontextprotocol/server-fetch",
                "@modelcontextprotocol/server-sqlite",
                "@modelcontextprotocol/server-git",
                "@modelcontextprotocol/server-memory",
                "@upstash/context7-mcp",
                "@anthropic/mcp-server-brave-search",
                "@anthropic/mcp-server-playwright",
                "@modelcontextprotocol/server-postgres",
            ],
        })

    # 3. 数据库膨胀 → 添加归档脚本
    db_data = system_data.get("database", {})
    conv_count = db_data.get("conversations", 0)
    if conv_count > 1000:
        archive_script = '''"""
数据库归档脚本（由 devPartner 自我进化引擎生成）
用途：将超过 30 天的旧对话记录归档
"""
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta


def archive_old_conversations(db_path: str, days: int = 30):
    """归档旧对话记录到 archive 表"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    # 确保 archive 表存在
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations_archive (
            id INTEGER PRIMARY KEY,
            agent TEXT, topic TEXT, task_type TEXT,
            user_intent TEXT, actions TEXT,
            problems TEXT, solutions TEXT,
            decisions TEXT, timestamp TEXT,
            archived_at TEXT
        )
    """)

    # 移动旧记录
    cursor.execute("""
        INSERT INTO conversations_archive
        SELECT *, ? FROM conversations WHERE timestamp < ?
    """, (datetime.now().isoformat(), cutoff))

    moved = cursor.rowcount

    # 删除原表中的旧记录
    cursor.execute("DELETE FROM conversations WHERE timestamp < ?", (cutoff,))
    conn.commit()
    conn.close()

    print(f"归档完成: {moved} 条记录已移至 conversations_archive")
    return moved


if __name__ == "__main__":
    import sys
    db = sys.argv[1] if len(sys.argv) > 1 else "data/devpartner.db"
    archive_old_conversations(db)
'''
        changes.append({
            "file": "tools/db_archive.py",
            "action": "create",
            "description": f"数据库有 {conv_count} 条记录，添加归档脚本 tools/db_archive.py",
            "content": archive_script,
        })

    return changes


def _apply_code_changes(changes: list[dict]) -> list[dict]:
    """将代码变更实际写入文件系统"""
    applied = []
    project_root = Path(__file__).parent.parent

    for change in changes:
        action = change.get("action")
        file_path = project_root / change["file"]
        description = change.get("description", "")

        try:
            if action == "create":
                file_path.parent.mkdir(parents=True, exist_ok=True)
                if not file_path.exists():
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(change.get("content", ""))
                    applied.append({
                        "file": change["file"],
                        "action": "create",
                        "description": description,
                        "applied": True,
                    })

            elif action == "modify":
                if "merge_mcp_servers" in change:
                    # 特殊处理：合并 MCP 服务到 config.yaml
                    _merge_mcp_servers_to_config(file_path,
                                                  change["merge_mcp_servers"])
                    applied.append({
                        "file": change["file"],
                        "action": "modify",
                        "description": description,
                        "applied": True,
                    })
                elif "content" in change:
                    with open(file_path, "w", encoding="utf-8") as f:
                        f.write(change["content"])
                    applied.append({
                        "file": change["file"],
                        "action": "modify",
                        "description": description,
                        "applied": True,
                    })

            elif action == "delete":
                if file_path.exists():
                    file_path.unlink()
                    applied.append({
                        "file": change["file"],
                        "action": "delete",
                        "description": description,
                        "applied": True,
                    })

        except Exception as e:
            applied.append({
                "file": change["file"],
                "action": action,
                "description": description,
                "applied": False,
                "error": str(e),
            })

    return applied


def _merge_mcp_servers_to_config(config_path: Path, new_servers: list[str]):
    """向 config.yaml 合并新的 MCP 服务列表（去重追加）"""
    if not config_path.exists():
        return

    with open(config_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 收集已有的服务器
    existing = set()
    in_servers = False
    result_lines = []
    indent = ""

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("known_mcp_servers:"):
            in_servers = True
            # 获取缩进
            indent = line[:len(line) - len(line.lstrip())] + "  "
            result_lines.append(line)
            continue
        if in_servers:
            if stripped.startswith("- "):
                server = stripped[2:].strip().strip('"').strip("'")
                existing.add(server)
                result_lines.append(line)
                continue
            else:
                # known_mcp_servers 列表结束
                # 追加新服务
                for srv in new_servers:
                    if srv not in existing:
                        result_lines.append(f'{indent}- "{srv}"\n')
                in_servers = False
        result_lines.append(line)

    # 如果列表中一直到最后还在 in_servers
    if in_servers:
        for srv in new_servers:
            if srv not in existing:
                result_lines.append(f'{indent}- "{srv}"\n')

    with open(config_path, "w", encoding="utf-8") as f:
        f.writelines(result_lines)


# ================================================================
# Git 操作
# ================================================================

_PREVIOUS_BRANCH = None


def _run_git(args: list, repo_path: str = ".") -> subprocess.CompletedProcess:
    """执行 git 命令"""
    result = subprocess.run(
        ["git", "-C", repo_path] + args,
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git 命令执行失败")
    return result


def _git_create_branch(branch_name: str, repo_path: str = "."):
    """创建并切换到新分支（记录原分支以便回滚）"""
    global _PREVIOUS_BRANCH
    # 记录当前分支
    r = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=15,
    )
    _PREVIOUS_BRANCH = r.stdout.strip()
    _run_git(["checkout", "-b", branch_name], repo_path)


def _git_checkout_previous(repo_path: str = "."):
    """切回当前进化操作之前的原始分支"""
    global _PREVIOUS_BRANCH
    if _PREVIOUS_BRANCH:
        try:
            _run_git(["checkout", _PREVIOUS_BRANCH], repo_path)
        except RuntimeError:
            pass


def _git_add_all(repo_path: str = "."):
    """暂存所有变更"""
    _run_git(["add", "-A"], repo_path)


def _git_commit(message: str, repo_path: str = "."):
    """提交变更"""
    _run_git(["commit", "-m", message], repo_path)


def _git_push(branch_name: str, repo_path: str = "."):
    """推送分支到 origin"""
    result = _run_git(["push", "-u", "origin", branch_name], repo_path)
    return result.stdout + result.stderr


def _get_base_branch(repo_path: str = ".") -> str:
    """获取基础分支名（优先 master，其次 main）"""
    for name in ["master", "main"]:
        r = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", f"origin/{name}"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return name
    return "master"


def _get_github_repo(repo_path: str = ".") -> tuple:
    """从 git remote 解析 GitHub owner/repo"""
    r = subprocess.run(
        ["git", "-C", repo_path, "remote", "get-url", "origin"],
        capture_output=True, text=True, timeout=15,
    )
    url = r.stdout.strip()
    # 支持 https://github.com/owner/repo.git 和 git@github.com:owner/repo.git
    m = re.search(r'github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$', url)
    if not m:
        raise RuntimeError(f"无法从 remote URL 解析 GitHub 仓库: {url}")
    return m.group(1), m.group(2)


def _build_commit_message(suggestions: list[dict],
                           code_changes: list[dict]) -> str:
    """根据建议和变更生成提交信息"""
    categories = set(s.get("category", "") for s in suggestions)
    lines = ["🤖 devPartner 自我进化", ""]
    for change in code_changes:
        lines.append(f"- {change.get('action', 'modify')}: {change.get('description', change.get('file', ''))}")
    lines.append("")
    lines.append(f"分析维度: {', '.join(categories) if categories else '系统巡检'}")
    lines.append("Auto-generated by devPartner self-evolution engine")
    return "\n".join(lines)


# ================================================================
# GitHub API
# ================================================================

def _create_github_pr(branch_name: str, base_branch: str,
                       title: str, suggestions: list[dict]) -> dict:
    """通过 GitHub REST API 创建 Pull Request"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("请设置 GITHUB_TOKEN 环境变量 (https://github.com/settings/tokens)")

    owner, repo = _get_github_repo()

    # 构建 PR body
    body_lines = ["## 🤖 devPartner 自我进化 PR", "",
                   "本 PR 由 devPartner 自我进化引擎自动生成。", "",
                   "### 分析维度"]
    for s in suggestions:
        body_lines.append(f"- **{s.get('category', '')}**: {s.get('suggestion', '')}")

    body_lines.extend(["", "### 变更文件", ""])
    body_lines.append("详见 commit diff。")

    # 用 httpx 调用 GitHub API
    import httpx
    url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "title": title.split("\n")[0][:256],  # PR 标题用第一行
        "body": "\n".join(body_lines),
        "head": branch_name,
        "base": base_branch,
    }

    resp = httpx.post(url, json=payload, headers=headers, timeout=30)
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub API 返回 {resp.status_code}: {resp.text[:500]}")

    return resp.json()


# ================================================================
# 报告生成
# ================================================================

def _generate_iteration_report(result: dict) -> str:
    """生成自我迭代报告（v4.0 含 PR 信息）"""
    lines = [
        "# 🧬 devPartner 自我进化报告",
        f"**生成时间**: {result['timestamp']}",
        "",
    ]

    # PR 信息
    if result.get("pr_url"):
        lines.append(f"## 🔗 Pull Request")
        lines.append(f"- **PR**: [#{result.get('pr_number', '?')}]({result['pr_url']})")
        lines.append(f"- **分支**: `{result.get('branch_name', '')}`")
        lines.append("")
    elif result.get("branch_name"):
        lines.append(f"## 🌿 分支")
        lines.append(f"- **分支名**: `{result['branch_name']}`")
        lines.append(f"- **状态**: PR 创建失败或未推送")
        lines.append("")

    # 执行步骤
    lines.append("## 📋 执行步骤")
    for step in result.get("steps", []):
        step_name = step.get("step", "")
        status = step.get("status", "")
        icon = "✅" if status == "ok" else "❌"
        detail = ""
        if "branch" in step:
            detail = f" → `{step['branch']}`"
        elif "count" in step:
            detail = f" ({step['count']} 条)"
        elif "note" in step:
            detail = f" — {step['note']}"
        elif "error" in step:
            detail = f" — {step['error']}"
        elif "pr_url" in step:
            detail = f" → {step['pr_url']}"
        elif "message" in step:
            detail = f" → {step['message'][:80]}..."
        lines.append(f"- {icon} **{step_name}**{detail}")

    lines.append("")

    # 分析结果
    lines.append("## 🔍 分析结果")
    suggestions = result.get("suggestions_generated", [])
    if suggestions:
        for s in suggestions:
            cat = s.get("category", "general")
            sug = s.get("suggestion", "")
            pri = s.get("priority", "")
            label = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(pri, "")
            lines.append(f"- {label} **[{cat}]** {sug}")
    else:
        lines.append("- 系统运行正常，未发现需改进项")

    lines.append("")

    # 代码变更
    lines.append("## 💻 代码变更")
    changes = result.get("code_changes", [])
    if changes:
        for ch in changes:
            lines.append(f"- `{ch.get('file', '?')}` ({ch.get('action', '')}): {ch.get('description', '')}")
    else:
        lines.append("- 本次无需代码变更")

    lines.append("")

    # 应用结果
    lines.append("## ⚡ 应用结果")
    applied = result.get("improvements_applied", [])
    if applied:
        for imp in applied:
            status = "✅ 已应用" if imp.get("applied") else "❌ 失败"
            lines.append(f"- {status} - `{imp.get('file', '')}`: {imp.get('description', '')}")
            if imp.get("error"):
                lines.append(f"  - 错误: {imp['error']}")
    else:
        lines.append("- 本次未应用代码变更")

    return "\n".join(lines)


async def check_and_improve() -> dict:
    """检查并执行改进（轻量版，适合频繁调用）"""
    try:
        from core.database import get_db
        db = get_db()

        # 检查待处理的改进
        pending = db.get_pending_improvements()
        if not pending:
            return {"has_pending": False, "count": 0}

        # 获取最高优先级的改进
        high_priority = [i for i in pending if i.get("priority") == "high"]
        return {
            "has_pending": True,
            "count": len(pending),
            "high_priority": len(high_priority),
            "top_suggestion": high_priority[0].get("suggestion", "") if high_priority else "",
        }
    except Exception as e:
        return {"error": str(e)}
