"""
日志服务
- 对话日志写入
- Pending log 处理
- 每日日志管理
- 日志归档与清理
"""
import json
import os
import re
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional


class LogService:
    """对话日志服务"""

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
        """获取数据目录（从配置读取，有cloud_sync则优先sync路径）"""
        try:
            from core.config import get_config
            cfg = get_config()
            if cfg.cloud_sync.data_root:
                return Path(cfg.cloud_sync.data_root)
        except Exception:
            pass
        return Path("data")

    def write_pending_log(self, data: dict) -> str:
        """写入待处理日志（给 Hook 消费）"""
        data_dir = self._get_data_dir()
        pending_file = data_dir / ".pending_log.json"
        pending_file.parent.mkdir(parents=True, exist_ok=True)

        # 注入客户端信息
        try:
            from core.identity import get_identity
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
        pending_file = Path("data/.pending_log.json")
        if not pending_file.exists():
            return None

        with open(pending_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # 消费后删除
        pending_file.unlink()
        return data

    def append_to_daily_log(self, entry: dict, date_str: str = None) -> str:
        """追加到每日日志文件"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        data_dir = self._get_data_dir()
        log_dir = data_dir / "daily_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"conversation_{date_str}.md"

        # 如果文件不存在，创建文件头
        if not log_file.exists():
            with open(log_file, "w", encoding="utf-8") as f:
                f.write(f"# 对话日志 - {date_str}\n\n")
                f.write(f"> 由 devPartner 自动记录\n\n")
                f.write("---\n\n")

        # 格式化条目
        timestamp = entry.get("timestamp", datetime.now().strftime("%H:%M:%S"))
        lines = [f"## {timestamp} - {entry.get('topic', '无主题')}\n"]

        lines.append(f"- **任务类型**: {entry.get('task_type', '未分类')}")
        lines.append(f"- **用户意图**: {entry.get('user_intent', '')}")
        lines.append(f"- **执行操作**: {entry.get('actions', '')}")

        if entry.get("files_touched"):
            files = entry.get("files_touched", [])
            if isinstance(files, str):
                files = [files]
            lines.append(f"- **涉及文件**: {', '.join(files)}")

        if entry.get("problems"):
            lines.append(f"- **遇到的问题**: {entry.get('problems')}")

        if entry.get("solutions"):
            lines.append(f"- **解决方案**: {entry.get('solutions')}")

        if entry.get("decisions"):
            lines.append(f"- **关键决策**: {entry.get('decisions')}")

        if entry.get("thinking_steps"):
            lines.append("\n### 思考历程")
            steps = entry["thinking_steps"]
            if isinstance(steps, str):
                steps = json.loads(steps)
            for step in steps:
                if isinstance(step, dict):
                    lines.append(f"{step.get('step', '')}. [{step.get('phase', '')}] {step.get('content', '')}")

        if entry.get("key_decisions"):
            lines.append("\n### 关键决策")
            decisions = entry["key_decisions"]
            if isinstance(decisions, str):
                decisions = json.loads(decisions)
            for d in decisions:
                if isinstance(d, dict):
                    lines.append(f"- **{d.get('decision', '')}**: {d.get('reason', '')}")
                    if d.get("alternatives"):
                        alts = d.get("alternatives", [])
                        if isinstance(alts, list):
                            lines.append(f"  - 备选: {', '.join(alts)}")

        if entry.get("self_reflection"):
            lines.append(f"\n### 自我反省\n{entry.get('self_reflection')}")

        lines.append("\n---\n")

        with open(log_file, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return str(log_file)

    def read_daily_log(self, date_str: str = None) -> str:
        """读取每日日志"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        data_dir = self._get_data_dir()
        log_file = data_dir / "daily_logs" / f"conversation_{date_str}.md"
        if not log_file.exists():
            return json.dumps({"error": f"日志文件不存在: {date_str}"}, ensure_ascii=False)

        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        return json.dumps({
            "date": date_str,
            "content": content,
            "size_bytes": log_file.stat().st_size,
        }, ensure_ascii=False)

    def list_logs(self) -> list[dict]:
        """列出所有日志文件"""
        data_dir = self._get_data_dir()
        log_dir = data_dir / "daily_logs"
        if not log_dir.exists():
            return []

        logs = []
        for f in sorted(log_dir.glob("conversation_*.md"), reverse=True):
            date_match = re.search(r"conversation_(\d{4}-\d{2}-\d{2})\.md", f.name)
            date_str = date_match.group(1) if date_match else ""
            logs.append({
                "date": date_str,
                "file": f.name,
                "size_bytes": f.stat().st_size,
                "path": str(f),
            })

        return logs

    def get_logs_range(self, start_date: str, end_date: str) -> list[dict]:
        """获取日期范围内的日志"""
        logs = self.list_logs()
        return [log for log in logs if start_date <= log["date"] <= end_date]

    def archive_old_logs(self, days: int = 30):
        """归档旧日志"""
        cutoff = datetime.now() - timedelta(days=days)
        archive_dir = Path("data/logs_archive")
        archive_dir.mkdir(parents=True, exist_ok=True)

        log_dir = Path("data/daily_logs")
        if not log_dir.exists():
            return

        import shutil
        archived = []

        for f in log_dir.glob("conversation_*.md"):
            date_match = re.search(r"conversation_(\d{4}-\d{2}-\d{2})\.md", f.name)
            if date_match:
                log_date = datetime.strptime(date_match.group(1), "%Y-%m-%d")
                if log_date < cutoff:
                    archive_path = archive_dir / f.name
                    shutil.move(str(f), str(archive_path))
                    archived.append(f.name)

        return archived

    def gap_check(self, date_str: str = None) -> dict:
        """检查日志间隙"""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        log_file = Path(f"data/daily_logs/conversation_{date_str}.md")
        if not log_file.exists():
            return {"has_gaps": False, "message": "今日暂无日志"}

        with open(log_file, "r", encoding="utf-8") as f:
            content = f.read()

        # 提取所有时间戳
        timestamps = re.findall(r"## (\d{2}:\d{2}:\d{2})", content)

        gaps = []
        for i in range(1, len(timestamps)):
            t1 = datetime.strptime(timestamps[i - 1], "%H:%M:%S")
            t2 = datetime.strptime(timestamps[i], "%H:%M:%S")
            diff_minutes = (t2 - t1).total_seconds() / 60
            if diff_minutes > 30:  # 超过30分钟算间隙
                gaps.append({
                    "from": timestamps[i - 1],
                    "to": timestamps[i],
                    "gap_minutes": int(diff_minutes),
                })

        return {
            "has_gaps": len(gaps) > 0,
            "gap_count": len(gaps),
            "gaps": gaps,
            "total_entries": len(timestamps),
        }


def get_log_service() -> LogService:
    return LogService()
