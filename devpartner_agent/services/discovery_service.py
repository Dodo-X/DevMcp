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
        # 原则：只收录完全免费或本地运行的服务，不收录需要付费/API Key 的
        self._recommended_servers = {
            # ═══ 官方基础服务（全部免费，本地运行） ═══
            "filesystem": {
                "package": "@modelcontextprotocol/server-filesystem",
                "description": "文件系统读写操作",
                "tools": ["read_file", "write_file", "list_directory"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "基础工具",
            },
            "github": {
                "package": "@modelcontextprotocol/server-github",
                "description": "GitHub 搜索和仓库管理",
                "tools": ["search_code", "search_repositories", "create_issue"],
                "free_tier": "✅ 免费（需 GitHub Token，免费获取）",
                "category": "代码托管",
            },
            "fetch": {
                "package": "@modelcontextprotocol/server-fetch",
                "description": "URL 网页内容获取",
                "tools": ["fetch"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "网络工具",
            },
            "sqlite": {
                "package": "@modelcontextprotocol/server-sqlite",
                "description": "SQLite 数据库查询",
                "tools": ["run_sql"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "数据存储",
            },
            "git": {
                "package": "@modelcontextprotocol/server-git",
                "description": "Git 仓库操作",
                "tools": ["git_status", "git_log", "git_diff"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "版本控制",
            },
            "memory": {
                "package": "@modelcontextprotocol/server-memory",
                "description": "知识记忆存储（知识图谱）",
                "tools": ["save_memory", "get_memory", "search_memory"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "知识管理",
            },
            "sequential-thinking": {
                "package": "@modelcontextprotocol/server-sequential-thinking",
                "description": "链式思考推理",
                "tools": ["sequential_thinking"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "推理工具",
            },
            "postgres": {
                "package": "@modelcontextprotocol/server-postgres",
                "description": "PostgreSQL 数据库查询",
                "tools": ["query"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "数据存储",
            },

            # ═══ 浏览器自动化（完全免费，本地运行） ═══
            "puppeteer": {
                "package": "@modelcontextprotocol/server-puppeteer",
                "description": "Puppeteer 无头浏览器自动化",
                "tools": ["puppeteer_navigate", "puppeteer_screenshot", "puppeteer_click", "puppeteer_fill", "puppeteer_evaluate"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "浏览器自动化",
            },
            "playwright": {
                "package": "@anthropic/mcp-server-playwright",
                "description": "Playwright 浏览器自动化（更现代）",
                "tools": ["browser_navigate", "browser_screenshot", "browser_click", "browser_fill"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "浏览器自动化",
            },

            # ═══ 外部服务（有免费额度，无需付费） ═══
            "tavily-search": {
                "package": "tavily-mcp",
                "description": "Tavily AI 搜索引擎（实时Web搜索）",
                "tools": ["tavily_search", "tavily_extract"],
                "free_tier": "🆓 1000次/月免费",
                "category": "搜索工具",
                "note": "比 Brave Search 更适合 AI 场景，返回结构化内容",
            },
            "exa-search": {
                "package": "exa-mcp-server",
                "description": "Exa 语义搜索 + 网页内容提取",
                "tools": ["web_search_exa", "get_contents_exa"],
                "free_tier": "🆓 有免费额度",
                "category": "搜索工具",
                "note": "语义搜索，不是关键词匹配",
            },

            # ═══ 开发辅助（完全免费） ═══
            "docker": {
                "package": "@modelcontextprotocol/server-docker",
                "description": "Docker 容器管理",
                "tools": ["docker_list_containers", "docker_run", "docker_stop"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "DevOps",
            },
            "redis": {
                "package": "@anthropic/mcp-server-redis",
                "description": "Redis 缓存操作",
                "tools": ["redis_get", "redis_set", "redis_del"],
                "free_tier": "✅ 完全免费（本地运行）",
                "category": "数据存储",
            },
            "everart": {
                "package": "everart-mcp-server",
                "description": "AI 图片生成（多模型支持）",
                "tools": ["generate_image", "list_models"],
                "free_tier": "🆓 每日免费额度",
                "category": "AI 创作",
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
            "@modelcontextprotocol/server-memory": ["save_memory", "get_memory", "search_memory"],
            "@modelcontextprotocol/server-sequential-thinking": ["sequential_thinking"],
            "@modelcontextprotocol/server-postgres": ["query"],
            "@modelcontextprotocol/server-puppeteer": ["puppeteer_navigate", "puppeteer_screenshot", "puppeteer_click", "puppeteer_fill", "puppeteer_evaluate"],
            "@anthropic/mcp-server-playwright": ["browser_navigate", "browser_screenshot", "browser_click", "browser_fill"],
            "tavily-mcp": ["tavily_search", "tavily_extract"],
            "exa-mcp-server": ["web_search_exa", "get_contents_exa"],
            "@modelcontextprotocol/server-docker": ["docker_list_containers", "docker_run", "docker_stop"],
            "@anthropic/mcp-server-redis": ["redis_get", "redis_set", "redis_del"],
            "everart-mcp-server": ["generate_image", "list_models"],
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
        known_packages = {str(info["package"]) for info in self._recommended_servers.values()}
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
