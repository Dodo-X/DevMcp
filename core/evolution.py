"""
devPartner 自我进化引擎
- 代码自更新（在对话中修改自身代码）
- 热重载模块
- 自动备份与回滚
- MCP 服务自动发现
"""
import os
import sys
import json
import shutil
import hashlib
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

    def _check_daily_limit(self) -> bool:
        """检查每日升级次数限制"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._last_upgrade_date:
            self._upgrade_count_today = 0
            self._last_upgrade_date = today
        from core.config import get_config
        cfg = get_config()
        return self._upgrade_count_today < cfg.evolution.max_auto_upgrades_per_day

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

    def upgrade_file(self, file_path: str, new_content: str, validate: bool = True) -> dict:
        """
        升级单个文件
        - 备份原文件
        - 写入新内容
        - 语法验证
        - 失败自动回滚
        """
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

            # 3. 验证语法（Python文件）
            if validate and file_path.endswith(".py"):
                try:
                    compile(new_content, str(full_path), "exec")
                except SyntaxError as e:
                    # 回滚
                    if result["backup"]:
                        shutil.copy2(result["backup"], full_path)
                    result["error"] = f"语法错误: {e}"
                    return result

            # 4. 记录进化日志
            self._log_evolution(file_path, "upgrade")

            self._upgrade_count_today += 1
            result["success"] = True
            return result

        except Exception as e:
            result["error"] = str(e)
            # 尝试回滚
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

            # 如果是 Python 文件，验证语法
            if file_path.endswith(".py"):
                try:
                    compile(content, str(full_path), "exec")
                except SyntaxError as e:
                    full_path.unlink()  # 删除无效文件
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
            return {"success": False, "error": str(e), "traceback": traceback.format_exc()}

    def discover_mcp_servers(self) -> list[dict]:
        """自动发现新的 MCP 服务器（通过 npm search）"""
        discovered = []

        try:
            # 搜索 npm registry
            result = subprocess.run(
                ["npm", "search", "@modelcontextprotocol", "--json"],
                capture_output=True, text=True, timeout=60,
                shell=True
            )

            if result.returncode == 0:
                packages = json.loads(result.stdout)
                for pkg in packages[:20]:  # 限制数量
                    discovered.append({
                        "name": pkg.get("name", ""),
                        "description": pkg.get("description", ""),
                        "version": pkg.get("version", ""),
                        "source": "npm_registry",
                    })
        except Exception as e:
            # npm search 可能不可用，尝试使用已知列表
            from core.config import get_config
            cfg = get_config()
            for server_pkg in cfg.evolution.known_mcp_servers:
                discovered.append({
                    "name": server_pkg.split("/")[-1] if "/" in server_pkg else server_pkg,
                    "package": server_pkg,
                    "description": "已知MCP服务",
                    "source": "known_list",
                })

        # 记录发现
        self._log_discovery(discovered)
        return discovered

    def test_mcp_server(self, package_name: str) -> dict:
        """测试 MCP 服务器是否可用"""
        try:
            result = subprocess.run(
                ["npx", "-y", package_name, "--help"],
                capture_output=True, text=True, timeout=30,
                shell=True
            )
            return {
                "available": result.returncode == 0,
                "package": package_name,
                "stdout": result.stdout[:500] if result.stdout else "",
                "stderr": result.stderr[:500] if result.stderr else "",
            }
        except Exception as e:
            return {"available": False, "package": package_name, "error": str(e)}

    def get_evolution_history(self) -> list[dict]:
        """获取进化历史"""
        from core.database import get_db, Database
        db = get_db()
        try:
            return db.query_local(
                "SELECT * FROM evolution_log ORDER BY timestamp DESC LIMIT 50"
            )
        except Exception:
            return self._read_history_file()

    def get_system_status(self) -> dict:
        """获取系统状态摘要"""
        from core.config import get_config
        cfg = get_config()
        from core.database import get_db

        status = {
            "version": cfg.version,
            "uptime": "N/A",
            "rules_count": 0,
            "mcp_servers_known": len(cfg.evolution.known_mcp_servers),
            "evolution_enabled": cfg.evolution.enabled,
            "upgrades_today": self._upgrade_count_today,
            "upgrades_limit": cfg.evolution.max_auto_upgrades_per_day,
            "ollama_connected": self._check_ollama(),
            "database_ok": False,
        }

        try:
            db = get_db()
            db.query_local("SELECT 1")
            status["database_ok"] = True
        except Exception:
            pass

        from core.rule_engine import get_engine
        status["rules_count"] = len(get_engine().get_all())

        return status

    def _check_ollama(self) -> bool:
        """检查 Ollama 连接状态"""
        try:
            from core.config import get_config
            cfg = get_config()
            import httpx
            resp = httpx.get(f"{cfg.ollama.host}/api/tags", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def _log_evolution(self, file_path: str, change_type: str):
        """记录进化日志到数据库"""
        from core.config import get_config
        cfg = get_config()
        try:
            from core.database import get_db
            db = get_db()
            db.query_local(
                """INSERT INTO evolution_log
                   (timestamp, version_from, version_to, change_type, description, files_changed)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    cfg.version,
                    cfg.version,
                    change_type,
                    f"Self-evolution: {change_type} {file_path}",
                    file_path,
                ),
            )
        except Exception:
            pass

    def _log_discovery(self, servers: list[dict]):
        """记录 MCP 发现日志"""
        try:
            from core.database import get_db
            db = get_db()
            for srv in servers:
                db.query_local(
                    """INSERT OR REPLACE INTO mcp_discovery
                       (timestamp, server_name, npm_package, description, status, last_check)
                       VALUES (?, ?, ?, ?, 'discovered', ?)""",
                    (
                        datetime.now().isoformat(),
                        srv.get("name", ""),
                        srv.get("package", ""),
                        srv.get("description", ""),
                        datetime.now().isoformat(),
                    ),
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

    def self_diagnose(self) -> dict:
        """自诊断：检查服务健康状况"""
        issues = []
        checks = {}

        # 检查目录结构
        required_dirs = ["core", "tools", "services", "rules", "skills", "data"]
        for d in required_dirs:
            path = self._project_root / d
            checks[f"dir_{d}"] = path.exists()
            if not path.exists():
                issues.append(f"缺少目录: {d}")

        # 检查核心文件
        required_files = ["core/config.py", "core/database.py", "core/rule_engine.py", "core/evolution.py"]
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

        # 检查 Ollama
        checks["ollama"] = self._check_ollama()
        if not checks["ollama"]:
            issues.append("Ollama 服务未连接")

        return {
            "healthy": len(issues) == 0,
            "checks": checks,
            "issues": issues,
            "timestamp": datetime.now().isoformat(),
        }


def get_evolution() -> EvolutionEngine:
    return EvolutionEngine()
