"""
DevPartner Tools - 纯工具层（无状态）

6 大类共 25 个无状态 MCP 工具。
设计原则：无状态、无副作用、即用即弃。
"""

from .tools.filesystem import (
    read_file, write_file, list_directory, search_files, search_content
)
from .tools.git_operations import (
    git_status, git_log, git_diff
)
from .tools.web_requests import (
    fetch_url, github_search_code, github_search_repositories, context7_search
)
from .tools.reasoning import (
    sequential_think, generate_mindmap, generate_mindmap_from_tree, list_mindmaps
)
from .tools.system_utils import (
    execute_system_command, detect_client, environment_scan, validate_path
)
from .tools.mcp_discovery import (
    discover_mcp_servers, list_known_mcp_servers, test_mcp_server,
    get_rules_summary, generate_config_snippet
)

__all__ = [
    # filesystem
    "read_file", "write_file", "list_directory", "search_files", "search_content",
    # git
    "git_status", "git_log", "git_diff",
    # web
    "fetch_url", "github_search_code", "github_search_repositories", "context7_search",
    # reasoning
    "sequential_think", "generate_mindmap", "generate_mindmap_from_tree", "list_mindmaps",
    # system
    "execute_system_command", "detect_client", "environment_scan", "validate_path",
    # discovery
    "discover_mcp_servers", "list_known_mcp_servers", "test_mcp_server",
    "get_rules_summary", "generate_config_snippet",
]
