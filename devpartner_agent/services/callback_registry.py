"""
回调注册表 (v5.2)
==================
管理客户端注册的回调函数，支持任务进度通知和完成通知。

核心功能：
  - 回调注册（on_progress / on_complete / on_error）
  - 按 task_id 或 conversation_id 查找回调
  - 回调触发（同步/异步）
  - 回调生命周期管理（超时清理、注册过期）

设计原则：
  - 线程安全（RLock）
  - 内存友好（定期清理过期注册）
  - 容错（单个回调失败不影响其他回调）
  - 可观测（注册/触发日志）

使用示例：
    registry = CallbackRegistry()

    # 注册回调
    reg_id = registry.register(
        conversation_id="conv_abc",
        on_complete=lambda result: print(f"Done: {result}"),
        on_progress=lambda pct: print(f"Progress: {pct}%"),
        on_error=lambda err: print(f"Error: {err}"),
    )

    # 触发回调
    registry.trigger_progress("conv_abc", 50.0, "分析中...")
    registry.trigger_complete("conv_abc", {"status": "success"})
"""
import uuid
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class CallbackType(str, Enum):
    """回调类型"""
    ON_PROGRESS = "on_progress"
    ON_COMPLETE = "on_complete"
    ON_ERROR = "on_error"
    ON_STEP_START = "on_step_start"
    ON_STEP_COMPLETE = "on_step_complete"


@dataclass
class CallbackRegistration:
    """回调注册记录"""
    registration_id: str
    conversation_id: str
    task_id: Optional[str] = None
    on_progress: Optional[Callable[[float, str], None]] = None
    on_complete: Optional[Callable[[Dict[str, Any]], None]] = None
    on_error: Optional[Callable[[str], None]] = None
    on_step_start: Optional[Callable[[str, str], None]] = None   # step_id, step_name
    on_step_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None  # step_id, result
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    expires_at: Optional[str] = None        # 过期时间
    ttl_seconds: int = 3600                 # 默认 TTL 1 小时
    triggered_count: int = 0                # 已触发次数
    last_triggered_at: Optional[str] = None
    is_active: bool = True


