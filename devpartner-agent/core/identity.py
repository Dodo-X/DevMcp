"""
身份识别层 - 多AI客户端注册/检测/路由
========================================
解决 CodeBuddy / Trae / 其他AI同时调用同一MCP服务时的身份问题。

策略：
  1. 自动检测：从文件系统操作路径推断（.codebuddy/ vs .trae/ vs .cursor/）
  2. 显式注册：devpartner_register(client_name, workspace_root)
  3. Session 缓存：短期记忆最近活跃客户端

存储位置：data/.client_registry.json
"""
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

# 可识别的AI客户端指纹
KNOWN_CLIENTS = {
    "codebuddy": {
        "config_dir": ".codebuddy",
        "display_name": "CodeBuddy",
        "default_config": ".codebuddy/settings.json",
        "rules_dir": ".codebuddy/rules",
        "mcp_config": "mcp.json",  # 在用户home .codebuddy/ 下
    },
    "trae": {
        "config_dir": ".trae",
        "display_name": "Trae",
        "default_config": ".trae/settings.json",
        "rules_dir": ".trae/rules",
        "mcp_config": ".trae/mcp.json",
    },
    "cursor": {
        "config_dir": ".cursor",
        "display_name": "Cursor",
        "default_config": ".cursor/settings.json",
        "rules_dir": ".cursorrules",
        "mcp_config": ".cursor/mcp.json",
    },
    "windsurf": {
        "config_dir": ".windsurfrules",
        "display_name": "Windsurf",
        "default_config": ".windsurfrules",
        "rules_dir": ".windsurfrules",
        "mcp_config": ".windsurf/mcp.json",
    },
}


