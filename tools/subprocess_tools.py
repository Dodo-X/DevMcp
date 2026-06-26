"""
Subprocess MCP 工具代理
- GitHub 搜索（需要 npm 包）
- Context7 搜索（需要 npm 包）
- 其他无法纯 Python 实现的 MCP 服务
"""
import json
import os
import subprocess
from pathlib import Path
from typing import Optional


class SubprocessMCP:
    """通过 subprocess 调用外部 npm MCP 服务的代理"""

    def __init__(self):
        self._cache: dict = {}

    def _call_mcp_tool(self, package: str, tool_name: str,
                       arguments: dict, extra_args: list = None,
                       env: dict = None, work_dir: str = None) -> str:
        """通用 MCP 工具调用"""
        try:
            cmd = ["npx", "-y"]
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(package)

            if work_dir:
                cmd.append(work_dir)

            input_data = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            }

            proc_env = os.environ.copy()
            if env:
                proc_env.update(env)

            result = subprocess.run(
                cmd,
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                timeout=30,
                env=proc_env,
            )

            if result.stdout:
                return result.stdout
            return json.dumps({"error": result.stderr or "无输出"}, ensure_ascii=False)
        except subprocess.TimeoutExpired:
            return json.dumps({"error": "MCP 服务调用超时"}, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    def github_search_code(self, query: str) -> str:
        """GitHub 代码搜索"""
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return json.dumps({
                "error": "请设置 GITHUB_TOKEN 环境变量",
                "tip": "在 https://github.com/settings/tokens 创建 token"
            }, ensure_ascii=False)
        return self._call_mcp_tool(
            "@modelcontextprotocol/server-github",
            "search_code",
            {"q": query},
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": token},
        )

    def github_search_repositories(self, query: str) -> str:
        """GitHub 仓库搜索"""
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            return json.dumps({
                "error": "请设置 GITHUB_TOKEN 环境变量",
                "tip": "在 https://github.com/settings/tokens 创建 token"
            }, ensure_ascii=False)
        return self._call_mcp_tool(
            "@modelcontextprotocol/server-github",
            "search_repositories",
            {"q": query},
            env={"GITHUB_PERSONAL_ACCESS_TOKEN": token},
        )

    def context7_search(self, query: str) -> str:
        """Context7 代码上下文搜索"""
        return self._call_mcp_tool(
            "@upstash/context7-mcp",
            "search",
            {"query": query},
        )


# 全局单例
_mcp_proxy: Optional[SubprocessMCP] = None


def get_mcp_proxy() -> SubprocessMCP:
    global _mcp_proxy
    if _mcp_proxy is None:
        _mcp_proxy = SubprocessMCP()
    return _mcp_proxy


# 便捷函数
def github_search_code(query: str) -> str:
    return get_mcp_proxy().github_search_code(query)


def github_search_repositories(query: str) -> str:
    return get_mcp_proxy().github_search_repositories(query)


def context7_search(query: str) -> str:
    return get_mcp_proxy().context7_search(query)
