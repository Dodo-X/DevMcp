"""
文件监控服务 (v4.4.0)
======================
后台线程监控统一的对话记忆路径，自动解析对话内容并存入数据库。

设计要点：
- 单一监控路径（可配置），所有客户端统一输出到该路径
- 文件内容中标记来源（source）
- 增量监控：只处理新增/修改的文件
- 自动调用 ConversationAnalyzer 进行分析
- 可选 LLM 增强 Markdown 解析（llama-cpp-python）
- 支持多客户端兼容（CodeBuddy/Cursor/Windsurf/Trae/自定义）
"""

import os
import re
import json
import threading
import time
from pathlib import Path
from datetime import datetime
from typing import Optional


# ── 默认监控路径（可通过环境变量覆盖）──
# 默认指向 data/memories，所有客户端统一输出到此处
DEFAULT_MEMORY_PATH = "data/memories"


class FileWatcher:
    """
    对话文件监控器

    监控统一路径下的 Markdown 文件，自动解析对话内容。
    文件命名规范：YYYY-MM-DD.md（每日日志）或 conversation_*.md
    """

    _instance: Optional["FileWatcher"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        self._watch_path: Optional[Path] = None
        self._known_files: dict[str, float] = {}  # 文件名 → 最后修改时间
        self._processed_conversations: set = set()  # 已处理的对话 ID
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._source = "unknown"
        self._interval = 30  # 扫描间隔（秒）

    def start(self, watch_path: str = None, source: str = None,
              interval: int = 30):
        """
        启动文件监控。

        Args:
            watch_path: 监控路径（None 则使用环境变量或默认值）
            source: 客户端来源标识
            interval: 扫描间隔（秒）
        """
        # 确定监控路径
        if watch_path:
            self._watch_path = Path(watch_path)
        else:
            env_path = os.environ.get("DEVPARTNER_MEMORY_PATH", DEFAULT_MEMORY_PATH)
            self._watch_path = Path(env_path)

        if not self._watch_path.is_absolute():
            # 相对于项目根目录
            from pathlib import Path as _Path
            project_root = _Path(__file__).resolve().parent.parent.parent
            self._watch_path = project_root / self._watch_path

        self._source = source or self._detect_source()
        self._interval = interval

        # 确保目录存在
        self._watch_path.mkdir(parents=True, exist_ok=True)

        # 初始化已知文件列表
        self._scan_known_files()

        # 启动后台线程
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._watch_loop, daemon=True)
            self._thread.start()
            print(f"[INFO] 文件监控已启动: {self._watch_path} (来源: {self._source}, 间隔: {interval}s)")

    def stop(self):
        """停止监控"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            print("[INFO] 文件监控已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def watch_path(self) -> Optional[Path]:
        return self._watch_path

    def _detect_source(self) -> str:
        """
        自动检测客户端来源。
        
        由于统一监控路径 data/memories，来源不再通过路径名检测，
        而是通过文件内容中的 source 标记识别。
        """
        return "unknown"

    def _scan_known_files(self):
        """扫描现有文件"""
        if not self._watch_path or not self._watch_path.exists():
            return

        with self._lock:
            for f in self._watch_path.glob("*.md"):
                self._known_files[f.name] = f.stat().st_mtime

    def _watch_loop(self):
        """后台监控循环"""
        while self._running:
            try:
                self._check_new_files()
            except Exception as e:
                print(f"[WARN] 文件监控异常: {e}")

            time.sleep(self._interval)

    def _check_new_files(self):
        """检查新增和修改的文件"""
        if not self._watch_path or not self._watch_path.exists():
            return

        current_files = {}
        new_or_modified = []

        for f in self._watch_path.glob("*.md"):
            mtime = f.stat().st_mtime
            current_files[f.name] = mtime

            with self._lock:
                if f.name not in self._known_files:
                    new_or_modified.append(("new", f))
                elif mtime > self._known_files[f.name] + 1:  # 1秒容差
                    new_or_modified.append(("modified", f))

        # 更新已知文件
        with self._lock:
            self._known_files = current_files

        # 处理新文件
        for change_type, filepath in new_or_modified:
            try:
                self._process_file(filepath, change_type)
            except Exception as e:
                print(f"[WARN] 处理文件失败 {filepath.name}: {e}")

    def _process_file(self, filepath: Path, change_type: str):
        """
        处理单个对话文件。

        解析文件内容，提取对话条目，调用分析引擎。
        """
        content = filepath.read_text(encoding="utf-8")
        if not content.strip():
            return

        # 提取文件中的日期
        date_match = re.search(r"(\d{4}-\d{2}-\d{2})", filepath.name)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%Y-%m-%d")

        # 尝试 LLM 解析，失败则回退到规则拆分
        conversations = self._split_conversations_with_llm(content, filepath.name, date_str)
        if not conversations:
            conversations = self._split_conversations(content, date_str)

        if conversations:
            from devpartner_agent.services.conversation_analyzer import get_analyzer

            analyzer = get_analyzer()
            processed = 0

            for conv in conversations:
                conv_id = f"{date_str}_{conv.get('time', 'unknown')}_{conv.get('topic_hash', '')}"

                # 去重
                with self._lock:
                    if conv_id in self._processed_conversations:
                        continue
                    self._processed_conversations.add(conv_id)

                # 分析并存储（优先使用条目内 source 标记）
                full_content = conv.get("content", "")
                conv_source = conv.get("source") or self._source
                analyzer.analyze_and_store(
                    content=full_content,
                    source=conv_source,
                    client=conv_source,
                    conversation_id=conv_id,
                )
                processed += 1

            if processed > 0:
                print(f"[INFO] 文件监控: {filepath.name} ({change_type}) → 处理了 {processed} 条对话")

        # 防止 processed_conversations 无限增长
        with self._lock:
            if len(self._processed_conversations) > 10000:
                # 保留最近 5000 条
                self._processed_conversations = set(
                    list(self._processed_conversations)[-5000:]
                )

    def _split_conversations(self, content: str, date_str: str) -> list[dict]:
        """
        将 Markdown 文件内容拆分为对话条目。

        支持格式：
        - ## HH:MM:SS - 标题
        - ## 标题
        - 连续的段落块
        """
        conversations = []

        # 按 ## 标题拆分
        sections = re.split(r'\n(?=## )', content)

        for section in sections:
            if not section.strip():
                continue

            # 跳过文件头（# 一级标题、> 引用）
            if re.match(r'^#\s', section.strip()):
                continue
            if re.match(r'^>\s', section.strip()):
                continue
            if section.strip().startswith('---'):
                continue

            # 提取时间
            time_match = re.search(r'##\s*(\d{2}:\d{2}(?::\d{2})?)', section)
            conv_time = time_match.group(1) if time_match else "00:00"

            # 提取主题（## 后面的标题文本）
            title_match = re.search(r'##\s*(?:\d{2}:\d{2}(?::\d{2})?\s*[-–—]\s*)?(.+?)(?:\n|$)', section)
            topic = title_match.group(1).strip() if title_match else "未分类"

            # 生成内容哈希用于去重
            topic_hash = str(hash(section[:200]))[-8:]

            conversations.append({
                "time": conv_time,
                "topic": topic[:100],
                "topic_hash": topic_hash,
                "content": section.strip(),
            })

        # 如果没有 ## 标题，把整个文件当作一条对话
        if not conversations and content.strip():
            conversations.append({
                "time": "00:00",
                "topic": f"每日记录 - {date_str}",
                "topic_hash": str(hash(content[:200]))[-8:],
                "content": content.strip(),
            })

        return conversations

    def _split_conversations_with_llm(self, content: str, filename: str,
                                      date_str: str) -> list[dict]:
        """使用本地 LLM 解析 Markdown 文件中的对话条目"""
        try:
            from devpartner_agent.services.llm_service import get_llm_service
            llm = get_llm_service()
            conversations = llm.parse_file_conversations(content, filename)
            if conversations:
                return conversations
        except Exception:
            pass
        return []

    def force_scan(self) -> int:
        """强制执行一次全量扫描（用于手动触发）"""
        if not self._watch_path or not self._watch_path.exists():
            return 0

        count = 0
        for f in sorted(self._watch_path.glob("*.md")):
            try:
                self._process_file(f, "force_scan")
                count += 1
            except Exception as e:
                print(f"[WARN] 强制扫描失败 {f.name}: {e}")

        return count

    def get_status(self) -> dict:
        """获取监控状态"""
        return {
            "running": self._running,
            "watch_path": str(self._watch_path) if self._watch_path else None,
            "source": self._source,
            "interval_seconds": self._interval,
            "known_files": len(self._known_files),
            "processed_count": len(self._processed_conversations),
        }


def get_watcher() -> FileWatcher:
    return FileWatcher()
