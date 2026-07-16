"""网络/API 请求工具集 - 4个纯函数"""
import json
import os
import subprocess
from typing import Dict, Any

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

def fetch_url(url: str, method: str = "GET", headers: Dict[str, str] = None, body: str = "", timeout: int = 30) -> Dict[str, Any]:
    """HTTP 请求 - 纯函数，不存储响应"""
    if not HAS_HTTPX:
        return {"success": False, "error": "httpx 未安装，运行: pip install httpx", "status_code": None}
    
    try:
        if headers is None:
            headers = {}
        
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method.upper(), url=url, headers=headers, content=body if body else None)
            
            return {
                "success": True,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "body": response.text,
                "url": str(response.url),
                "error": None
            }
    except httpx.TimeoutException:
        return {"success": False, "error": f"超时（{timeout}秒）", "status_code": None}
    except Exception as e:
        return {"success": False, "error": str(e), "status_code": None}

def github_search_code(query: str) -> Dict[str, Any]:
    """GitHub 代码搜索 - 需要环境变量 GITHUB_TOKEN"""
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        return {"success": False, "items": [], "error": "未设置 GITHUB_TOKEN"}
    
    try:
        import urllib.request
        url = f"https://api.github.com/search/code?q={query}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        })
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
            items = []
            for item in data.get("items", [])[:20]:
                items.append({
                    "name": item.get("name"),
                    "path": item.get("path"),
                    "repository": item.get("repository", {}).get("full_name"),
                    "html_url": item.get("html_url")
                })
            return {"success": True, "items": items, "total_count": data.get("total_count", 0), "error": None}
    except Exception as e:
        return {"success": False, "items": [], "error": str(e)}

def github_search_repositories(query: str) -> Dict[str, Any]:
    """GitHub 仓库搜索 - 需要 GITHUB_TOKEN"""
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        return {"success": False, "items": [], "error": "未设置 GITHUB_TOKEN"}
    
    try:
        import urllib.request
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&per_page=20"
        req = urllib.request.Request(url, headers={"Authorization": f"token {token}"})
        
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
            items = []
            for repo in data.get("items", [])[:20]:
                items.append({
                    "full_name": repo.get("full_name"),
                    "description": repo.get("description"),
                    "stars": repo.get("stargazers_count"),
                    "forks": repo.get("forks_count"),
                    "language": repo.get("language")
                })
            return {"success": True, "items": items, "total_count": data.get("total_count", 0), "error": None}
    except Exception as e:
        return {"success": False, "items": [], "error": str(e)}

def context7_search(query: str) -> Dict[str, Any]:
    """Context7 MCP 搜索 - 需要已安装 @upstash/context7-mcp"""
    try:
        result = subprocess.run(["npx", "-y", "@upstash/context7-mcp", "search", query],
                               capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60)
        
        if result.returncode != 0:
            return {"success": False, "results": [], "error": f"Context7 失败: {result.stderr}"}
        
        try:
            data = json.loads(result.stdout)
            return {"success": True, "results": data if isinstance(data, list) else [data], "query": query, "error": None}
        except json.JSONDecodeError:
            return {"success": True, "results": [{"raw_output": result.stdout}], "query": query, "error": None}
    except FileNotFoundError:
        return {"success": False, "results": [], "error": "Node.js/npx 未安装"}
    except subprocess.TimeoutExpired:
        return {"success": False, "results": [], "error": "Context7 超时"}


def register_web_request_tools(mcp):
    """注册 Web 请求工具到 MCP"""

    @mcp.tool()
    def fetch_url_tool(url: str, method: str = "GET", headers: str = "{}", body: str = "", timeout: int = 30) -> str:
        """发起 HTTP 请求。"""
        import json as _json
        h = _json.loads(headers) if isinstance(headers, str) else headers
        return _json.dumps(fetch_url(url, method, h, body, timeout), ensure_ascii=False, default=str)

    @mcp.tool()
    def github_search_code_tool(query: str) -> str:
        """搜索 GitHub 代码。"""
        import json as _json
        return _json.dumps(github_search_code(query), ensure_ascii=False, default=str)

    @mcp.tool()
    def github_search_repositories_tool(query: str) -> str:
        """搜索 GitHub 仓库。"""
        import json as _json
        return _json.dumps(github_search_repositories(query), ensure_ascii=False, default=str)
