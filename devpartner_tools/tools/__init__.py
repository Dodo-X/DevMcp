"""
DevPartner Tools - 纯工具包

4 大类共 16 个无状态 MCP 工具：

  📁 filesystem        — 文件系统操作 (5个: read_file, write_file, list_directory, search_files, search_content)
  🔀 git_operations     — Git 操作 (3个: git_status, git_log, git_diff)
  🌐 web_requests       — 网络请求 (4个: fetch_url, github_search_code, github_search_repositories, context7_search)
  ⚙️ system_utils       — 系统工具 (4个: execute_system_command, detect_client, environment_scan, validate_path)

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
from .system_utils import (
    execute_system_command, detect_client, environment_scan, validate_path
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
]