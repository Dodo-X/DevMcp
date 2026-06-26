"""
🔍 服务发现工具集 — 5 个工具

设计原则：
  - 提供 MCP 服务发现、测试、配置生成能力
  - 内置常用 MCP 服务知识库
  - 规则摘要作为便捷入口（详细定义在 agent 层）
"""

import json
import subprocess
import time
from datetime import datetime
from typing import Dict, Any

# 内置的常用 MCP 服务列表（静态知识库）
KNOWN_MCP_SERVERS = [
    {"name": "Filesystem", "package": "@modelcontextprotocol/server-filesystem",
     "category": "文件系统", "rating": 5.0, "description": "安全的文件系统访问", "recommended": True},
    {"name": "GitHub", "package": "@modelcontextprotocol/server-github",
     "category": "开发工具", "rating": 4.8, "description": "GitHub API 集成", "recommended": True},
    {"name": "PostgreSQL", "package": "@modelcontextprotocol/server-postgres",
     "category": "数据库", "rating": 4.5, "description": "PostgreSQL 查询", "recommended": False},
    {"name": "Puppeteer", "package": "@modelcontextprotocol/server-puppeteer",
     "category": "浏览器", "rating": 4.3, "description": "浏览器自动化", "recommended": False},
    {"name": "Context7", "package": "@upstash/context7-mcp",
     "category": "AI 助手", "rating": 4.9, "description": "代码上下文理解", "recommended": True},
    {"name": "Brave Search", "package": "@modelcontextprotocol/server-brave-search",
     "category": "搜索", "rating": 4.6, "description": "网页搜索", "recommended": True},
    {"name": "Memory", "package": "@modelcontextprotocol/server-memory",
     "category": "知识管理", "rating": 4.4, "description": "知识图谱", "recommended": False},
    {"name": "SQLite", "package": "@modelcontextprotocol/server-sqlite",
     "category": "数据库", "rating": 4.2, "description": "轻量级数据库", "recommended": True}
]


def discover_mcp_servers() -> Dict[str, Any]:
    """
    发现 MCP 服务 — 结合已知列表和 npm 搜索

    Returns:
        {success, servers, count, source, last_updated, error}
    """
    discovered = [s.copy() for s in KNOWN_MCP_SERVERS]

    try:
        result = subprocess.run(
            ["npm", "search", "@modelcontextprotocol/server-", "--json"],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode == 0:
            try:
                npm_data = json.loads(result.stdout)
                existing_names = {s["package"] for s in discovered}
                for pkg in npm_data[:10]:
                    if pkg.get("name") not in existing_names:
                        discovered.append({
                            "name": pkg.get("name", "").replace("@modelcontextprotocol/server-", ""),
                            "package": pkg.get("name", ""),
                            "category": "npm_discovered",
                            "rating": None,
                            "description": pkg.get("description", ""),
                            "recommended": False
                        })
            except json.JSONDecodeError:
                pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return {
        "success": True,
        "servers": discovered,
        "count": len(discovered),
        "source": "known_list + npm_search",
        "last_updated": datetime.now().isoformat(),
        "error": None
    }


def list_known_mcp_servers() -> Dict[str, Any]:
    """
    列出已知 MCP 服务 — 推荐优先

    Returns:
        {success, servers, total_count, recommended_count, categories, error}
    """
    recommended_first = sorted(KNOWN_MCP_SERVERS,
                               key=lambda x: (not x["recommended"], -(x["rating"] or 0)))

    return {
        "success": True,
        "servers": recommended_first,
        "total_count": len(KNOWN_MCP_SERVERS),
        "recommended_count": sum(1 for s in KNOWN_MCP_SERVERS if s["recommended"]),
        "categories": list(set(s["category"] for s in KNOWN_MCP_SERVERS)),
        "error": None
    }


def test_mcp_server(package: str) -> Dict[str, Any]:
    """
    测试 MCP 服务可用性

    Args:
        package: npm 包名，如 "@modelcontextprotocol/server-filesystem"

    Returns:
        {success, available, package, version, installed, latency_ms, error}
    """
    start_time = time.time()

    try:
        if not package.startswith("@"):
            return {"success": False, "available": False, "package": package,
                    "error": f"包名格式不正确: {package}"}

        result = subprocess.run(
            ["npm", "info", package, "version"],
            capture_output=True, text=True, timeout=15
        )

        elapsed = time.time() - start_time

        if result.returncode == 0:
            version = result.stdout.strip()
            install_check = subprocess.run(
                ["npm", "list", "-g", package],
                capture_output=True, text=True, timeout=10
            )
            installed = install_check.returncode == 0

            return {
                "success": True,
                "available": True,
                "package": package,
                "version": version,
                "installed": installed,
                "latency_ms": round(elapsed * 1000, 1),
                "error": None
            }
        else:
            return {"success": False, "available": False, "package": package,
                    "error": result.stderr.strip()}

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {"success": False, "available": False, "package": package, "error": "超时"}
    except FileNotFoundError:
        return {"success": False, "available": False, "package": package, "error": "npm 未安装"}
    except Exception as e:
        return {"success": False, "available": False, "package": package, "error": str(e)}


def get_rules_summary() -> Dict[str, Any]:
    """
    获取规则摘要 — agent 层规则概览

    tools 层提供便捷入口，详细定义和触发逻辑在 devpartner-agent 的 rule_engine 中。

    Returns:
        {success, rules, count, note, error}
    """
    rules_overview = [
        {"name": "auto-log-conversation", "description": "自动记录对话到日志",
         "priority": 1, "layer": "agent"},
        {"name": "cross-agent-dialogue", "description": "多AI实例对话机制",
         "priority": 1, "layer": "agent"},
        {"name": "turbo-effect", "description": "系统自改进优化",
         "priority": 2, "layer": "agent"},
        {"name": "self-reflection", "description": "决策后自动反思",
         "priority": 3, "layer": "agent"},
        {"name": "security-audit", "description": "定期安全审计",
         "priority": 2, "layer": "agent"},
    ]

    return {
        "success": True,
        "rules": rules_overview,
        "count": len(rules_overview),
        "note": "详细定义见 devpartner-agent 的 rule_engine",
        "error": None
    }


def generate_config_snippet() -> Dict[str, Any]:
    """
    生成 MCP 客户端配置片段

    Returns:
        {success, config_json, servers, note, error}
    """
    config_snippet = {
        "mcpServers": {
            "devpartner-tools": {
                "command": "python",
                "args": ["<PATH>/devpartner-tools/server.py"],
                "transport": "stdio"
            },
            "devpartner-agent": {
                "command": "python",
                "args": ["<PATH>/devpartner-agent/server.py"],
                "transport": "stdio"
            }
        }
    }

    config_json = json.dumps(config_snippet, indent=2, ensure_ascii=False)

    return {
        "success": True,
        "config_json": config_json,
        "servers": ["devpartner-tools", "devpartner-agent"],
        "note": "请替换 <PATH> 为实际项目路径",
        "error": None
    }
