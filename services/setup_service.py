"""
配置向导服务 - 首次运行检测/询问/自动配置
==========================================
智能检测用户环境，引导配置 devPartner 运行参数。

功能：
  1. 首次运行检测 → 自动触发引导
  2. 云盘路径扫描 → 推荐同步目录
  3. AI客户端发现 → 自动注册已知IDE
  4. 路径验证 → 确保配置可用
  5. 生成配置 → 写入 config.yaml
"""
import os
import json
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List


class SetupWizard:
    """
    配置向导
    
    用法：
        wizard = SetupWizard()
        # 检测是否需要配置
        result = wizard.check_setup_needed()
        # 执行自动检测
        scan = wizard.scan_environment()
        # 应用配置
        wizard.apply_config({"data_root": "D:/Nutstore/devPartner-data"})
    """

    def __init__(self):
        self.config_path = Path("config.yaml")
        self.project_root = Path(__file__).parent.parent

    # ---- 检查 ----

    def check_setup_needed(self) -> dict:
        """
        检查是否需要运行配置向导
        
        返回：{needed: bool, reasons: [...], current_config: {...}}
        """
        reasons = []

        # 1. 配置文件是否存在
        if not self.config_path.exists():
            reasons.append("config.yaml 不存在，需要初始化配置")

        # 2. 关键路径是否可访问
        config = self._load_config()
        if config:
            db_path = config.get("database", {}).get("shared_db", "")
            if db_path and not Path(db_path).parent.exists():
                reasons.append(f"共享数据库路径不可访问: {db_path}")

            dialogue_file = config.get("dialogue", {}).get("dialogue_file", "")
            if dialogue_file and not Path(dialogue_file).parent.exists():
                reasons.append(f"对话文件目录不可访问: {Path(dialogue_file).parent}")

        # 3. 是否有云盘可用
        from core.cloud_sync import CloudDriveDetector
        drives = CloudDriveDetector.detect_all()
        has_cloud = any(d.status == "found_accessible" for d in drives)
        if not has_cloud:
            reasons.append("未检测到可用的云盘服务（坚果云/阿里云盘/OneDrive等）")

        # 4. 是否已注册AI客户端
        registry_file = Path("data/.client_registry.json")
        if not registry_file.exists():
            reasons.append("尚未注册任何AI客户端")

        return {
            "needed": len(reasons) > 0,
            "reasons": reasons,
            "current_config": config,
        }

    # ---- 扫描 ----

    def scan_environment(self) -> dict:
        """
        完整环境扫描
        
        返回结构化扫描报告，供AI展示给用户选择
        """
        scan = {
            "timestamp": datetime.now().isoformat(),
            "cloud_drives": [],
            "ai_clients": [],
            "existing_databases": [],
            "suggested_data_root": None,
            "workspace_projects": [],
        }

        # 1. 扫描云盘
        from core.cloud_sync import CloudDriveDetector
        drives = CloudDriveDetector.detect_all()
        for d in drives:
            scan["cloud_drives"].append({
                "name": d.name,
                "icon": d.icon,
                "path": d.path,
                "status": d.status,
                "readable": d.status == "found_accessible",
            })

        # 2. 推荐数据存储路径
        scan["suggested_data_root"] = CloudDriveDetector.suggest_sync_path()

        # 3. 扫描 AI 客户端（在工作区附近）
        workspace_root = Path(os.getcwd())
        for candidate in [workspace_root, workspace_root.parent]:
            for client_name, info in {
                "codebuddy": ".codebuddy",
                "trae": ".trae",
                "cursor": ".cursor",
            }.items():
                config_dir = candidate / info
                if config_dir.exists():
                    # 读取 mcp 配置看是否已配置 devPartner
                    mcp_config = None
                    mcp_files = list(candidate.glob(f"{info}/**/mcp*.json")) + \
                                list(Path.home().glob(f".{client_name}/**/mcp*.json"))
                    for mf in mcp_files:
                        try:
                            mcp_config = json.loads(mf.read_text(encoding="utf-8"))
                            break
                        except Exception:
                            pass

                    scan["ai_clients"].append({
                        "name": client_name,
                        "config_dir": str(config_dir),
                        "workspace": str(candidate),
                        "has_mcp_config": bool(mcp_config),
                        "devpartner_configured": self._check_mcp_has_devpartner(mcp_config),
                    })

        # 4. 扫描已有数据库
        db_patterns = [
            "**/work_tracker.db",
            "**/devpartner.db",
            "**/conversation_log.db",
        ]
        for pattern in db_patterns:
            for db_file in workspace_root.parent.glob(pattern):
                if db_file.is_file():
                    scan["existing_databases"].append({
                        "path": str(db_file),
                        "size_bytes": db_file.stat().st_size,
                    })

        # 5. 扫描工作区项目
        for item in workspace_root.parent.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                has_code = any(item.glob("*.py")) or any(item.glob("*.js")) or \
                           any(item.glob("*.java")) or any(item.glob("*.ts"))
                if has_code:
                    scan["workspace_projects"].append({
                        "name": item.name,
                        "path": str(item),
                    })

        return scan

    def _check_mcp_has_devpartner(self, mcp_config: dict) -> bool:
        """检查 MCP 配置中是否已包含 devPartner"""
        if not mcp_config:
            return False
        servers = mcp_config.get("mcpServers", {})
        for name in servers:
            if "devpartner" in name.lower() or "dev-partner" in name.lower():
                return True
        return False

    # ---- 生成建议 ----

    def generate_suggestions(self, scan: dict) -> List[dict]:
        """
        基于扫描结果生成配置建议列表
        
        返回可操作的配置建议
        """
        suggestions = []

        # 建议1：设置数据存储路径
        if scan["cloud_drives"]:
            best_drive = None
            for drive in scan["cloud_drives"]:
                if drive["readable"]:
                    best_drive = drive
                    break
            if best_drive:
                suggestions.append({
                    "id": "data_root",
                    "title": f"设置数据存储到 {best_drive['icon']} {best_drive['name']}",
                    "description": f"将所有日志、数据库、对话记录存储在 {best_drive['name']} 的同步目录中，实现多设备自动同步",
                    "recommended_value": f"{best_drive['path']}/devPartner-data",
                    "priority": "high",
                    "action": "需要你确认或修改此路径",
                })

        # 建议2：注册AI客户端
        for client in scan["ai_clients"]:
            if not client.get("devpartner_configured"):
                suggestions.append({
                    "id": f"register_{client['name']}",
                    "title": f"注册 {client['name']} 客户端",
                    "description": f"检测到 {client['name']} 配置目录在 {client['config_dir']}，但尚未连接 devPartner",
                    "recommended_value": {
                        "client": client["name"],
                        "workspace": client["workspace"],
                    },
                    "priority": "high",
                    "action": f"需要在 {client['name']} 的 MCP 配置中添加 devPartner 连接",
                })

        # 建议3：共享数据库
        if not scan["existing_databases"]:
            suggestions.append({
                "id": "shared_db",
                "title": "首次使用，将创建新的共享数据库",
                "description": "所有日志和总结将归档到共享数据库中（可通过云盘同步）",
                "recommended_value": f"{scan.get('suggested_data_root', 'data')}/work_tracker.db",
                "priority": "medium",
                "action": "自动创建，无需操作",
            })

        return suggestions

    # ---- 应用配置 ----

    def apply_config(self, user_choices: dict) -> dict:
        """
        应用用户选择的配置
        
        user_choices 示例：
        {
            "data_root": "D:/Nutstore/devPartner-data",
            "clients": [
                {"name": "codebuddy", "workspace": "D:/WorkSpace/Code/toptown_LIVE"},
                {"name": "trae", "workspace": "D:/WorkSpace/Code/toptown_LIVE"}
            ]
        }
        """
        applied = []
        current_config = self._load_config() or {}

        # 1. 设置 data_root
        data_root = user_choices.get("data_root")
        if data_root:
            data_root = str(Path(data_root))
            Path(data_root).mkdir(parents=True, exist_ok=True)

            if "database" not in current_config:
                current_config["database"] = {}
            current_config["database"]["local_db"] = f"{data_root}/devpartner.db"
            current_config["database"]["shared_db"] = f"{data_root}/work_tracker.db"
            current_config["database"]["report_dir"] = f"{data_root}/reports"

            if "log" not in current_config:
                current_config["log"] = {}
            current_config["log"]["daily_logs_dir"] = f"{data_root}/daily_logs"
            current_config["log"]["log_archive_dir"] = f"{data_root}/logs_archive"
            current_config["log"]["tool_archive_dir"] = f"{data_root}/tool_archive"

            if "dialogue" not in current_config:
                current_config["dialogue"] = {}
            current_config["dialogue"]["dialogue_file"] = f"{data_root}/agent_dialogue.md"
            current_config["dialogue"]["state_file"] = f"{data_root}/.dialogue_state.json"
            current_config["dialogue"]["pending_file"] = f"{data_root}/.pending_dialogue.json"

            if "mindmap" not in current_config:
                current_config["mindmap"] = {}
            current_config["mindmap"]["output_dir"] = f"{data_root}/mindmaps"

            applied.append({"config": "data_root", "status": "applied", "value": data_root})

        # 2. 注册客户端
        clients = user_choices.get("clients", [])
        from core.identity import get_identity
        identity = get_identity()

        for client in clients:
            name = client.get("name", "")
            workspace = client.get("workspace", "")
            if name:
                result = identity.register(name, workspace)
                applied.append({
                    "config": f"client:{name}",
                    "status": "applied",
                    "workspace": workspace,
                })

        # 3. 写入 config.yaml
        self._save_config(current_config)

        return {
            "success": True,
            "applied": applied,
            "config_file": str(self.config_path),
        }

    def generate_mcp_config_snippet(self, host: str = "localhost", port: int = 8080) -> dict:
        """
        生成 MCP 连接配置代码片段（供用户粘贴到 CodeBuddy/Trae 的 mcp.json 中）
        """
        return {
            "type": "sse",
            "url": f"http://{host}:{port}/sse",
            "description": "devPartner - 自我进化全能MCP聚合服务",
        }

    # ---- 内部方法 ----

    def _load_config(self) -> Optional[dict]:
        """加载现有配置"""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception:
                return None
        return None

    def _save_config(self, config: dict):
        """保存配置到 YAML"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def validate_path(self, path: str) -> dict:
        """验证路径是否可用"""
        p = Path(path)
        result = {
            "path": str(p),
            "exists": p.exists(),
            "is_dir": p.is_dir() if p.exists() else False,
            "is_writable": False,
            "parent_exists": p.parent.exists(),
        }
        if result["parent_exists"]:
            try:
                test = p.parent / ".devpartner_write_test"
                test.write_text("test")
                test.unlink()
                result["is_writable"] = True
            except Exception:
                pass
        return result


# 全局单例
_setup_instance: Optional[SetupWizard] = None


def get_setup() -> SetupWizard:
    global _setup_instance
    if _setup_instance is None:
        _setup_instance = SetupWizard()
    return _setup_instance
