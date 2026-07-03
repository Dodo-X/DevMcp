"""
模块间协作消息服务
==================
用于 devpartner-tools 和 devpartner-agent 两个模块间的内部通信。

定位：纯工具层 ↔ 智能管家层的内部消息传递
  - 读写 module_dialogue.md
  - 检测新消息
  - 生成回复
  - 管理已读状态

注意：这不是面向 CodeBuddy/Trae/用户的跨AI对话，
      而是 devPartner 内部两个模块之间的协作机制。
"""
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional


class DialogueService:
    """模块间协作消息管理服务"""

    _instance: Optional["DialogueService"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        # 从配置读取路径，失败时使用默认值
        try:
            from devpartner_agent.core.config import get_config
            cfg = get_config()
            data_root = cfg.data.root_dir
            self._dialogue_file = Path(data_root) / "module_dialogue.md"
            self._state_file = Path(data_root) / ".module_dialogue_state.json"
            self._pending_file = Path(data_root) / ".pending_module_dialogue.json"
        except Exception:
            data_root = "data"
            self._dialogue_file = Path("data/module_dialogue.md")
            self._state_file = Path("data/.module_dialogue_state.json")
            self._pending_file = Path("data/.pending_module_dialogue.json")
        self._initialized = True

    def configure(self, dialogue_file: str, state_file: str, pending_file: str):
        """配置文件路径"""
        self._dialogue_file = Path(dialogue_file)
        self._state_file = Path(state_file)
        self._pending_file = Path(pending_file)

    def read_dialogue(self) -> str:
        """读取模块协作消息文件"""
        if not self._dialogue_file.exists():
            return json.dumps({"entries": [], "message": "模块对话文件不存在"}, ensure_ascii=False)

        with open(self._dialogue_file, "r", encoding="utf-8") as f:
            content = f.read()

        return json.dumps({
            "file": str(self._dialogue_file),
            "content": content,
            "size": len(content),
        }, ensure_ascii=False)

    def parse_entries(self) -> list[dict]:
        """解析模块对话文件中的所有条目"""
        if not self._dialogue_file.exists():
            return []

        with open(self._dialogue_file, "r", encoding="utf-8") as f:
            content = f.read()

        entries = []
        # 匹配条目或回复
        pattern = r'## (条目|回复) #(\d+)\n(.*?)(?=\n## |\n---\n## |$)'
        matches = re.findall(pattern, content, re.DOTALL)

        for match in matches:
            entry_type, entry_id, body = match
            entry = {
                "type": entry_type,
                "id": int(entry_id),
                "body": body.strip(),
            }

            # 提取元数据（模块间消息）
            time_match = re.search(r'时间.*?(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', body)
            from_match = re.search(r'来自.*?(devpartner-tools|devpartner-agent|tools|agent)', body)
            to_match = re.search(r'写给.*?(devpartner-tools|devpartner-agent|tools|agent)', body)
            priority_match = re.search(r'优先级.*?(high|medium|low)', body)

            entry["time"] = time_match.group(1) if time_match else ""
            entry["from"] = from_match.group(1) if from_match else ""
            entry["to"] = to_match.group(1) if to_match else ""
            entry["priority"] = priority_match.group(1) if priority_match else "medium"

            entries.append(entry)

        return entries

    def get_new_entries(self) -> list[dict]:
        """获取写给当前模块的新条目"""
        all_entries = self.parse_entries()
        read_ids = self._get_read_state()

        new_entries = []
        for entry in all_entries:
            if entry["id"] not in read_ids:
                # 检查是否写给当前模块（devpartner-agent 或 devpartner-tools）
                to_field = entry["to"].lower()
                if any(name in to_field for name in ["devpartner-agent", "agent", "devpartner-tools", "tools"]):
                    new_entries.append(entry)

        return new_entries

    def write_entry(self, content: str, to: str = "devpartner-tools",
                    entry_type: str = "条目", priority: str = "medium") -> dict:
        """写入新条目到模块对话文件"""
        # 确保文件存在
        self._dialogue_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._dialogue_file.exists():
            with open(self._dialogue_file, "w", encoding="utf-8") as f:
                f.write("# devPartner 模块协作消息记录\n\n")
                f.write("> devpartner-tools ↔ devpartner-agent 内部通信\n\n")

        # 获取下一个 ID
        existing = self.parse_entries()
        existing_replies = re.findall(r'## 回复 条目 #(\d+)', 
                                       self._dialogue_file.read_text(encoding="utf-8") 
                                       if self._dialogue_file.exists() else "")
        max_id = max(
            [e["id"] for e in existing] + [int(r) for r in existing_replies] + [0]
        )
        next_id = max_id + 1

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry = f"""
---
## {entry_type} #{next_id}
- **时间**: {timestamp}
- **来自**: devpartner-agent
- **写给**: {to}
- **优先级**: {priority}
- **类型**: 通知 / 建议 / 问题报告 / 设计讨论

### 内容

{content}
"""

        with open(self._dialogue_file, "a", encoding="utf-8") as f:
            f.write(entry)

        return {
            "success": True,
            "entry_id": next_id,
            "file": str(self._dialogue_file),
        }

    def write_reply(self, entry_id: int, content: str, to: str = "devpartner-tools") -> dict:
        """回复指定条目"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        reply = f"""
---
## 回复 条目 #{entry_id}
- **时间**: {timestamp}
- **来自**: devpartner-agent
- **写给**: {to}

### 回复内容

{content}
"""

        with open(self._dialogue_file, "a", encoding="utf-8") as f:
            f.write(reply)

        return {
            "success": True,
            "reply_to": entry_id,
            "file": str(self._dialogue_file),
        }

    def mark_as_read(self, entry_ids: list[int]):
        """标记条目为已读"""
        read_ids = self._get_read_state()
        for eid in entry_ids:
            if eid not in read_ids:
                read_ids.append(eid)
        self._save_read_state(read_ids)

    def mark_all_as_read(self):
        """标记所有条目为已读"""
        all_entries = self.parse_entries()
        all_ids = [e["id"] for e in all_entries]
        self._save_read_state(all_ids)

    def _get_read_state(self) -> list[int]:
        """获取已读状态"""
        if self._state_file.exists():
            with open(self._state_file, "r", encoding="utf-8") as f:
                return json.load(f).get("read_ids", [])
        return []

    def _save_read_state(self, read_ids: list[int]):
        """保存已读状态"""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump({
                "read_ids": read_ids,
                "last_update": datetime.now().isoformat(),
            }, f, ensure_ascii=False, indent=2)

    def check_for_messages(self) -> dict:
        """检查是否有来自其他模块的新消息"""
        new_entries = self.get_new_entries()

        if new_entries:
            # 写入 pending 通知
            self._pending_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._pending_file, "w", encoding="utf-8") as f:
                json.dump({
                    "has_new": True,
                    "count": len(new_entries),
                    "new_entries": [{"id": e["id"], "from": e["from"], "priority": e["priority"]} 
                                    for e in new_entries],
                    "timestamp": datetime.now().isoformat(),
                }, f, ensure_ascii=False, indent=2)

            return {"has_new": True, "count": len(new_entries), "entries": new_entries}
        else:
            # 清除 pending
            if self._pending_file.exists():
                self._pending_file.unlink()
            return {"has_new": False, "count": 0, "entries": []}

    def get_statistics(self) -> dict:
        """获取模块间对话统计"""
        entries = self.parse_entries()
        by_from = {}
        by_to = {}
        by_priority = {"high": 0, "medium": 0, "low": 0}

        for e in entries:
            by_from[e["from"]] = by_from.get(e["from"], 0) + 1
            by_to[e["to"]] = by_to.get(e["to"], 0) + 1
            if e["priority"] in by_priority:
                by_priority[e["priority"]] += 1

        return {
            "total_entries": len(entries),
            "by_from": by_from,
            "by_to": by_to,
            "by_priority": by_priority,
            "file": str(self._dialogue_file),
        }


def get_dialogue() -> DialogueService:
    return DialogueService()
