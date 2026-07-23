"""
异步任务队列 (v9.5.3)
=====================
管理后台任务的异步执行，支持 FIFO 调度、阶段级并发控制、心跳保活和进度报告。

核心职责（仅限调度）：
  ✅ FIFO 先进先出调度
  ✅ 阶段级并发控制（v8.1 新增）
     - step_analysis: 同会话可并行（各自写不同的 step 行）
     - conversation_finalize: 必须等该会话所有 step_analysis 完成（v9.5.3: 最多等 30min）
     - 其他任务: 同会话串行（保守策略）
  ✅ 跨会话并行执行
  ✅ 并发控制（Semaphore = OLLAMA_NUM_PARALLEL, Workers = N*2）
  ✅ 内存占用监控
  ✅ 任务超时处理（v9.5.3: 超时后发送取消信号真正中断 LLM 推理）
  ✅ 失败重试机制
  ✅ 僵尸任务清理
  ✅ 心跳保活（v9.5.1）：长任务定期报告存活状态
  ✅ 进度报告（v9.5.1）：Worker 可更新任务进度和部分结果
  ✅ 取消机制（v9.5.3）：通过 cancel_event 中断 worker 线程的 LLM 推理

v9.5.3 变更（相比 v9.5.1）：
  - _execute_with_timeout: 从 thread.join() 假超时改为 cancel_event 真正可取消
  - _check_phase_ready: PHASE_SEQUENTIAL 任务最多等 30 分钟，超时后强制放行
  - 并发默认值: ollama_num_parallel 从 2 改为 1（CPU 推理串行更快）
"""

import collections
import contextlib
import json
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    DUPLICATE_DISCARDED = "duplicate_discarded"  # v9.6.0: 去重废弃


class TaskPriority:
    CRITICAL = 100
    HIGH = 10
    MEDIUM = 5
    LOW = 1
    BACKGROUND = 0


@dataclass
class QueuedTask:
    task_id: str
    task_data: dict
    enqueue_time: float = field(default_factory=time.time)