class IdentityManager:
    """
    客户端身份管理器

    用法：
        mgr = IdentityManager()
        # 自动检测
        who = mgr.detect_client("/path/to/workspace")
        # 显式注册
        mgr.register("codebuddy", workspace="/path/to/workspace")
        # 获取当前客户端
        client = mgr.get_active_client()
    """

    _instance: Optional["IdentityManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_init_done"):
            return
        self._init_done = True
        self._registry_file = Path("data/.client_registry.json")
        self._registry: Dict = {}
        self._active_client: Optional[str] = None
        self._active_workspace: Optional[str] = None
        self._session_start = datetime.now().isoformat()
        self._call_history: List[dict] = []
        self._load_registry()

    # ---- 注册表持久化 ----

    def _load_registry(self):
        """加载客户端注册表"""
        if self._registry_file.exists():
            try:
                with open(self._registry_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._registry = data.get("clients", {})
                self._active_client = data.get("last_active")
                self._active_workspace = data.get("last_workspace")
            except Exception:
                self._registry = {}

    def _save_registry(self):
        """保存客户端注册表"""
        self._registry_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._registry_file, "w", encoding="utf-8") as f:
            json.dump({
                "clients": self._registry,
                "last_active": self._active_client,
                "last_workspace": self._active_workspace,
                "updated_at": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    # ---- 注册 ----

    def register(self, client_name: str, workspace_root: str = "",
                 extra: dict = None) -> dict:
        """
        注册一个AI客户端
        
        client_name: 'codebuddy' | 'trae' | 'cursor' | 自定义名称
        workspace_root: 工作区根路径（用于后续自动识别）
        """
        normalized = client_name.lower().strip()
        if normalized not in KNOWN_CLIENTS:
            # 未知客户端 - 仍然允许注册
            pass

        entry = {
            "name": normalized,
            "display_name": KNOWN_CLIENTS.get(normalized, {}).get("display_name", client_name),
            "workspace_root": str(Path(workspace_root).resolve()) if workspace_root else "",
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "call_count": self._registry.get(normalized, {}).get("call_count", 0) + 1,
            "extra": extra or {},
        }

        if workspace_root:
            entry["has_config_dir"] = (Path(workspace_root) / 
                                       KNOWN_CLIENTS.get(normalized, {}).get("config_dir", ".unknown")).exists()

        self._registry[normalized] = entry
        self._active_client = normalized
        self._active_workspace = workspace_root
        self._save_registry()

        return {
            "registered": True,
            "client": normalized,
            "display_name": entry["display_name"],
            "workspace": workspace_root,
            "known_type": normalized in KNOWN_CLIENTS,
        }

    # ---- 检测 ----

    def detect_client(self, workspace_path: str = None) -> dict:
        """
        自动检测当前运行的AI客户端
        
        检测方法：
        1. 扫描工作区中的 .codebuddy/ .trae/ 目录
        2. 如果提供了操作文件路径，分析路径特征
        3. 返回最可能的客户端 + 置信度
        """
        result = {
            "detected": None,
            "confidence": 0.0,
            "candidates": [],
            "method": "unknown",
        }

        candidates = []

        # 方法1：扫描工作区
        if workspace_path:
            ws = Path(workspace_path)
            for name, info in KNOWN_CLIENTS.items():
                config_path = ws / info["config_dir"]
                if config_path.exists() and config_path.is_dir():
                    candidates.append({
                        "name": name,
                        "display_name": info["display_name"],
                        "confidence": 0.9,
                        "evidence": f"找到 {info['config_dir']}/ 目录",
                        "method": "workspace_scan",
                    })

        # 方法2：从已注册的工作区匹配
        if not candidates:
            for name, info in self._registry.items():
                if info.get("workspace_root"):
                    candidates.append({
                        "name": name,
                        "display_name": info.get("display_name", name),
                        "confidence": 0.6,
                        "evidence": f"已注册的客户端 (工作区: {info['workspace_root']})",
                        "method": "registry_match",
                    })

        # 方法3：从最近活跃推断
        if not candidates and self._active_client:
            candidates.append({
                "name": self._active_client,
                "display_name": self._active_client,
                "confidence": 0.3,
                "evidence": "最近活跃的客户端",
                "method": "last_active",
            })

        if candidates:
            best = max(candidates, key=lambda c: c["confidence"])
            result["detected"] = best["name"]
            result["display_name"] = best.get("display_name", best["name"])
            result["confidence"] = best["confidence"]
            result["method"] = best["method"]
            result["evidence"] = best.get("evidence", "")

        result["candidates"] = candidates
        return result

    def detect_from_path(self, file_path: str) -> Optional[str]:
        """
        从操作的文件路径推断客户端
        例如: .../project/.codebuddy/rules/... → codebuddy
        """
        p = Path(file_path)
        parts = p.parts

        for name, info in KNOWN_CLIENTS.items():
            if info["config_dir"] in parts:
                return name

        return None

    # ---- 查询 ----

    def get_active_client(self) -> dict:
        """获取当前活跃客户端信息"""
        if not self._active_client:
            return {
                "known": False,
                "message": "未知客户端，尚未注册。请调用 devpartner_register 进行注册。",
            }

        info = self._registry.get(self._active_client, {})
        return {
            "known": True,
            "client": self._active_client,
            "display_name": info.get("display_name", self._active_client),
            "workspace": info.get("workspace_root", ""),
            "registered_at": info.get("registered_at", ""),
            "last_seen": info.get("last_seen", ""),
            "call_count": info.get("call_count", 0),
        }

    def get_all_clients(self) -> list[dict]:
        """获取所有已注册的客户端"""
        return [
            {
                "name": name,
                "display_name": info.get("display_name", name),
                "workspace": info.get("workspace_root", ""),
                "last_seen": info.get("last_seen", ""),
                "call_count": info.get("call_count", 0),
            }
            for name, info in self._registry.items()
        ]

    def record_call(self, tool_name: str):
        """记录一次工具调用"""
        with self._lock:
            self._call_history.append({
                "tool": tool_name,
                "time": datetime.now().isoformat(),
                "client": self._active_client,
            })
            # 只保留最近 100 条
            if len(self._call_history) > 100:
                self._call_history = self._call_history[-100:]

        # 更新 last_seen
        if self._active_client and self._active_client in self._registry:
            self._registry[self._active_client]["last_seen"] = datetime.now().isoformat()
            self._registry[self._active_client]["call_count"] = (
                self._registry[self._active_client].get("call_count", 0) + 1
            )
            # 定期保存
            if self._registry[self._active_client]["call_count"] % 10 == 0:
                self._save_registry()

    def get_recent_calls(self, limit: int = 20) -> list[dict]:
        """获取最近的调用历史"""
        return self._call_history[-limit:]

    def to_tag(self) -> str:
        """生成当前客户端的日志标签"""
        if self._active_client:
            display = self._registry.get(self._active_client, {}).get("display_name", self._active_client)
            return f"[{display}]"
        return "[unknown]"


# 全局单例
def get_identity() -> IdentityManager:
    return IdentityManager()
