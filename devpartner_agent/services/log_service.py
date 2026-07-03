"""
日志服务 (v5.2 精简版)
- Pending log 处理（跨进程临时通知）
- Markdown 文件日志已废弃（v6.2 起），数据统一存储在 SQLite

注意：append_to_daily_log / read_daily_log / list_logs / archive_old_logs
等 Markdown 文件操作方法已在 v5.2 中移除。对话数据通过 database.py
的 conversations + conversation_archive 表统一管理。
"""
import json
from pathlib import Path
from typing import Optional


class LogService:
    """轻量日志服务 — 仅保留 pending log 机制"""

    _instance: Optional["LogService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

    def _get_data_dir(self) -> Path:
        """获取数据根目录"""
        try:
            from devpartner_agent.core.config import get_config
            return Path(get_config().data.root_dir)
        except Exception:
            return Path("data")

    def write_pending_log(self, data: dict) -> str:
        """写入待处理日志（跨进程通知）"""
        data_dir = self._get_data_dir()
        pending_file = data_dir / ".pending_log.json"
        pending_file.parent.mkdir(parents=True, exist_ok=True)

        # 注入客户端信息
        try:
            from devpartner_agent.core.identity import get_identity
            identity = get_identity()
            active = identity.get_active_client()
            if active.get("known") and "client" not in data:
                data["client"] = active["client"]
        except Exception:
            pass

        with open(pending_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        return str(pending_file)

    def consume_pending_log(self) -> Optional[dict]:
        """消费待处理日志"""
        pending_file = self._get_data_dir() / ".pending_log.json"
        if not pending_file.exists():
            return None

        with open(pending_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 消费后删除
        pending_file.unlink()
        return data


def get_log_service() -> LogService:
    return LogService()
