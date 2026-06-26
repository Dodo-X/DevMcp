"""
DevPartner Tools — MCP 纯工具服务器 v2.0.0

定位：无状态、无副作用的纯工具层。
只做一件事：接收参数 → 处理 → 返回结果。

启动方式：
    python server.py          # stdio 模式（推荐）
    python server.py sse      # SSE 模式（远程部署，默认端口 8081）
"""

import sys
from pathlib import Path

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from fastmcp import FastMCP

# 创建 MCP 实例
mcp = FastMCP("devpartner-tools")

# ── 加载配置 ──────────────────────────────────────────────
_config = {}
try:
    import yaml
    config_path = Path(__file__).parent / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
except ImportError:
    pass  # pyyaml 可选，不影响运行
except Exception:
    pass

_tools_cfg = _config.get("tools", {})

# ── 显式导入并注册工具 ─────────────────────────────────────
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
from tools.discovery import (
    discover_mcp_servers, list_known_mcp_servers, test_mcp_server,
    get_rules_summary, generate_config_snippet
)

# 注册所有工具到 MCP 实例（FastMCP 通过类型注解自动识别）
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

_tool_count = 25

# ── 启动入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"DevPartner Tools v2.0.0")
    print(f"工具总数: {_tool_count} 个纯工具")
    print(f"配置来源: {'config.yaml 已加载' if _config else '使用默认值'}")
    print(f"待命状态: 等待 AI 客户端连接...")

    if len(sys.argv) > 1 and sys.argv[1] == "sse":
        server_cfg = _config.get("server", {})
        host = server_cfg.get("host", "0.0.0.0")
        port = server_cfg.get("port", 8081)
        mcp.run(transport="sse", host=host, port=port)
    else:
        mcp.run()
