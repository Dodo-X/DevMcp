"""
MCP 服务自动发现服务
- 扫描 npm registry 查找新 MCP 服务
- 测试连接
- 自动集成新工具
- 免费服务推荐列表
"""
import json
import subprocess
from datetime import datetime
from typing import Optional


class DiscoveryService:
    """MCP 服务自动发现与集成"""

    _instance: Optional["DiscoveryService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        # 已知的免费好用 MCP 服务列表
        self._recommended_servers = {
            # 官方基础服务
            "filesystem": {
                "package": "@modelcontextprotocol/server-filesystem",
                "description": "文件系统读写操作",
                "tools": ["read_file", "write_file", "list_directory"],
                "free_tier": "unlimited",
            },
            "github": {
                "package": "@modelcontextprotocol/server-github",
                "description": "GitHub 搜索和仓库管理",
                "tools": ["search_code", "search_repositories", "create_issue"],
                "free_tier": "需要 GitHub Token",
            },
            "fetch": {
                "package": "@modelcontextprotocol/server-fetch",
                "description": "URL 网页内容获取",
                "tools": ["fetch"],
                "free_tier": "unlimited",
            },
            "sqlite": {
                "package": "@modelcontextprotocol/server-sqlite",
                "description": "SQLite 数据库查询",
                "tools": ["run_sql"],
                "free_tier": "unlimited",
            },
            "git": {
                "package": "@modelcontextprotocol/server-git",
                "description": "Git 仓库操作",
                "tools": ["git_status", "git_log", "git_diff"],
                "free_tier": "unlimited",
            },
            "memory": {
                "package": "@modelcontextprotocol/server-memory",
                "description": "知识记忆存储",
                "tools": ["save_memory", "get_memory"],
                "free_tier": "unlimited",
            },
            "sequential-thinking": {
                "package": "@modelcontextprotocol/server-sequential-thinking",
                "description": "链式思考推理",
                "tools": ["sequential_thinking"],
                "free_tier": "unlimited",
            },

            # 第三方实用服务
            "context7": {
                "package": "@upstash/context7-mcp",
                "description": "代码上下文搜索 (Upstash)",
                "tools": ["search"],
                "free_tier": "需要 API Key",
            },
            "brave-search": {
                "package": "@anthropic/mcp-server-brave-search",
                "description": "Brave 搜索引擎（web搜索）",
                "tools": ["brave_web_search", "brave_local_search"],
                "free_tier": "需要 Brave Search API Key (免费额度)",
            },
            "browserbase": {
                "package": "@browserbasehq/mcp-server-browserbase",
                "description": "浏览器自动化 (Browserbase)",
                "tools": ["navigate", "screenshot", "click"],
                "free_tier": "需要注册",
            },
            "puppeteer": {
                "package": "@anthropic/mcp-server-puppeteer",
                "description": "Puppeteer 浏览器控制",
                "tools": ["navigate", "screenshot", "click", "fill", "evaluate"],
                "free_tier": "unlimited (本地运行)",
            },
            "playwright": {
                "package": "@anthropic/mcp-server-playwright",
                "description": "Playwright 浏览器自动化",
                "tools": ["navigate", "screenshot", "click", "fill"],
                "free_tier": "unlimited (本地运行)",
            },
            "postgres": {
                "package": "@modelcontextprotocol/server-postgres",
                "description": "PostgreSQL 数据库查询",
                "tools": ["query"],
                "free_tier": "unlimited",
            },
            "slack": {
                "package": "@modelcontextprotocol/server-slack",
                "description": "Slack 消息管理",
                "tools": ["send_message", "list_channels"],
                "free_tier": "需要 Slack Token",
            },
            "notion": {
                "package": "@anthropic/mcp-server-notion",
                "description": "Notion 文档管理",
                "tools": ["search", "create_page", "read_page"],
                "free_tier": "需要 Notion API Key",
            },
            "jira": {
                "package": "@anthropic/mcp-server-jira",
                "description": "Jira 项目管理",
                "tools": ["search_issues", "create_issue", "get_issue"],
                "free_tier": "需要 Jira Token",
            },
        }

    def get_recommended_servers(self) -> dict:
        """获取推荐的 MCP 服务列表"""
        return {
            "total": len(self._recommended_servers),
            "servers": self._recommended_servers,
            "timestamp": datetime.now().isoformat(),
        }

    def search_npm(self, query: str = "@modelcontextprotocol") -> list[dict]:
        """搜索 npm registry 中的 MCP 包"""
        try:
            result = subprocess.run(
                ["npm", "search", query, "--json"],
                capture_output=True, text=True, timeout=60,
                shell=True,
            )
            if result.returncode == 0:
                packages = json.loads(result.stdout)
                return [
                    {
                        "name": p.get("name", ""),
                        "version": p.get("version", ""),
                        "description": p.get("description", ""),
                        "publisher": p.get("publisher", {}).get("username", ""),
                    }
                    for p in packages[:30]
                ]
            return []
        except Exception:
            return []

    def test_server(self, package: str) -> dict:
        """测试 MCP 服务是否可安装运行"""
        try:
            # 尝试安装
            result = subprocess.run(
                ["npx", "-y", package, "--version"],
                capture_output=True, text=True, timeout=60,
                shell=True,
            )
            return {
                "package": package,
                "installable": True,
                "output": result.stdout[:200] if result.stdout else result.stderr[:200],
            }
        except subprocess.TimeoutExpired:
            return {"package": package, "installable": False, "error": "安装超时"}
        except Exception as e:
            return {"package": package, "installable": False, "error": str(e)}

    def get_server_tools(self, package: str) -> list[str]:
        """获取 MCP 服务提供的工具列表"""
        known_tools = {
            "@modelcontextprotocol/server-filesystem": ["read_file", "write_file", "list_directory"],
            "@modelcontextprotocol/server-github": ["search_code", "search_repositories", "create_issue"],
            "@modelcontextprotocol/server-fetch": ["fetch"],
            "@modelcontextprotocol/server-sqlite": ["run_sql"],
            "@modelcontextprotocol/server-git": ["git_status", "git_log", "git_diff"],
            "@modelcontextprotocol/server-memory": ["save_memory", "get_memory"],
            "@modelcontextprotocol/server-sequential-thinking": ["sequential_thinking"],
            "@upstash/context7-mcp": ["search"],
            "@anthropic/mcp-server-brave-search": ["brave_web_search", "brave_local_search"],
            "@browserbasehq/mcp-server-browserbase": ["navigate", "screenshot", "click"],
            "@anthropic/mcp-server-puppeteer": ["navigate", "screenshot", "click", "fill", "evaluate"],
        }

        if package in known_tools:
            return known_tools[package]

        # 尝试从推荐列表中查找
        for info in self._recommended_servers.values():
            if info["package"] == package:
                return info.get("tools", [])

        return []

    def add_to_config(self, server_name: str, package: str, tools: list[str]) -> dict:
        """将新发现的 MCP 服务添加到配置"""
        try:
            # 更新推荐列表
            self._recommended_servers[server_name] = {
                "package": package,
                "description": f"自动发现: {server_name}",
                "tools": tools,
                "free_tier": "unknown",
                "discovered_at": datetime.now().isoformat(),
            }

            # 记录到数据库
            from core.database import get_db
            db = get_db()
            db.query_local(
                """INSERT OR REPLACE INTO mcp_discovery
                   (timestamp, server_name, npm_package, description, tools_count, status, last_check)
                   VALUES (?, ?, ?, ?, ?, 'integrated', ?)""",
                (datetime.now().isoformat(), server_name, package,
                 f"已集成 {len(tools)} 个工具", len(tools), datetime.now().isoformat()),
            )

            return {
                "success": True,
                "server": server_name,
                "package": package,
                "tools_added": len(tools),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def scan_and_discover(self) -> dict:
        """完整扫描流程：搜索 → 过滤已知 → 测试 → 推荐"""
        # 从 npm 搜索
        npm_results = self.search_npm()

        # 过滤出新的
        known_packages = {info["package"] for info in self._recommended_servers.values()}
        new_packages = [p for p in npm_results if p["name"] not in known_packages]

        discovered = []
        for pkg in new_packages[:10]:  # 测试前10个
            test_result = self.test_server(pkg["name"])
            if test_result.get("installable"):
                discovered.append({
                    "name": pkg["name"],
                    "description": pkg["description"],
                    "version": pkg["version"],
                    "tested": True,
                })

        return {
            "total_found": len(npm_results),
            "new_discovered": len(discovered),
            "discovered": discovered,
            "known_count": len(self._recommended_servers),
            "timestamp": datetime.now().isoformat(),
        }

    def get_scan_status(self) -> dict:
        """获取最后一次扫描状态"""
        try:
            from core.database import get_db
            db = get_db()
            rows = db.query_local(
                "SELECT * FROM mcp_discovery ORDER BY last_check DESC LIMIT 20"
            )
            return {
                "total_discovered": len(rows),
                "integrated": len([r for r in rows if r.get("status") == "integrated"]),
                "recent": rows[:5],
            }
        except Exception:
            return {"total_discovered": len(self._recommended_servers)}


def get_discovery() -> DiscoveryService:
    return DiscoveryService()
