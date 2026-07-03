"""
DevPartner Tools - 纯工具包

7 大类共 30 个无状态 MCP 工具：

  📁 filesystem        — 文件系统操作 (5个: read_file, write_file, list_directory, search_files, search_content)
  🔀 git_operations     — Git 操作 (3个: git_status, git_log, git_diff)
  🌐 web_requests       — 网络请求 (4个: fetch_url, github_search_code, github_search_repositories, context7_search)
  🧠 reasoning          — 推理分析 (4个: sequential_think, generate_mindmap, generate_mindmap_from_tree, list_mindmaps)
  ⚙️ system_utils       — 系统工具 (4个: execute_system_command, detect_client, environment_scan, validate_path)
  🔍 mcp_discovery      — MCP服务发现 (5个: discover_mcp_servers, list_known_mcp_servers, test_mcp_server, get_rules_summary, generate_config_snippet)
  📊 growth_analytics   — 双向成长分析 (5个: get_user_growth_overview, get_system_evolution_stats, get_user_skill_radar, get_learning_timeline, get_user_activity_heatmap)

设计原则：
  - 无状态：函数不持有内部状态，每次调用独立
  - 无副作用：除 write_file 外，所有函数只读
  - 即用即弃：输入 → 处理 → 输出
"""

# 显式导出每个工具模块的公开函数，避免通配符导入
from .filesystem import (
    read_file, write_file, list_directory, search_files, search_content
)
from .git_operations import (
    git_status, git_log, git_diff
)
from .web_requests import (
    fetch_url, github_search_code, github_search_repositories, context7_search
)
from .reasoning import (
    sequential_think, generate_mindmap, generate_mindmap_from_tree, list_mindmaps
)
from .system_utils import (
    execute_system_command, detect_client, environment_scan, validate_path
)
from .mcp_discovery import (
    discover_mcp_servers, list_known_mcp_servers, test_mcp_server,
    get_rules_summary, generate_config_snippet
)
from .growth_analytics import (
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
    # reasoning
    "sequential_think", "generate_mindmap", "generate_mindmap_from_tree", "list_mindmaps",
    # system
    "execute_system_command", "detect_client", "environment_scan", "validate_path",
    # discovery
    "discover_mcp_servers", "list_known_mcp_servers", "test_mcp_server",
    "get_rules_summary", "generate_config_snippet",
    # growth analytics (双向成长仪表盘)
    "get_user_growth_overview",
    "get_system_evolution_stats",
    "get_user_skill_radar",
    "get_learning_timeline",
    "get_user_activity_heatmap",
]