class TaskQueue:
    """
    异步任务队列管理器 (v9.5.3 — 可取消超时 + 阶段降级)

    资源策略：
      - 全局并发数: 与 OLLAMA_NUM_PARALLEL 对齐（CPU 推理默认 1）
      - 最大内存阈值: 1.5GB
      - 单任务超时: 10800秒/3小时（v9.5.3: 超时后发送取消信号中断 LLM 推理）
      - 最大重试: 3次
      - PHASE_SEQUENTIAL 等待超时: 30分钟（超时后强制放行，防止永久堵死）

    并发模型（v9.5.3 增强）：
      - step_analysis: 同会话可并行（各自写不同的 step 行）
      - conversation_finalize: 必须等该会话所有 step_analysis 完成，
        但最多等 30 分钟，超时后强制放行
      - 其他任务类型: 同会话串行（保守策略）
      - 不同会话: 始终并行
      - 超时取消: 任务超时后 set cancel_event → infer() 中断 HTTP 调用 → worker 正常退出
    """

    PHASE_PARALLEL = {
        "step_analysis",
        "vault_export_batch",
        "vault_export_all",
        "vault_export_profile",
        "vault_export_project",
        "vault_export_weekly",
        "vault_export_monthly",
        "vault_export_annual",
        "vault_export_daily",
        "cleanup_force",
        "cleanup_vacuum",
        "cleanup_full",
    }
    PHASE_SEQUENTIAL = {
        "conversation_finalize",
        "conversation_analysis",
        "profile_update",
        "knowledge_extraction",
        "system_optimization",
        "daily_summary",
        "daily_export",
    }

    # 大型汇总报告 — 同一时间只允许一个执行（防止 Ollama 资源争抢断开）
    REPORT_TYPES = {
        "daily_summary",
        "weekly_report",
        "monthly_report",
        "annual_report",
        "growth_analysis",
    }

    def __init__(self):
        self._task_queue: collections.deque = collections.deque()
        self._queue_lock = threading.Lock()
        self._task_map: dict[str, dict] = {}
        self._futures: dict[str, Future] = {}

        self._conv_phase_locks: dict[str, threading.Lock] = {}
        self._conv_phase_locks_guard = threading.Lock()

        self._conv_step_counter: dict[str, int] = {}
        self._conv_step_counter_guard = threading.Lock()

        self._conv_finalize_wait: dict[str, threading.Event] = {}
        self._conv_finalize_wait_guard = threading.Lock()

        # v9.5.3: PHASE_SEQUENTIAL 等待超时追踪
        self._seq_wait_start: dict[str, float] = {}

        try:
            from foundation.config.app_settings import get_config

            _cfg = get_config()
            _num_parallel = _cfg.llm.ollama_num_parallel
        except Exception:
            logger.warning("TaskQueue.__init__: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
            _num_parallel = 2

        self._max_concurrent: int = _num_parallel
        self._semaphore: threading.Semaphore = threading.Semaphore(_num_parallel)
        self._report_semaphore: threading.Semaphore = threading.Semaphore(1)  # 大型报告串行化
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=_num_parallel * 2, thread_name_prefix="task_worker_"
        )

        self._max_memory_mb: float = 1536.0
        self._current_memory_mb: float = 0.0
        self._memory_lock = threading.Lock()

        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_cancelled": 0,
            "avg_execution_time_sec": 0.0,
        }
        self._stats_lock = threading.Lock()

        self._handlers: dict[str, Callable[[dict], Any]] = {}

        self._shutdown_flag: bool = False
        self._worker_thread: threading.Thread = threading.Thread(
            target=self._worker_loop, name="task_scheduler_main", daemon=True
        )
        self._worker_thread.start()

        self._retry_thread: threading.Thread = threading.Thread(
            target=self._retry_scheduler_loop, name="task_retry_scheduler", daemon=True
        )
        self._retry_thread.start()

        # v9.7.1: 恢复流水线延迟到 ensure_ready() 末尾执行（handler 注册后），
        # 不再在 __init__ 中调用，避免 handler 未注册时提交注定失败的任务。
        self._recovery_pending: bool = True

        logger.info(
            f"🔄 异步任务队列已启动 (v9.7.1 延迟恢复 | Semaphore={_num_parallel} | Workers={_num_parallel * 2})"
        )

    # ══════════════════════════════════════════════════════════
    # Handler 注册（各模块在启动时注册自己的任务处理器）
    # ══════════════════════════════════════════════════════════

    def register_handler(self, task_type: str, handler: Callable[[dict], Any]):
        """注册任务处理器

        Args:
            task_type: 任务类型标识（如 'step_analysis', 'conversation_finalize'）
            handler: 处理函数，接收 payload dict，返回 result dict
        """
        if task_type in self._handlers:
            logger.warning(f"⚠️ 覆盖已注册的 handler: {task_type}")
        self._handlers[task_type] = handler
        logger.info(f"📝 注册任务处理器: {task_type} → {handler.__qualname__}")

    def get_registered_types(self) -> list:
        """获取已注册的任务类型列表"""
        return list(self._handlers.keys())

    def get_handlers(self) -> list:
        """获取已注册的任务处理器清单（含 phase 分类，供 Dashboard 使用）"""
        handlers = []
        for task_type, handler_fn in self._handlers.items():
            phase = "PARALLEL" if task_type in self.PHASE_PARALLEL else "SEQUENTIAL"
            handlers.append(
                {
                    "name": task_type,
                    "phase": phase,
                    "handler": handler_fn.__qualname__
                    if hasattr(handler_fn, "__qualname__")
                    else str(handler_fn),
                }
            )
        # 按 phase 排序：PARALLEL 在前
        handlers.sort(key=lambda h: (0 if h["phase"] == "PARALLEL" else 1, h["name"]))
        return handlers

    # ══════════════════════════════════════════════════════════
    # 任务提交
    # ══════════════════════════════════════════════════════════

    def submit_task(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: int = TaskPriority.MEDIUM,
        timeout_seconds: int = 10800,
        max_retries: int = 3,
        estimated_memory_mb: int = 100,
        callback: Callable | None = None,
    ) -> str:
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        timestamp = datetime.now().isoformat()

        task_meta = {
            "task_id": task_id,
            "task_type": task_type,
            "payload": payload,
            "status": TaskStatus.PENDING.value,
            "priority": priority,
            "max_retries": max_retries,
            "retry_count": 0,
            "timeout_seconds": timeout_seconds,
            "estimated_memory_mb": estimated_memory_mb,
            "callback": callback.__name__ if callback else None,
            "queued_at": timestamp,
            "started_at": None,
            "completed_at": None,
            "error_message": None,
            "result": None,
            # v9.5.1: 心跳 & 进度
            "last_heartbeat": None,
            "progress": 0.0,
            "partial_result": "",
            "status_note": "",
        }

        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            existing = db.query_local(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM task_queue"
            )
            sort_order = existing[0]["next_order"] if existing else 1
            db.query_local(
                """
                INSERT INTO task_queue (
                    task_id, task_type, payload, status, priority,
                    max_retries, estimated_memory_mb, queued_at, timeout_seconds, sort_order
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """,
                (
                    task_id,
                    task_type,
                    json.dumps(payload, ensure_ascii=False),
                    priority,
                    max_retries,
                    estimated_memory_mb,
                    timestamp,
                    timeout_seconds,
                    sort_order,
                ),
            )
        except Exception as e:
            logger.error(f"❌ 任务持久化失败: {e}")

        with self._queue_lock:
            self._task_queue.append(QueuedTask(task_id, task_meta))

        self._task_map[task_id] = task_meta

        conversation_id = payload.get("conversation_id", "global")
        with self._stats_lock:
            self._stats["total_submitted"] += 1

        logger.info(f"📥 提交任务: {task_id} | 类型: {task_type} | 会话: {conversation_id}")
        return task_id

    def submit(
        self,
        task_type: str,
        payload: dict[str, Any],
        priority: str = "medium",
        timeout_seconds: int = 10800,
        max_retries: int = 3,
        estimated_memory_mb: int = 100,
        callback: Callable | None = None,
    ) -> str:
        """submit_task 的简化别名（v9.6.0: 修复缺失的别名方法）。

        priority 支持字符串形式 ('critical'/'high'/'medium'/'low'/'background')。
        """
        _priority_map = {
            "critical": TaskPriority.CRITICAL,
            "high": TaskPriority.HIGH,
            "medium": TaskPriority.MEDIUM,
            "low": TaskPriority.LOW,
            "background": TaskPriority.BACKGROUND,
        }
        priority_int = _priority_map.get(priority, TaskPriority.MEDIUM)
        return self.submit_task(
            task_type=task_type,
            payload=payload,
            priority=priority_int,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            estimated_memory_mb=estimated_memory_mb,
            callback=callback,
        )

    # ══════════════════════════════════════════════════════════
    # 调度核心（v8.1 阶段级并发控制）
    # ══════════════════════════════════════════════════════════

    def _worker_loop(self):
        _last_zombie_check = 0
        _last_orphan_check = 0
        while not self._shutdown_flag:
            try:
                if time.time() - _last_zombie_check > 60:
                    self._auto_cleanup_zombies()
                    _last_zombie_check = time.time()

                if time.time() - _last_orphan_check > 300:
                    self._auto_cleanup_orphan_steps()
                    _last_orphan_check = time.time()

                task = self._acquire_next_task()
                if task is None:
                    time.sleep(0.5)
                    continue

                task_id = task.task_id
                task_meta = task.task_data
                task_type = task_meta.get("task_type", "")
                conversation_id = task_meta.get("payload", {}).get("conversation_id", "global")

                if not self._check_phase_ready(task_type, conversation_id):
                    # v9.5.4: 阶段锁阻塞时放到队尾，避免死锁
                    # （如果 appendleft，被阻塞的任务会立即回到队首，阻塞整个队列）
                    with self._queue_lock:
                        self._task_queue.append(task)
                    time.sleep(0.5)
                    continue

                if not self._check_resource_availability(task_meta):
                    with self._queue_lock:
                        self._task_queue.appendleft(task)
                    time.sleep(2.0)
                    continue

                self._on_task_start(task_type, conversation_id)

                future = self._executor.submit(
                    self._execute_task_with_phase_tracking,
                    task_id,
                    task_meta,
                    task_type,
                    conversation_id,
                )
                self._futures[task_id] = future

            except Exception as e:
                logger.error(f"❌ Worker loop error: {e}", exc_info=True)
                time.sleep(1.0)

    def _acquire_next_task(self) -> QueuedTask | None:
        """从队列中获取下一个待执行的任务"""
        with self._queue_lock:
            if self._task_queue:
                return self._task_queue.popleft()
            return None

    def _check_phase_ready(self, task_type: str, conversation_id: str) -> bool:
        """检查任务是否满足阶段执行条件。

        v9.5.3: PHASE_SEQUENTIAL 任务在等待 PARALLEL 完成后最多等 30 分钟，
        超时后强制放行，防止 step_analysis 失败导致 finalize 永久堵死。
        """
        if task_type in self.PHASE_PARALLEL:
            return True

        if task_type in self.PHASE_SEQUENTIAL:
            with self._conv_step_counter_guard:
                running_steps = self._conv_step_counter.get(conversation_id, 0)
            if running_steps > 0:
                # v9.5.3: 记录首次等待时间，超时 30 分钟后强制放行
                wait_key = f"seq_wait_{conversation_id}_{task_type}"
                first_wait = getattr(self, "_seq_wait_start", {})
                now = time.time()
                if wait_key not in first_wait:
                    first_wait[wait_key] = now
                    self._seq_wait_start = first_wait
                    logger.info(
                        f"⏳ PHASE_SEQUENTIAL 任务等待 PARALLEL 完成: "
                        f"{task_type} | 会话: {conversation_id} | 剩余并行任务: {running_steps}"
                    )
                elif now - first_wait[wait_key] > 1800:  # 30 分钟
                    logger.warning(
                        f"⚠️ PHASE_SEQUENTIAL 任务等待超时 (30min)，强制放行: "
                        f"{task_type} | 会话: {conversation_id}"
                    )
                    # 清理等待记录，强制放行
                    first_wait.pop(wait_key, None)
                    return True
                return False
            else:
                # PARALLEL 已完成，清理等待记录
                first_wait = getattr(self, "_seq_wait_start", {})
                wait_key = f"seq_wait_{conversation_id}_{task_type}"
                first_wait.pop(wait_key, None)

            phase_lock = self._get_phase_lock(conversation_id)
            if phase_lock.locked():
                return False

        return True

    def _on_task_start(self, task_type: str, conversation_id: str):
        """任务开始前的阶段计数更新"""
        if task_type in self.PHASE_PARALLEL:
            with self._conv_step_counter_guard:
                self._conv_step_counter[conversation_id] = (
                    self._conv_step_counter.get(conversation_id, 0) + 1
                )
        elif task_type in self.PHASE_SEQUENTIAL:
            phase_lock = self._get_phase_lock(conversation_id)
            phase_lock.acquire()

    def _on_task_finish(self, task_type: str, conversation_id: str):
        """任务完成后的阶段计数更新和 finalize 唤醒"""
        if task_type in self.PHASE_PARALLEL:
            with self._conv_step_counter_guard:
                self._conv_step_counter[conversation_id] = (
                    self._conv_step_counter.get(conversation_id, 1) - 1
                )
                if self._conv_step_counter[conversation_id] <= 0:
                    self._conv_step_counter.pop(conversation_id, None)

            with self._conv_step_counter_guard:
                all_done = self._conv_step_counter.get(conversation_id, 0) == 0
            if all_done:
                with self._conv_finalize_wait_guard:
                    event = self._conv_finalize_wait.get(conversation_id)
                if event:
                    event.set()

        elif task_type in self.PHASE_SEQUENTIAL:
            phase_lock = self._get_phase_lock(conversation_id)
            with contextlib.suppress(RuntimeError):
                phase_lock.release()

    def _get_phase_lock(self, conversation_id: str) -> threading.Lock:
        with self._conv_phase_locks_guard:
            if conversation_id not in self._conv_phase_locks:
                self._conv_phase_locks[conversation_id] = threading.Lock()
            return self._conv_phase_locks[conversation_id]

    def _execute_task_with_phase_tracking(
        self, task_id: str, task_meta: dict, task_type: str, conversation_id: str
    ):
        try:
            return self._execute_task_wrapper(task_id, task_meta)
        finally:
            self._on_task_finish(task_type, conversation_id)

    def _check_resource_availability(self, task_meta: dict) -> bool:
        if not self._semaphore.acquire(blocking=False):
            return False
        self._semaphore.release()

        required_memory = task_meta.get("estimated_memory_mb", 100)
        with self._memory_lock:
            available_memory = self._max_memory_mb - self._current_memory_mb
            if required_memory > available_memory * 0.8:
                return False
        return True

    def _execute_task_wrapper(self, task_id: str, task_meta: dict):
        start_time = time.time()
        db = None
        release_event = threading.Event()
        heartbeat_stop = threading.Event()

        acquired = self._semaphore.acquire(timeout=1.0)
        if not acquired:
            logger.warning(f"⚠️ 无法获取并发许可: {task_id}")
            return

        try:
            self._update_task_status(task_id, TaskStatus.RUNNING.value)
            self._update_memory_usage(task_meta.get("estimated_memory_mb", 100), delta=True)

            from backend.core.database.base_conn import get_db

            db = get_db()
            now_ts = datetime.now().isoformat()
            db.query_local(
                """
                UPDATE task_queue SET status = 'running', started_at = ?, last_heartbeat = ?, worker_id = ?
                WHERE task_id = ?
            """,
                (now_ts, now_ts, threading.current_thread().name, task_id),
            )
            if task_id in self._task_map:
                self._task_map[task_id]["started_at"] = now_ts
                self._task_map[task_id]["last_heartbeat"] = now_ts

            # v9.5.1: 启动心跳线程（每 45 秒更新一次）
            def _heartbeat_loop():
                while not heartbeat_stop.is_set():
                    heartbeat_stop.wait(45)
                    if not heartbeat_stop.is_set():
                        self.update_heartbeat(task_id)

            heartbeat_thread = threading.Thread(
                target=_heartbeat_loop, name=f"hb_{task_id[:8]}", daemon=True
            )
            heartbeat_thread.start()

            timeout_seconds = task_meta.get("timeout_seconds", 10800)
            result = self._execute_with_timeout(task_meta, timeout_seconds)

            execution_time = time.time() - start_time

            with self._stats_lock:
                self._stats["total_completed"] += 1
                old_avg = self._stats["avg_execution_time_sec"]
                new_count = self._stats["total_completed"]
                self._stats["avg_execution_time_sec"] = (
                    old_avg * (new_count - 1) + execution_time
                ) / new_count

            self._update_task_status(task_id, TaskStatus.COMPLETED.value, result=result)
            db.query_local(
                """
                UPDATE task_queue SET status = 'completed', result = ?, completed_at = ?, progress = 1.0,
                    actual_memory_mb = ?
                WHERE task_id = ?
            """,
                (
                    json.dumps(result, ensure_ascii=False) if result else None,
                    datetime.now().isoformat(),
                    task_meta.get("estimated_memory_mb", 100),
                    task_id,
                ),
            )

            logger.info(f"✅ 任务完成: {task_id} | 耗时: {execution_time:.2f}s")

            callback_name = task_meta.get("callback")
            if callback_name:
                self._invoke_callback(callback_name, task_id, result)

        except TimeoutError:
            logger.error(f"⏰ 任务超时: {task_id}")
            self._handle_task_failure(task_id, "Timeout exceeded", db, release_event)
            self._update_task_status(task_id, TaskStatus.TIMEOUT.value)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"❌ 任务执行失败: {task_id} | 错误: {error_msg}", exc_info=True)
            self._handle_task_failure(task_id, error_msg, db, release_event)

        finally:
            heartbeat_stop.set()
            self._semaphore.release()
            self._update_memory_usage(task_meta.get("estimated_memory_mb", 100), delta=False)
            release_event.set()

            if db is None:
                try:
                    from backend.core.database.base_conn import get_db

                    db = get_db()
                    db.query_local(
                        "UPDATE task_queue SET status = 'failed', error_message = ? WHERE task_id = ? AND status = 'running'",
                        ("db_unavailable", task_id),
                    )
                except Exception:
                    logger.warning(
                        "TaskQueue._execute_task_wrapper: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    pass

            if task_id in self._futures:
                del self._futures[task_id]

    def _execute_with_timeout(self, task_meta: dict, timeout_seconds: int) -> Any:
        """v9.5.3: 带真正取消能力的超时执行。

        旧版用 thread.join(timeout) 做假超时——超时后只抛异常，
        worker 线程仍在跑、仍在占用 Ollama、Semaphore 也不释放。

        v9.5.3 改为：创建 cancel_event，通过 llm_engine.bind_cancel_event()
        绑定到 worker 线程。超时后 set() cancel_event → infer() 检测到
        取消信号 → 中断 HTTP 调用 → worker 正常退出 → Semaphore 释放。
        """
        cancel_event = threading.Event()
        result_container = {"result": None, "error": None, "done": False}
        lock = threading.Lock()

        def worker():
            # 绑定取消事件到当前线程，infer() 会自动检测
            try:
                from backend.core.llm_kernel.llm_utils import bind_cancel_event, unbind_cancel_event

                bind_cancel_event(cancel_event)
            except Exception:
                logger.warning(
                    "TaskQueue._execute_with_timeout: 未预期的异常被静默捕获（P-17 收口）",
                    exc_info=True,
                )
                pass
            try:
                r = self._dispatch_task_execution(task_meta)
                with lock:
                    result_container["result"] = r
                    result_container["done"] = True
            except Exception as e:
                logger.warning(
                    "TaskQueue._execute_with_timeout: 未预期的异常被静默捕获（P-17 收口）",
                    exc_info=True,
                )
                with lock:
                    result_container["error"] = e
                    result_container["done"] = True
            finally:
                try:
                    from backend.core.llm_kernel.llm_utils import unbind_cancel_event

                    unbind_cancel_event()
                except Exception:
                    logger.warning(
                        "TaskQueue._execute_with_timeout: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    pass

        t = threading.Thread(
            target=worker, name=f"tw_{task_meta.get('task_id', '')[:12]}", daemon=True
        )
        t.start()
        t.join(timeout=timeout_seconds)

        with lock:
            if result_container["done"]:
                if result_container["error"]:
                    raise result_container["error"]
                return result_container["result"]

        # 超时：设置取消信号，让 worker 线程的 infer() 感知到并中断
        cancel_event.set()
        logger.error(
            f"⏰ 任务执行超时 ({timeout_seconds}s)，已发送取消信号: "
            f"{task_meta.get('task_id', '')} | 类型: {task_meta.get('task_type', '')}"
        )
        raise TimeoutError(f"Task execution exceeded {timeout_seconds}s")

    def _dispatch_task_execution(self, task_meta: dict) -> Any:
        """根据任务类型分发到已注册的 handler

        v9.5.1: payload 中自动注入 _task_id 和 _progress_callback，
        让 handler 可以更新任务进度和心跳。
        """
        task_type = task_meta["task_type"]
        payload = task_meta["payload"].copy()
        task_id = task_meta["task_id"]

        # 注入任务上下文
        payload["_task_id"] = task_id
        payload["_progress_callback"] = lambda progress, partial="", note="": (
            self.update_task_progress(task_id, progress, partial, note)
        )

        handler = self._handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"未注册的任务类型: {task_type} | 已注册: {list(self._handlers.keys())}"
            )

        # 大型汇总报告串行化：同一时间只允许一个报告任务占用 Ollama
        if task_type in self.REPORT_TYPES:
            logger.info(f"📊 报告任务排队: {task_type} — 等待报告槽位...")
            acquired = self._report_semaphore.acquire(timeout=1800)
            if not acquired:
                raise RuntimeError(f"报告槽位等待超时: {task_type} (30min)")
            logger.info(f"📊 报告槽位获得: {task_type} — 开始执行")
            try:
                result = handler(payload)
            finally:
                self._report_semaphore.release()
                logger.info(f"📊 报告槽位释放: {task_type}")
            return result

        return handler(payload)

    # ══════════════════════════════════════════════════════════
    # 失败处理 & 重试
    # ══════════════════════════════════════════════════════════

    def _handle_task_failure(
        self, task_id: str, error_msg: str, db, release_event: threading.Event = None
    ):
        task_meta = self._task_map.get(task_id)
        if not task_meta:
            return

        retry_count = task_meta.get("retry_count", 0)
        max_retries = task_meta.get("max_retries", 3)

        if retry_count < max_retries:
            new_retry_count = retry_count + 1
            delay = min(2**new_retry_count, 30)

            task_meta["retry_count"] = new_retry_count
            task_meta["error_message"] = error_msg
            task_meta["status"] = TaskStatus.PENDING.value

            next_retry = (
                datetime.now().isoformat()
                if delay == 0
                else (
                    datetime.now().replace(microsecond=0).isoformat()
                    if delay <= 1
                    else (datetime.now() + timedelta(seconds=delay)).isoformat()
                )
            )

            if db is not None:
                try:
                    db.query_local(
                        """
                        UPDATE task_queue SET
                            status = 'pending', retry_count = ?, error_message = ?,
                            next_retry_at = ?
                        WHERE task_id = ?
                    """,
                        (new_retry_count, error_msg, next_retry, task_id),
                    )
                except Exception:
                    logger.warning(
                        "TaskQueue._handle_task_failure: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    pass

            def requeue():
                time.sleep(delay)
                if release_event is not None:
                    release_event.wait()
                with self._queue_lock:
                    self._task_queue.append(QueuedTask(task_id, task_meta))
                logger.info(f"🔄 重试任务: {task_id} | 第{new_retry_count}次 | 延迟{delay}s")

            threading.Thread(target=requeue, daemon=True).start()

            with self._stats_lock:
                self._stats["total_failed"] += 1
        else:
            self._update_task_status(task_id, TaskStatus.FAILED.value, error=error_msg)
            if db is not None:
                try:
                    db.query_local(
                        """
                        UPDATE task_queue SET status = 'failed', error_message = ?, completed_at = ?
                        WHERE task_id = ?
                    """,
                        (error_msg, datetime.now().isoformat(), task_id),
                    )
                except Exception:
                    logger.warning(
                        "TaskQueue._handle_task_failure: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    pass

            with self._stats_lock:
                self._stats["total_failed"] += 1

            # v9.5.4: step_analysis 失败 → 级联取消对应的 conversation_finalize
            if task_meta and task_meta.get("task_type") == "step_analysis":
                conv_id = task_meta.get("payload", {}).get("conversation_id", "")
                if conv_id:
                    result = self.cancel_conversation_tasks(conv_id)
                    if result["cancelled"] > 0:
                        logger.info(
                            f"🔗 级联取消: step_analysis={task_id} 失败 "
                            f"→ conversation={conv_id} 的 {result['cancelled']} 个任务"
                        )

    # ══════════════════════════════════════════════════════════
    # 状态管理
    # ══════════════════════════════════════════════════════════

    def _update_task_status(self, task_id: str, status: str, result: Any = None, error: str = None):
        if task_id in self._task_map:
            self._task_map[task_id]["status"] = status
            if result is not None:
                self._task_map[task_id]["result"] = result
            if error is not None:
                self._task_map[task_id]["error_message"] = error
            if status in [
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.TIMEOUT.value,
            ]:
                self._task_map[task_id]["completed_at"] = datetime.now().isoformat()

    def _update_memory_usage(self, memory_mb: int, delta: bool):
        with self._memory_lock:
            if delta:
                self._current_memory_mb += memory_mb
            else:
                self._current_memory_mb = max(0, self._current_memory_mb - memory_mb)

    def _invoke_callback(self, callback_name: str, task_id: str, result: Any):
        try:
            from backend.core.task_queue_kernel.callback_registry import get_callback_registry

            registry = get_callback_registry()

            task_meta = self._task_map.get(task_id, {})
            payload = task_meta.get("payload", {})
            conversation_id = payload.get("conversation_id", "")

            if conversation_id:
                registry.trigger_complete(
                    conversation_id=conversation_id,
                    result=result or {},
                    task_id=task_id,
                )
                logger.info(
                    f"📞 回调触发: {callback_name} | 任务: {task_id} | 会话: {conversation_id}"
                )
        except Exception as e:
            logger.warning(f"⚠️ 回调触发失败: {e}")

    # ══════════════════════════════════════════════════════════
    # 查询 & 控制
    # ══════════════════════════════════════════════════════════

    def get_task_status(self, task_id: str) -> dict | None:
        if task_id not in self._task_map:
            from backend.core.database.base_conn import get_db

            db = get_db()
            rows = db.query_local("SELECT * FROM task_queue WHERE task_id = ?", (task_id,))
            if rows:
                return dict(rows[0])
            return None
        return self._task_map[task_id].copy()

    def cancel_task(self, task_id: str) -> bool:
        task_meta = self._task_map.get(task_id)
        if not task_meta:
            return False
        if task_meta["status"] not in [TaskStatus.PENDING.value, TaskStatus.QUEUED.value]:
            return False

        self._update_task_status(task_id, TaskStatus.CANCELLED.value)
        from backend.core.database.base_conn import get_db

        db = get_db()
        db.query_local("UPDATE task_queue SET status = 'cancelled' WHERE task_id = ?", (task_id,))

        with self._stats_lock:
            self._stats["total_cancelled"] += 1
        return True

    def retry_task(self, task_id: str) -> dict:
        """手动重试失败任务（重置为 pending 立即重试）"""
        task_meta = self._task_map.get(task_id)
        if not task_meta:
            return {"success": False, "error": "任务不存在"}

        status = task_meta.get("status", "")
        if status not in [TaskStatus.FAILED.value, "dead"]:
            return {"success": False, "error": f"任务状态为 {status}，只能重试 failed/dead 任务"}

        # 重置为重试计数，立即重试
        task_meta["retry_count"] = task_meta.get("retry_count", 0)  # 保留计数，不重置
        task_meta["status"] = TaskStatus.PENDING.value
        task_meta["error_message"] = None
        task_meta["next_retry_at"] = None

        from backend.core.database.base_conn import get_db

        db = get_db()
        if db:
            try:
                db.query_local(
                    "UPDATE task_queue SET status='pending', error_message=NULL, next_retry_at=NULL WHERE task_id=?",
                    (task_id,),
                )
            except Exception:
                logger.warning(
                    "TaskQueue.retry_task: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

        with self._queue_lock:
            self._task_queue.append(QueuedTask(task_id, task_meta))

        logger.info(f"🔁 手动重试任务: {task_id}")
        return {"success": True, "task_id": task_id}

    def cancel_conversation_tasks(self, conversation_id: str) -> dict:
        """级联取消指定 conversation 的所有 pending/queued 任务（含 conversation_finalize）。

        核心场景：一个对话的 step_analysis 全部失败后，
        对应的 conversation_finalize（PHASE_SEQUENTIAL）还在排队，
        但因为 step 永远不会完成，finalize 会一直等到 30 分钟超时才降级。
        此方法主动清理这类"死等"任务。

        Returns:
            {"cancelled": int, "task_ids": [str], "conversation_id": str}
        """
        cancelled = []
        for tid, meta in list(self._task_map.items()):
            payload = meta.get("payload", {})
            conv_id = payload.get("conversation_id", "")
            if conv_id == conversation_id:
                status = meta.get("status", "")
                if status in [
                    TaskStatus.PENDING.value,
                    TaskStatus.QUEUED.value,
                ] and self.cancel_task(tid):
                    cancelled.append(tid)

        logger.info(f"🔗 级联取消 conversation={conversation_id}: {len(cancelled)} 个任务")
        return {
            "cancelled": len(cancelled),
            "task_ids": cancelled,
            "conversation_id": conversation_id,
        }

    def cleanup_pending_tasks(
        self,
        before_hours: float = 24.0,
        task_types: list | None = None,
        conversation_id: str | None = None,
        dry_run: bool = False,
    ) -> dict:
        """批量清理指定时间范围内的 pending/queued 任务。

        Args:
            before_hours: 清理多久之前的 pending 任务（默认 24 小时）
            task_types: 限定任务类型，如 ["step_analysis", "conversation_finalize"]。None = 所有类型
            conversation_id: 限定 conversation。None = 所有
            dry_run: 只统计不执行

        Returns:
            {"cancelled": int, "cancelled_ids": [str], "by_type": {type: count}, "dry_run": bool}
        """
        cutoff = datetime.now() - timedelta(hours=before_hours)
        by_type = {}
        cancelled = []

        for tid, meta in list(self._task_map.items()):
            status = meta.get("status", "")
            if status not in [TaskStatus.PENDING.value, TaskStatus.QUEUED.value]:
                continue

            # 时间过滤
            created_at_str = meta.get("queued_at", "")
            if created_at_str:
                try:
                    created_at = datetime.fromisoformat(created_at_str)
                    if created_at > cutoff:
                        continue
                except (ValueError, TypeError):
                    pass  # 无法解析时间的不跳过

            # 类型过滤
            task_type = meta.get("task_type", "")
            if task_types and task_type not in task_types:
                continue

            # conversation 过滤
            payload = meta.get("payload", {})
            conv_id = payload.get("conversation_id", "")
            if conversation_id and conv_id != conversation_id:
                continue

            if dry_run or self.cancel_task(tid):
                by_type[task_type] = by_type.get(task_type, 0) + 1
                cancelled.append(tid)

        action = "预览" if dry_run else "取消"
        logger.info(
            f"🧹 {action} pending 任务: {len(cancelled)} 个 | before_hours={before_hours}h | types={task_types}"
        )
        return {
            "cancelled": len(cancelled),
            "cancelled_ids": cancelled,
            "by_type": by_type,
            "dry_run": dry_run,
        }

    # ══════════════════════════════════════════════════════════
    # v9.5.1: 心跳保活 & 进度报告
    # ══════════════════════════════════════════════════════════

    def update_heartbeat(self, task_id: str):
        """更新任务心跳时间戳，防止被僵尸检测误杀。

        长任务（如重型 LLM 分析）应每 30-60 秒调用一次。
        心跳同时写入内存和数据库。
        """
        now = datetime.now().isoformat()
        if task_id in self._task_map:
            self._task_map[task_id]["last_heartbeat"] = now

        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            db.query_local(
                "UPDATE task_queue SET last_heartbeat = ? WHERE task_id = ?", (now, task_id)
            )
        except Exception:
            logger.warning(
                "TaskQueue.update_heartbeat: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            pass

    def update_task_progress(
        self, task_id: str, progress: float, partial_result: str = "", status_note: str = ""
    ):
        """更新任务进度（0.0 ~ 1.0）和部分结果预览。

        Worker 在处理长任务时调用，让外部轮询者看到实时进度。

        Args:
            task_id: 任务ID
            progress: 进度 0.0 ~ 1.0
            partial_result: 部分生成结果的前若干字符（预览用）
            status_note: 状态备注（如 "正在生成用户画像..."）
        """
        progress = max(0.0, min(1.0, float(progress)))
        now = datetime.now().isoformat()

        if task_id in self._task_map:
            self._task_map[task_id]["progress"] = progress
            self._task_map[task_id]["partial_result"] = (
                partial_result[:2000] if partial_result else ""
            )
            self._task_map[task_id]["status_note"] = status_note
            self._task_map[task_id]["last_heartbeat"] = now

        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            db.query_local(
                "UPDATE task_queue SET progress = ?, partial_result = ?, status_note = ?, last_heartbeat = ? WHERE task_id = ?",
                (
                    progress,
                    partial_result[:2000] if partial_result else "",
                    status_note,
                    now,
                    task_id,
                ),
            )
        except Exception:
            logger.warning(
                "TaskQueue.update_task_progress: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            pass

    def get_running_tasks_with_progress(self) -> list:
        """获取所有运行中任务的进度信息（用于 Dashboard 展示）"""
        running = []
        for tid, meta in self._task_map.items():
            if meta.get("status") == TaskStatus.RUNNING.value:
                running.append(
                    {
                        "task_id": tid,
                        "task_type": meta.get("task_type", ""),
                        "progress": meta.get("progress", 0.0),
                        "partial_result": meta.get("partial_result", ""),
                        "status_note": meta.get("status_note", ""),
                        "last_heartbeat": meta.get("last_heartbeat", ""),
                        "started_at": meta.get("started_at", ""),
                        "conversation_id": meta.get("payload", {}).get("conversation_id", ""),
                    }
                )
        return running

    def list_tasks(self, limit: int = 20) -> list:
        """列出所有任务（按创建时间倒序，供 Dashboard 使用）

        优先从内存 _task_map 获取，如果内存为空则从数据库查询。
        """
        tasks = []
        # 先从内存 _task_map 收集
        for tid, meta in self._task_map.items():
            tasks.append(
                {
                    "task_id": tid,
                    "task_type": meta.get("task_type", ""),
                    "conversation_id": meta.get("payload", {}).get("conversation_id", ""),
                    "status": meta.get("status", ""),
                    "created_at": meta.get("created_at", ""),
                    "progress": meta.get("progress", 0.0),
                    "status_note": meta.get("status_note", ""),
                    "error": meta.get("error_message", "") or meta.get("error", ""),
                    "last_heartbeat": meta.get("last_heartbeat", ""),
                    "retry_count": meta.get("retry_count", 0),
                    "max_retries": meta.get("max_retries", 3),
                    "next_retry_at": meta.get("next_retry_at", ""),
                }
            )
        # 如果内存为空，从数据库补充
        if not tasks:
            try:
                from backend.core.database.base_conn import get_db

                db = get_db()
                rows = db.query_local(
                    "SELECT * FROM task_queue WHERE is_deleted=0 ORDER BY queued_at DESC LIMIT ?",
                    (limit,),
                )
                for r in rows or []:
                    payload = r.get("payload", "{}")
                    if isinstance(payload, str):
                        import json as _json

                        try:
                            payload = _json.loads(payload)
                        except Exception:
                            logger.warning(
                                "TaskQueue.list_tasks: 未预期的异常被静默捕获（P-17 收口）",
                                exc_info=True,
                            )
                            payload = {}
                    tasks.append(
                        {
                            "task_id": r.get("task_id", ""),
                            "task_type": r.get("task_type", ""),
                            "conversation_id": payload.get("conversation_id", ""),
                            "status": r.get("status", ""),
                            "created_at": r.get("queued_at", ""),
                            "progress": r.get("progress", 0.0),
                            "status_note": r.get("status_note", ""),
                            "error": r.get("error_message", "") or r.get("error", ""),
                            "last_heartbeat": r.get("last_heartbeat", ""),
                            "retry_count": r.get("retry_count", 0),
                            "max_retries": r.get("max_retries", 3),
                            "next_retry_at": r.get("next_retry_at", ""),
                        }
                    )
            except Exception as e:
                logger.warning(f"从数据库加载任务列表失败: {e}")
        # 按创建时间倒序
        tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return tasks[:limit]

    def get_queue_stats(self) -> dict:
        pending_count = sum(
            1
            for t in self._task_map.values()
            if t["status"] in [TaskStatus.PENDING.value, TaskStatus.QUEUED.value]
        )
        running_count = sum(
            1 for t in self._task_map.values() if t["status"] == TaskStatus.RUNNING.value
        )

        with self._stats_lock:
            stats_copy = self._stats.copy()

        return {
            **stats_copy,
            "pending_tasks": pending_count,
            "running_tasks": running_count,
            "memory_usage_mb": round(self._current_memory_mb, 2),
            "memory_limit_mb": self._max_memory_mb,
            "utilization_percent": round(
                (self._current_memory_mb / max(1, self._max_memory_mb)) * 100, 1
            ),
            "active_workers": self._executor._max_workers,
            "available_slots": self._semaphore._value,
            "registered_handlers": list(self._handlers.keys()),
        }

    def get_diagnostics(self) -> dict:
        with self._queue_lock:
            pending_count = len(self._task_queue)
            pending_tasks = [
                {
                    "id": t.task_id,
                    "type": t.task_data.get("task_type"),
                    "conv": t.task_data.get("payload", {}).get("conversation_id", "global"),
                }
                for t in list(self._task_queue)[:5]
            ]

        with self._memory_lock:
            memory_info = {
                "current_mb": self._current_memory_mb,
                "max_mb": self._max_memory_mb,
                "usage_percent": (self._current_memory_mb / self._max_memory_mb * 100)
                if self._max_memory_mb > 0
                else 0,
            }

        status_count = {}
        for task_meta in self._task_map.values():
            status = task_meta.get("status", "unknown")
            status_count[status] = status_count.get(status, 0) + 1

        running_tasks = [
            {
                "id": tid,
                "type": meta.get("task_type"),
                "started": meta.get("started_at"),
                "conv": meta.get("payload", {}).get("conversation_id", "global"),
            }
            for tid, meta in self._task_map.items()
            if meta.get("status") == TaskStatus.RUNNING.value
        ]

        conv_phase_status = {}
        with self._conv_phase_locks_guard:
            for conv_id, lock in self._conv_phase_locks.items():
                conv_phase_status[conv_id] = {"phase_lock": lock.locked()}

        with self._conv_step_counter_guard:
            step_counter_snapshot = dict(self._conv_step_counter)

        return {
            "timestamp": datetime.now().isoformat(),
            "scheduler_mode": "FIFO + phase_concurrent + handler_dispatch (v8.1)",
            "registered_handlers": list(self._handlers.keys()),
            "phase_parallel_types": list(self.PHASE_PARALLEL),
            "phase_sequential_types": list(self.PHASE_SEQUENTIAL),
            "semaphore_value": self._semaphore._value
            if hasattr(self._semaphore, "_value")
            else "unknown",
            "active_futures": len(self._futures),
            "pending_in_queue": pending_count,
            "pending_preview": pending_tasks,
            "total_tracked": len(self._task_map),
            "active_phase_locks": len(
                [lock for lock in self._conv_phase_locks.values() if lock.locked()]
            ),
            "total_phase_locks": len(self._conv_phase_locks),
            "conv_step_counters": step_counter_snapshot,
            "conv_phase_locks": conv_phase_status,
            "memory": memory_info,
            "status_breakdown": status_count,
            "running_tasks": running_tasks,
            "stats": self._stats.copy(),
        }

    # ══════════════════════════════════════════════════════════
    # 启动恢复 & 重试调度
    # ══════════════════════════════════════════════════════════

    def recover_pending_tasks(self) -> int:
        """v9.5.4: 从 DB 加载所有 pending 任务到内存队列（公共方法，供 ensure_ready 调用）。

        解决 v9.5.3 的启动时序 bug：TaskQueue.__init__ 在 DB 初始化之前执行，
        _recover_interrupted_tasks 因为 db.is_local_initialized() 返回 False 而跳过加载。
        现在由 ensure_ready 在 DB 初始化完成后显式调用此方法。

        Returns:
            成功加载的任务数量。
        """
        return self._recover_interrupted_tasks()

    def run_startup_recovery(self) -> dict:
        """v9.7.1: 延迟启动恢复 — 在 handler 全部注册后由 ensure_ready 调用。

        替代原来在 __init__ 中的 recover_on_startup() 调用。
        此时 handlers 已注册完毕，恢复流水线提交的任务可以正常执行。

        Returns:
            {"recovered": int, "pipeline_stats": dict}
        """
        result = {"recovered": 0, "pipeline_stats": {}}

        # 先加载 DB 中的 pending 任务到内存队列
        recovered = self._recover_interrupted_tasks()
        result["recovered"] = recovered
        if recovered > 0:
            logger.info(f"[启动恢复] 从 DB 加载 {recovered} 个 pending 任务到内存队列")

        # 再运行恢复流水线（统一去重、排序、兜底）
        if not self._recovery_pending:
            return result
        self._recovery_pending = False

        try:
            from backend.core.task_recovery import recover_on_startup

            stats = recover_on_startup()
            result["pipeline_stats"] = {
                "scanned": stats.scanned_total,
                "after_dedup": stats.after_dedup,
                "enqueued": stats.enqueued,
                "duplicates": stats.duplicates_discarded,
                "by_type": stats.by_type,
            }
            if stats.scanned_total > 0:
                logger.info(
                    f"[启动恢复] 扫描 {stats.scanned_total} → "
                    f"去重后 {stats.after_dedup} → 入队 {stats.enqueued}"
                )
        except Exception as e:
            logger.warning(f"⚠️ 启动恢复流水线执行失败（非致命）: {e}")

        return result

    def _recover_interrupted_tasks(self):
        """v9.5.2: 启动时恢复中断任务 + 从 DB 加载 pending 任务到内存队列

        修复了服务重启后 pending 任务丢失的问题：
        - 旧逻辑只把 running/processing 重置为 pending，不加载到内存队列
        - 新逻辑额外从 DB 查询所有 pending 任务并加入 _task_queue
        - 同时清理幽灵 running 任务（completed_at 已设置但 status 仍 running）
        """
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            if not db.is_local_initialized():
                return 0

            # 1. 清理幽灵任务：completed_at 已设置但 status 仍 running
            ghost_rows = db.query_local(
                "SELECT task_id FROM task_queue "
                "WHERE status = 'running' AND completed_at IS NOT NULL AND is_deleted = 0"
            )
            if ghost_rows:
                ghost_ids = [r["task_id"] for r in ghost_rows]
                db.query_local(
                    "UPDATE task_queue SET status = 'completed' WHERE task_id IN ({})".format(
                        ",".join(["?"] * len(ghost_ids))
                    ),
                    tuple(ghost_ids),
                )
                logger.info(
                    f"🧹 清理幽灵任务: {len(ghost_rows)} 个已完成但状态未更新的任务 → completed"
                )

            # 2. 重置中断的 running/processing 任务
            rows = db.query_local(
                "SELECT task_id, status FROM task_queue "
                "WHERE status IN ('processing', 'running') AND is_deleted = 0"
            )
            if rows:
                count = len(rows)
                db.query_local(
                    "UPDATE task_queue SET status = 'pending', started_at = NULL, "
                    "worker_id = NULL, error_message = 'Recovered after restart' "
                    "WHERE status IN ('processing', 'running') AND is_deleted = 0"
                )
                logger.info(f"🔄 启动恢复: {count} 个中断任务已重置为 pending")

            # 3. v9.5.2: 从 DB 加载所有 pending 任务到内存队列
            pending_rows = db.query_local(
                "SELECT task_id, task_type, payload, priority, max_retries, "
                "retry_count, error_message, timeout_seconds, estimated_memory_mb, "
                "next_retry_at, sort_order "
                "FROM task_queue "
                "WHERE status = 'pending' AND is_deleted = 0 "
                "ORDER BY sort_order"
            )
            loaded_count = 0
            for row in pending_rows or []:
                task_id = row["task_id"]
                # 避免重复加载（如果任务已在内存中）
                if task_id in self._task_map:
                    continue
                payload = row["payload"]
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        logger.warning(
                            "TaskQueue._recover_interrupted_tasks: 未预期的异常被静默捕获（P-17 收口）",
                            exc_info=True,
                        )
                        payload = {}
                task_meta = {
                    "task_id": task_id,
                    "task_type": row["task_type"],
                    "payload": payload or {},
                    "status": TaskStatus.PENDING.value,
                    "priority": row.get("priority", 5),
                    "max_retries": row.get("max_retries", 3),
                    "retry_count": row.get("retry_count", 0),
                    "error_message": row.get("error_message", ""),
                    "timeout_seconds": row.get("timeout_seconds", 10800),
                    "estimated_memory_mb": row.get("estimated_memory_mb", 100),
                    "next_retry_at": row.get("next_retry_at", ""),
                    "sort_order": row.get("sort_order", 0),
                }
                self._task_map[task_id] = task_meta
                with self._queue_lock:
                    self._task_queue.append(QueuedTask(task_id, task_meta))
                loaded_count += 1

            if loaded_count > 0:
                logger.info(f"📥 启动加载: {loaded_count} 个 pending 任务已恢复到内存队列")

            return loaded_count

        except Exception as e:
            logger.warning(f"⚠️ 启动恢复失败（非致命）: {e}", exc_info=True)
            return 0

    def _retry_scheduler_loop(self):
        """v9.6.0: 定时重试调度 — 统一走恢复流水线（门B：定时扫描）。

        每 300 秒（5 分钟）触发一次统一恢复流水线，处理所有未完成/失败任务。
        替代旧的手动 SQL 扫描方式。
        """
        while not self._shutdown_flag:
            try:
                time.sleep(300)  # 5 分钟间隔
                from backend.core.task_recovery import recover_on_periodic

                stats = recover_on_periodic()
                if stats.scanned_total > 0:
                    logger.info(
                        f"[定时恢复] 扫描 {stats.scanned_total} → "
                        f"去重 {stats.duplicates_discarded} → 入队 {stats.enqueued}"
                    )
            except Exception as e:
                logger.warning(f"⚠️ 重试调度异常（非致命）: {e}")

    # ══════════════════════════════════════════════════════════
    # 僵尸任务 & 孤儿步骤清理
    # ══════════════════════════════════════════════════════════

    def _auto_cleanup_zombies(self):
        """v9.5.1: 基于 last_heartbeat 判断僵尸（优先），fallback 到 started_at"""
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            if not db.is_local_initialized():
                return
            rows = db.query_local(
                "SELECT task_id, started_at, last_heartbeat FROM task_queue WHERE status='running'"
            )
            if not rows:
                return

            now = datetime.now()
            max_age = 10800  # 3 小时无心跳 = 僵尸（对齐任务超时）
            cleaned = 0
            for row in rows:
                # 优先使用心跳时间判断
                heartbeat = row.get("last_heartbeat")
                if heartbeat:
                    try:
                        hb_time = datetime.fromisoformat(heartbeat)
                        age_s = (now - hb_time).total_seconds()
                        if age_s > max_age:
                            self._mark_zombie(db, row["task_id"], age_s, now)
                            cleaned += 1
                        continue
                    except Exception:
                        logger.warning(
                            "TaskQueue._auto_cleanup_zombies: 未预期的异常被静默捕获（P-17 收口）",
                            exc_info=True,
                        )
                        pass

                # fallback: 用 started_at 判断
                started_at = row.get("started_at")
                if not started_at:
                    continue
                try:
                    started = datetime.fromisoformat(started_at)
                    age_s = (now - started).total_seconds()
                    if age_s > max_age:
                        self._mark_zombie(db, row["task_id"], age_s, now)
                        cleaned += 1
                except Exception:
                    logger.warning(
                        "TaskQueue._auto_cleanup_zombies: 未预期的异常被静默捕获（P-17 收口）",
                        exc_info=True,
                    )
                    pass

            if cleaned > 0:
                self.reset_semaphore_leak()
                logger.info(f"✅ 自动清理完成: {cleaned} 个僵尸任务")
        except Exception as e:
            logger.warning(f"⚠️ 僵尸任务检查失败（非致命）: {e}")

    def _mark_zombie(self, db, task_id: str, age_s: float, now: datetime):
        """标记任务为僵尸/超时"""
        db.query_local(
            "UPDATE task_queue SET status='timeout', error_message=?, completed_at=? WHERE task_id=?",
            (
                f"Auto zombie cleanup after {age_s / 3600:.1f}h (no heartbeat)",
                now.isoformat(),
                task_id,
            ),
        )
        if task_id in self._task_map:
            self._update_task_status(
                task_id, TaskStatus.TIMEOUT.value, error=f"Zombie after {age_s / 3600:.1f}h"
            )
        if task_id in self._futures:
            try:
                self._futures[task_id].cancel()
            except Exception:
                logger.warning(
                    "TaskQueue._mark_zombie: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass
            del self._futures[task_id]

    def _auto_cleanup_orphan_steps(self):
        try:
            from backend.core.database.base_conn import get_db

            db = get_db()
            if not db.is_local_initialized():
                return
            now = datetime.now()

            db.query_local(
                """
                UPDATE conversation_steps SET status = 'orphaned', error_message = ?
                WHERE status = 'pending'
                  AND created_at < ?
                  AND created_at IS NOT NULL
            """,
                (
                    f"Auto orphaned after 24h at {now.isoformat()}",
                    (now - timedelta(hours=24)).isoformat(),
                ),
            )

            db.query_local(
                """
                UPDATE conversation_steps SET status = 'pending', error_message = ?
                WHERE status = 'in_progress'
                  AND started_at < ?
                  AND started_at IS NOT NULL
            """,
                (
                    f"Auto reset from in_progress after 10min at {now.isoformat()}",
                    (now - timedelta(minutes=10)).isoformat(),
                ),
            )
        except Exception as e:
            logger.warning(f"⚠️ 孤儿步骤检查失败（非致命）: {e}")

    def force_cleanup_zombie_tasks(self, max_age_seconds: int = 300) -> int:
        cleaned_count = 0
        now = datetime.now()

        for task_id, task_meta in list(self._task_map.items()):
            if task_meta.get("status") != TaskStatus.RUNNING.value:
                continue

            started_at = task_meta.get("started_at")
            if not started_at:
                continue

            try:
                start_time = datetime.fromisoformat(started_at)
                age_seconds = (now - start_time).total_seconds()

                if age_seconds > max_age_seconds:
                    self._update_task_status(
                        task_id,
                        TaskStatus.TIMEOUT.value,
                        error=f"Force cleanup after {age_seconds:.1f}s",
                    )

                    try:
                        from backend.core.database.base_conn import get_db

                        db = get_db()
                        db.query_local(
                            """
                            UPDATE task_queue SET status = 'timeout', error_message = ?, completed_at = ?
                            WHERE task_id = ?
                        """,
                            (f"Zombie cleanup after {age_seconds:.1f}s", now.isoformat(), task_id),
                        )
                    except Exception:
                        logger.warning(
                            "TaskQueue.force_cleanup_zombie_tasks: 未预期的异常被静默捕获（P-17 收口）",
                            exc_info=True,
                        )
                        pass

                    if task_id in self._futures:
                        self._futures[task_id].cancel()
                        del self._futures[task_id]

                    cleaned_count += 1
            except Exception as e:
                logger.error(f"❌ 清理僵尸任务异常: {task_id} | {e}")

        if cleaned_count > 0:
            logger.info(f"✅ 僵尸任务清理完成，共清理 {cleaned_count} 个任务")
        return cleaned_count

    def reset_semaphore_leak(self) -> int:
        actual_running = sum(
            1 for meta in self._task_map.values() if meta.get("status") == TaskStatus.RUNNING.value
        )

        max(0, 2 - actual_running)
        current_value = 0
        if hasattr(self._semaphore, "_value"):
            current_value = self._semaphore._value

        leak_count = actual_running - (2 - current_value) if current_value < 2 else 0

        if leak_count > 0:
            for _ in range(leak_count):
                try:
                    self._semaphore.release()
                except ValueError:
                    break
            logger.info(f"✅ 已释放 {leak_count} 个泄漏的信号量")
            return leak_count
        return 0

    def shutdown(self, wait: bool = True):
        logger.info("🛑 正在关闭任务队列...")
        self._shutdown_flag = True

        if wait:
            for future in list(self._futures.values()):
                future.result(timeout=10.0)

        self._executor.shutdown(wait=wait)
        logger.info("✅ 任务队列已关闭")


_task_queue_instance: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    global _task_queue_instance
    if _task_queue_instance is None:
        _task_queue_instance = TaskQueue()
    return _task_queue_instance
