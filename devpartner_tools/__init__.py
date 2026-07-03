"""
DevPartner Tools - 纯工具层（无状态）

5 大类共 21 个无状态 MCP 工具。
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
from .tools.system_utils import (
    execute_system_command, detect_client, environment_scan, validate_path
)
from .tools.growth_analytics import (
    get_user_growth_overview,
    get_system_evolution_stats,
    get_user_skill_radar,
    get_learning_timeline,
    get_user_activity_heatmap
)

__all__ = [
    # filesystem
    "read_file", "write_file", "list_directory", "search_files", "search_content",
    # git
    "git_status", "git_log", "git_diff",
    # web
    "fetch_url", "github_search_code", "github_search_repositories", "context7_search",
    # system
    "execute_system_command", "detect_client", "environment_scan", "validate_path",
    # growth analytics (双向成长仪表盘)
    "get_user_growth_overview",
    "get_system_evolution_stats",
    "get_user_skill_radar",
    "get_learning_timeline",
    "get_user_activity_heatmap",
]