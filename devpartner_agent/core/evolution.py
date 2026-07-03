"""
DevPartner Agent 自我进化引擎

核心能力：
  - 代码自更新（备份 → 写入 → 语法验证 → 失败回滚）
  - 热重载模块
  - MCP 服务自动发现
  - 自诊断 & 系统状态查询
  - 进化历史追踪
"""

import os
import sys
import json
import shutil
import importlib
import subprocess
import traceback
from pathlib import Path
from datetime import datetime
from typing import Any, Optional


class EvolutionEngine:
    """自我进化引擎：代码自更新、热重载、MCP自动发现"""

    _instance: Optional["EvolutionEngine"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._project_root = Path(__file__).parent.parent
        self._backup_dir = self._project_root / "data" / "backups"
        self._upgrade_count_today = 0
        self._last_upgrade_date = ""
        self._initialized = True

    # ── 内部辅助 ──────────────────────────────────────

    def _check_daily_limit(self) -> bool:
        """检查每日升级次数限制"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_upgrade_date:
            self._upgrade_count_today = 0
            self._last_upgrade_date = today
        try:
            from .config import get_config
            cfg = get_config()
            return self._upgrade_count_today < cfg.evolution.max_changes_per_day
        except Exception:
            return self._upgrade_count_today < 3  # 默认每日最多3次

    def _get_cfg(self):
        """安全获取配置"""
        try:
            from .config import get_config
            return get_config()
        except Exception:
            return None

    # ── 文件操作 ──────────────────────────────────────

    def backup_file(self, file_path: str) -> Optional[str]:
        """备份文件（返回备份路径）"""
        src = Path(file_path)
        if not src.exists():
            return None

        self._backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{src.name}.{timestamp}.bak"
        backup_path = self._backup_dir / backup_name
        shutil.copy2(src, backup_path)
        return str(backup_path)

    def upgrade_file(self, file_path: str, new_content: str,
                     validate: bool = True) -> dict:
        """
        升级单个文件
        - 备份原文件
        - 写入新内容
        - 语法验证（Python）
        - 失败自动回滚
        """
        if not self._check_daily_limit():
            return {
                "success": False,
                "file": file_path,
                "error": "超过每日升级次数限制",
                "action": "upgrade",
            }

        full_path = self._project_root / file_path
        result = {
            "success": False,
            "file": file_path,
            "backup": None,
            "action": "upgrade",
        }

        try:
            # 1. 备份
            result["backup"] = self.backup_file(str(full_path))

            # 2. 写入新内容
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(new_content)

            # 3. 语法验证
            if validate and file_path.endswith(".py"):
                try:
                    compile(new_content, str(full_path), "exec")
                except SyntaxError as e:
                    if result["backup"]:
                        shutil.copy2(result["backup"], full_path)
                    result["error"] = f"语法错误: {e}"
                    return result

            # 4. 记录日志
            self._log_evolution(file_path, "upgrade")
            self._upgrade_count_today += 1
            result["success"] = True
            return result

        except Exception as e:
            result["error"] = str(e)
            if result["backup"] and Path(result["backup"]).exists():
                try:
                    shutil.copy2(result["backup"], full_path)
                    result["rolled_back"] = True
                except Exception:
                    pass
            return result

    def create_new_file(self, file_path: str, content: str) -> dict:
        """创建新文件（自我进化中新增模块）"""
        full_path = self._project_root / file_path
        result = {"success": False, "file": file_path, "action": "create"}

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

            if file_path.endswith(".py"):
                try:
                    compile(content, str(full_path), "exec")
                except SyntaxError as e:
                    full_path.unlink()
                    result["error"] = f"语法错误: {e}"
                    return result

            self._log_evolution(file_path, "create")
            result["success"] = True
            return result

        except Exception as e:
            result["error"] = str(e)
            return result

    def hot_reload_module(self, module_name: str) -> dict:
        """热重载 Python 模块"""
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                return {"success": True, "module": module_name, "action": "reloaded"}
            else:
                module = importlib.import_module(module_name)
                return {"success": True, "module": module_name, "action": "imported"}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "traceback": traceback.format_exc()}

    # ── MCP 发现 ──────────────────────────────────────

    def discover_mcp_servers(self) -> list[dict]:
        """自动发现新的 MCP 服务器"""
        discovered = []

        try:
            result = subprocess.run(
                ["npm", "search", "@modelcontextprotocol", "--json"],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=60
            )

            if result.returncode == 0:
                packages = json.loads(result.stdout)
                for pkg in packages[:20]:
                    discovered.append({
                        "name": pkg.get("name", ""),
                        "description": pkg.get("description", ""),
                        "version": pkg.get("version", ""),
                        "source": "npm_registry",
                    })
        except Exception:
            # npm search 不可用，使用已知列表
            cfg = self._get_cfg()
            known = cfg.evolution.known_mcp_servers if cfg else []
            for server_pkg in known:
                discovered.append({
                    "name": server_pkg.split("/")[-1] if "/" in server_pkg else server_pkg,
                    "package": server_pkg,
                    "description": "已知MCP服务",
                    "source": "known_list",
                })

        self._log_discovery(discovered)
        return discovered

    def test_mcp_server(self, package_name: str) -> dict:
        """测试 MCP 服务器是否可用"""
        try:
            result = subprocess.run(
                ["npx", "-y", package_name, "--help"],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30
            )
            return {
                "available": result.returncode == 0,
                "package": package_name,
                "stdout": result.stdout[:500] if result.stdout else "",
                "stderr": result.stderr[:500] if result.stderr else "",
            }
        except Exception as e:
            return {"available": False, "package": package_name, "error": str(e)}

    # ── Git 版本控制 ──────────────────────────────────

    def _is_git_available(self) -> bool:
        """检测 git 是否可用"""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=10, cwd=str(self._project_root.parent)
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_git(self, args: list, cwd: str = None) -> subprocess.CompletedProcess:
        """执行 git 命令"""
        if cwd is None:
            cwd = str(self._project_root.parent)
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=60, cwd=cwd
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} 失败")
        return result

    def git_create_branch(self, branch_name: str, base_branch: str = None) -> dict:
        """
        AI 控制的 Git 分支创建

        在系统升级前创建新分支，用于安全地应用变更。
        自动记录当前分支以便回滚。

        Args:
            branch_name: 新分支名称
            base_branch: 基础分支（默认当前分支）

        Returns:
            {success, branch, previous_branch}
        """
        if not self._is_git_available():
            return {"success": False, "error": "Git 不可用"}

        try:
            # 记录当前分支
            r = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15, cwd=str(self._project_root.parent)
            )
            previous = r.stdout.strip()

            # 如果指定了 base_branch，先切换
            if base_branch and base_branch != previous:
                self._run_git(["checkout", base_branch])
                # 确保基于最新代码
                try:
                    self._run_git(["pull", "--ff-only"])
                except Exception:
                    pass

            # 创建并切换到新分支
            self._run_git(["checkout", "-b", branch_name])

            self._git_previous_branch = previous

            return {
                "success": True,
                "branch": branch_name,
                "previous_branch": previous,
                "base_branch": base_branch or previous,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def git_commit_and_push(self, message: str, branch_name: str = None) -> dict:
        """
        AI 控制的 Git 提交和推送

        暂存所有变更 → 提交 → 推送到 origin。
        这是系统升级完成后的标准 Git 操作。

        Args:
            message: 提交信息
            branch_name: 要推送的分支名（默认当前分支）

        Returns:
            {success, branch, commit_message, push_result}
        """
        if not self._is_git_available():
            return {"success": False, "error": "Git 不可用"}

        try:
            # 1. 暂存所有变更
            self._run_git(["add", "-A"])

            # 2. 提交
            self._run_git(["commit", "-m", message])

            # 3. 获取当前分支名
            if branch_name is None:
                r = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    capture_output=True, text=True, encoding='utf-8', errors='replace',
                    timeout=15, cwd=str(self._project_root.parent)
                )
                branch_name = r.stdout.strip()

            # 4. 推送
            result = self._run_git(["push", "-u", "origin", branch_name])

            return {
                "success": True,
                "branch": branch_name,
                "commit_message": message,
                "push_output": result.stdout.strip()[:500],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def git_checkout_previous(self) -> dict:
        """切回升级前的原始分支"""
        if hasattr(self, "_git_previous_branch") and self._git_previous_branch:
            try:
                self._run_git(["checkout", self._git_previous_branch])
                return {"success": True, "branch": self._git_previous_branch}
            except Exception as e:
                return {"success": False, "error": str(e)}
        return {"success": False, "error": "无记录的前一个分支"}

    def git_rollback_branch(self, branch_name: str) -> dict:
        """
        AI 控制的 Git 回滚

        删除失败的分支，切回原分支。
        用于升级失败时的自动恢复。

        Args:
            branch_name: 要删除的分支名

        Returns:
            {success, deleted_branch, current_branch}
        """
        if not self._is_git_available():
            return {"success": False, "error": "Git 不可用"}

        try:
            # 先切回之前的 branch
            checkout_result = self.git_checkout_previous()
            current = checkout_result.get("branch", "unknown")

            # 删除失败的分支
            self._run_git(["branch", "-D", branch_name])

            return {
                "success": True,
                "deleted_branch": branch_name,
                "current_branch": current,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def git_get_status(self) -> dict:
        """
        获取 Git 仓库状态

        返回当前分支、变更文件列表、是否干净等信息。
        用于 AI 决策是否应该创建分支/提交。

        Returns:
            {branch, is_clean, changes: {staged, unstaged, untracked}, files: [...]}
        """
        if not self._is_git_available():
            return {"git_available": False}

        try:
            r = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15, cwd=str(self._project_root.parent)
            )
            lines = [l for l in r.stdout.strip().split("\n") if l]

            r_branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
                timeout=15, cwd=str(self._project_root.parent)
            )

            staged = []
            unstaged = []
            untracked = []
            for line in lines:
                if len(line) < 3:
                    continue
                status_code = line[:2]
                filename = line[3:].strip()
                if status_code[0] in "MRC" and status_code[1] != "?":
                    staged.append(filename)
                elif status_code[0] == "?":
                    untracked.append(filename)
                else:
                    unstaged.append(filename)

            return {
                "git_available": True,
                "branch": r_branch.stdout.strip(),
                "is_clean": len(lines) == 0,
                "changes": {
                    "staged": len(staged),
                    "unstaged": len(unstaged),
                    "untracked": len(untracked),
                },
                "files": lines[:20],  # 最多返回前20个文件
            }
        except Exception as e:
            return {"git_available": True, "error": str(e)}

    # ── 状态查询 ──────────────────────────────────────

    def get_evolution_history(self) -> list[dict]:
        """获取进化历史"""
        try:
            from .database import get_db
            db = get_db()
            return db.query_local(
                "SELECT * FROM evolution_log ORDER BY timestamp DESC LIMIT 50"
            )
        except Exception:
            return self._read_history_file()

    def get_system_status(self) -> dict:
        """获取系统状态摘要"""
        cfg = self._get_cfg()

        status = {
            "version": cfg.version if cfg else "unknown",
            "uptime": "N/A",
            "rules_count": 0,
            "mcp_servers_known": len(cfg.evolution.known_mcp_servers) if cfg else 0,
            "evolution_enabled": cfg.evolution.enabled if cfg else True,
            "upgrades_today": self._upgrade_count_today,
            "upgrades_limit": cfg.evolution.max_changes_per_day if cfg else 3,
            "database_ok": False,
        }

        try:
            from .database import get_db
            db = get_db()
            db.query_local("SELECT 1")
            status["database_ok"] = True
        except Exception:
            pass

        try:
            from .rule_engine import get_rule_engine
            status["rules_count"] = len(get_rule_engine().get_all())
        except Exception:
            pass

        return status

    def self_diagnose(self) -> dict:
        """自诊断：检查服务健康状况"""
        issues = []
        checks = {}

        # 检查目录结构
        required_dirs = ["core", "services", "skills", "data"]
        for d in required_dirs:
            path = self._project_root / d
            checks[f"dir_{d}"] = path.exists()
            if not path.exists():
                issues.append(f"缺少目录: {d}")

        # 检查核心文件
        required_files = [
            "core/config.py", "core/database.py",
            "core/rule_engine.py", "core/evolution.py"
        ]
        for f in required_files:
            path = self._project_root / f
            checks[f"file_{f}"] = path.exists()
            if not path.exists():
                issues.append(f"缺少核心文件: {f}")

        # 检查依赖
        try:
            import fastmcp
            checks["fastmcp_installed"] = True
        except ImportError:
            issues.append("fastmcp 未安装，请运行: pip install -r requirements.txt")
            checks["fastmcp_installed"] = False

        return {
            "healthy": len(issues) == 0,
            "checks": checks,
            "issues": issues,
            "timestamp": datetime.now().isoformat(),
        }

    # ── 日志记录 ──────────────────────────────────────

    def _log_evolution(self, file_path: str, change_type: str):
        """记录进化日志到数据库"""
        cfg = self._get_cfg()
        try:
            from .database import get_db
            db = get_db()
            version = cfg.version if cfg else "2.0.0"
            db.log_evolution(
                change_type=change_type,
                description=f"Self-evolution: {change_type} {file_path}",
                files_changed=file_path,
                version=version,
            )
        except Exception:
            pass

    def _log_discovery(self, servers: list[dict]):
        """记录 MCP 发现日志到 mcp_tool_registry"""
        try:
            from .database import get_db
            db = get_db()
            for srv in servers:
                db.register_tool(
                    tool_name=srv.get("name", ""),
                    module=srv.get("package", ""),
                    description=srv.get("description", ""),
                )
        except Exception:
            pass

    def _read_history_file(self) -> list[dict]:
        """从文件读取进化历史（数据库不可用时的回退）"""
        history_file = self._project_root / "data" / ".evolution_history.json"
        if history_file.exists():
            with open(history_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return []


# 全局便捷访问
def get_evolution_engine() -> EvolutionEngine:
    return EvolutionEngine()