class CallbackRegistry:
    """
    回调注册表管理器

    特性：
      - 支持多种回调类型（进度/完成/错误/步骤开始/步骤结束）
      - 按 conversation_id 或 task_id 索引
      - 线程安全（可重入锁）
      - TTL 过期自动清理
      - 触发日志记录
      - 容错：单个回调异常不影响后续触发
    """

    _instance: Optional["CallbackRegistry"] = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

        # ── 核心数据结构 ──
        self._registrations: Dict[str, CallbackRegistration] = {}
        # 索引：conversation_id → [registration_ids]
        self._by_conversation: Dict[str, List[str]] = {}
        # 索引：task_id → [registration_ids]
        self._by_task: Dict[str, List[str]] = {}

        # ── 统计信息 ──
        self._stats = {
            "total_registered": 0,
            "total_triggered": 0,
            "total_cleaned": 0,
            "total_errors": 0,
        }

        # ── 清理线程 ──
        self._shutdown_flag = False
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="callback_cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()
        logger.info("📞 回调注册表已启动")

    # ══════════════════════════════════════════════════════════
    # 注册 API
    # ══════════════════════════════════════════════════════════

    def register(
        self,
        conversation_id: str,
        task_id: Optional[str] = None,
        on_progress: Optional[Callable[[float, str], None]] = None,
        on_complete: Optional[Callable[[Dict[str, Any]], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_step_start: Optional[Callable[[str, str], None]] = None,
        on_step_complete: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        ttl_seconds: int = 3600,
    ) -> str:
        """
        注册回调函数

        Args:
            conversation_id: 关联的会话ID
            task_id: 关联的任务ID（可选）
            on_progress: 进度回调 (percentage: float, message: str) -> None
            on_complete: 完成回调 (result: dict) -> None
            on_error: 错误回调 (error_message: str) -> None
            on_step_start: 步骤开始回调 (step_id: str, step_name: str) -> None
            on_step_complete: 步骤完成回调 (step_id: str, result: dict) -> None
            ttl_seconds: 回调有效期（秒），默认 1 小时

        Returns:
            registration_id: 唯一注册ID，用于取消注册
        """
        reg_id = f"cb_{uuid.uuid4().hex[:12]}"
        now = datetime.now()

        registration = CallbackRegistration(
            registration_id=reg_id,
            conversation_id=conversation_id,
            task_id=task_id,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            on_step_start=on_step_start,
            on_step_complete=on_step_complete,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(),
            ttl_seconds=ttl_seconds,
        )

        with self._lock:
            self._registrations[reg_id] = registration
            self._by_conversation.setdefault(conversation_id, []).append(reg_id)
            if task_id:
                self._by_task.setdefault(task_id, []).append(reg_id)
            self._stats["total_registered"] += 1

        logger.info(f"📞 注册回调: {reg_id} | 会话: {conversation_id}"
                    f"{f' | 任务: {task_id}' if task_id else ''}")
        return reg_id

    # ══════════════════════════════════════════════════════════
    # 触发 API
    # ══════════════════════════════════════════════════════════

    def trigger_progress(
        self,
        conversation_id: str,
        percentage: float,
        message: str = "",
        task_id: Optional[str] = None,
    ) -> int:
        """
        触发进度回调

        Args:
            conversation_id: 会话ID
            percentage: 进度百分比（0.0-100.0）
            message: 进度描述
            task_id: 任务ID（可选，更精确匹配）

        Returns:
            触发成功数
        """
        registrations = self._find_registrations(conversation_id, task_id)
        triggered = 0

        for reg in registrations:
            if reg.on_progress and reg.is_active:
                try:
                    reg.on_progress(percentage, message)
                    reg.triggered_count += 1
                    reg.last_triggered_at = datetime.now().isoformat()
                    triggered += 1
                except Exception as e:
                    logger.error(f"❌ 进度回调执行失败: {reg.registration_id} | {e}")
                    with self._lock:
                        self._stats["total_errors"] += 1

        with self._lock:
            self._stats["total_triggered"] += triggered

        if triggered > 0:
            logger.debug(f"📞 触发进度回调: {conversation_id} | {percentage:.1f}% | {triggered} 个")

        return triggered

    def trigger_complete(
        self,
        conversation_id: str,
        result: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> int:
        """
        触发完成回调

        Args:
            conversation_id: 会话ID
            result: 完成结果字典
            task_id: 任务ID（可选）

        Returns:
            触发成功数
        """
        registrations = self._find_registrations(conversation_id, task_id)
        triggered = 0

        for reg in registrations:
            if reg.on_complete and reg.is_active:
                try:
                    reg.on_complete(result)
                    reg.triggered_count += 1
                    reg.last_triggered_at = datetime.now().isoformat()
                    triggered += 1
                except Exception as e:
                    logger.error(f"❌ 完成回调执行失败: {reg.registration_id} | {e}")
                    with self._lock:
                        self._stats["total_errors"] += 1

        with self._lock:
            self._stats["total_triggered"] += triggered

        if triggered > 0:
            logger.info(f"📞 触发完成回调: {conversation_id} | {triggered} 个")

        return triggered

    def trigger_error(
        self,
        conversation_id: str,
        error_message: str,
        task_id: Optional[str] = None,
    ) -> int:
        """
        触发错误回调

        Args:
            conversation_id: 会话ID
            error_message: 错误信息
            task_id: 任务ID（可选）

        Returns:
            触发成功数
        """
        registrations = self._find_registrations(conversation_id, task_id)
        triggered = 0

        for reg in registrations:
            if reg.on_error and reg.is_active:
                try:
                    reg.on_error(error_message)
                    reg.triggered_count += 1
                    reg.last_triggered_at = datetime.now().isoformat()
                    triggered += 1
                except Exception as e:
                    logger.error(f"❌ 错误回调执行失败: {reg.registration_id} | {e}")
                    with self._lock:
                        self._stats["total_errors"] += 1

        with self._lock:
            self._stats["total_triggered"] += triggered

        if triggered > 0:
            logger.info(f"📞 触发错误回调: {conversation_id} | {triggered} 个")

        return triggered

    def trigger_step_start(
        self,
        conversation_id: str,
        step_id: str,
        step_name: str,
        task_id: Optional[str] = None,
    ) -> int:
        """触发步骤开始回调"""
        registrations = self._find_registrations(conversation_id, task_id)
        triggered = 0

        for reg in registrations:
            if reg.on_step_start and reg.is_active:
                try:
                    reg.on_step_start(step_id, step_name)
                    reg.triggered_count += 1
                    reg.last_triggered_at = datetime.now().isoformat()
                    triggered += 1
                except Exception as e:
                    logger.error(f"❌ 步骤开始回调失败: {reg.registration_id} | {e}")

        return triggered

    def trigger_step_complete(
        self,
        conversation_id: str,
        step_id: str,
        result: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> int:
        """触发步骤完成回调"""
        registrations = self._find_registrations(conversation_id, task_id)
        triggered = 0

        for reg in registrations:
            if reg.on_step_complete and reg.is_active:
                try:
                    reg.on_step_complete(step_id, result)
                    reg.triggered_count += 1
                    reg.last_triggered_at = datetime.now().isoformat()
                    triggered += 1
                except Exception as e:
                    logger.error(f"❌ 步骤完成回调失败: {reg.registration_id} | {e}")

        return triggered

    # ══════════════════════════════════════════════════════════
    # 管理 API
    # ══════════════════════════════════════════════════════════

    def unregister(self, registration_id: str) -> bool:
        """
        取消注册回调

        Args:
            registration_id: 注册ID

        Returns:
            是否成功取消
        """
        with self._lock:
            reg = self._registrations.pop(registration_id, None)
            if reg is None:
                return False

            # 清理索引
            if reg.conversation_id in self._by_conversation:
                self._by_conversation[reg.conversation_id].remove(registration_id)
                if not self._by_conversation[reg.conversation_id]:
                    del self._by_conversation[reg.conversation_id]

            if reg.task_id and reg.task_id in self._by_task:
                self._by_task[reg.task_id].remove(registration_id)
                if not self._by_task[reg.task_id]:
                    del self._by_task[reg.task_id]

            reg.is_active = False

        logger.info(f"📞 取消注册回调: {registration_id}")
        return True

    def unregister_by_conversation(self, conversation_id: str) -> int:
        """取消指定会话的所有回调"""
        with self._lock:
            reg_ids = list(self._by_conversation.get(conversation_id, []))
        count = 0
        for reg_id in reg_ids:
            if self.unregister(reg_id):
                count += 1
        return count

    def get_registration(self, registration_id: str) -> Optional[dict]:
        """获取回调注册详情"""
        with self._lock:
            reg = self._registrations.get(registration_id)
            if reg is None:
                return None
            return {
                "registration_id": reg.registration_id,
                "conversation_id": reg.conversation_id,
                "task_id": reg.task_id,
                "has_progress": reg.on_progress is not None,
                "has_complete": reg.on_complete is not None,
                "has_error": reg.on_error is not None,
                "created_at": reg.created_at,
                "expires_at": reg.expires_at,
                "triggered_count": reg.triggered_count,
                "last_triggered_at": reg.last_triggered_at,
                "is_active": reg.is_active,
            }

    def get_stats(self) -> dict:
        """获取注册表统计信息"""
        with self._lock:
            active_count = sum(1 for r in self._registrations.values() if r.is_active)
            return {
                **self._stats,
                "active_registrations": active_count,
                "total_registrations": len(self._registrations),
                "conversations_with_callbacks": len(self._by_conversation),
                "tasks_with_callbacks": len(self._by_task),
            }

    # ══════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════

    def _find_registrations(
        self, conversation_id: str, task_id: Optional[str] = None
    ) -> List[CallbackRegistration]:
        """查找匹配的回调注册"""
        with self._lock:
            reg_ids = set()

            # 按 conversation_id 查找
            if conversation_id in self._by_conversation:
                reg_ids.update(self._by_conversation[conversation_id])

            # 按 task_id 查找
            if task_id and task_id in self._by_task:
                reg_ids.update(self._by_task[task_id])

            registrations = []
            now = datetime.now()

            for reg_id in reg_ids:
                reg = self._registrations.get(reg_id)
                if reg is None or not reg.is_active:
                    continue

                # 检查是否过期
                if reg.expires_at:
                    try:
                        expires = datetime.fromisoformat(reg.expires_at)
                        if now > expires:
                            reg.is_active = False
                            continue
                    except (ValueError, TypeError):
                        pass

                registrations.append(reg)

            return registrations

    def _cleanup_loop(self):
        """定期清理过期注册"""
        while not self._shutdown_flag:
            time.sleep(300)  # 每 5 分钟清理一次

            try:
                now = datetime.now()
                to_remove = []

                with self._lock:
                    for reg_id, reg in list(self._registrations.items()):
                        if not reg.is_active:
                            to_remove.append(reg_id)
                            continue
                        if reg.expires_at:
                            try:
                                expires = datetime.fromisoformat(reg.expires_at)
                                if now > expires:
                                    to_remove.append(reg_id)
                            except (ValueError, TypeError):
                                pass

                for reg_id in to_remove:
                    self.unregister(reg_id)

                if to_remove:
                    with self._lock:
                        self._stats["total_cleaned"] += len(to_remove)
                    logger.info(f"🧹 清理过期回调: {len(to_remove)} 个")

            except Exception as e:
                logger.error(f"❌ 回调清理失败: {e}")

    def shutdown(self):
        """关闭回调注册表"""
        logger.info("📞 正在关闭回调注册表...")
        self._shutdown_flag = True

        with self._lock:
            for reg in self._registrations.values():
                reg.is_active = False
            self._registrations.clear()
            self._by_conversation.clear()
            self._by_task.clear()

        logger.info("✅ 回调注册表已关闭")


def get_callback_registry() -> CallbackRegistry:
    """获取全局回调注册表单例"""
    return CallbackRegistry()
