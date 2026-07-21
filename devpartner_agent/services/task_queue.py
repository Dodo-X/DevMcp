"""
异步任务队列 (v9.5.1)
=====================
管理后台任务的异步执行，支持 FIFO 调度、阶段级并发控制、心跳保活和进度报告。

核心职责（仅限调度）：
  ✅ FIFO 先进先出调度
  ✅ 阶段级并发控制（v8.1 新增）
     - step_analysis: 同会话可并行（各自写不同的 step 行）
     - conversation_finalize: 必须等该会话所有 step_analysis 完成
     - 其他任务: 同会话串行（保守策略）
  ✅ 跨会话并行执行
  ✅ 并发控制（Semaphore = OLLAMA_NUM_PARALLEL, Workers = N*2）
  ✅ 内存占用监控
  ✅ 任务超时处理
  ✅ 失败重试机制
  ✅ 僵尸任务清理
  ✅ 心跳保活（v9.5.1）：长任务定期报告存活状态
  ✅ 进度报告（v9.5.1）：Worker 可更新任务进度和部分结果

v9.5.1 变更（相比 v9.5.0）：
  - 新增心跳机制：Worker 定期更新 last_heartbeat，防止被误杀
  - 新增进度更新：update_task_progress() 让长任务报告进度
  - 僵尸检测改用 last_heartbeat 替代 started_at 判断
  - 任务元数据新增 last_heartbeat / progress / partial_result 字段
"""
import json
import uuid
import logging
import threading
import time
import collections
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


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
    异步任务队列管理器 (v8.1 — 阶段级并发控制)

    资源策略：
      - 全局并发数: 与 OLLAMA_NUM_PARALLEL 对齐
      - 最大内存阈值: 1.5GB
      - 单任务超时: 3600秒（v9.5: LLM 推理不设 HTTP 超时，任务级给 1h 兜底）
      - 最大重试: 3次

    并发模型（v8.1 阶段级）：
      - step_analysis: 同会话可并行（各自写不同的 step 行）
      - conversation_finalize: 必须等该会话所有 step_analysis 完成
      - 其他任务类型: 同会话串行（保守策略）
      - 不同会话: 始终并行
    """

    PHASE_PARALLEL = {
        "step_analysis",
        "vault_export_batch", "vault_export_all", "vault_export_profile",
        "vault_export_project", "vault_export_weekly", "vault_export_monthly",
        "vault_export_annual", "vault_export_daily",
        "cleanup_force", "cleanup_vacuum", "cleanup_full",
    }
    PHASE_SEQUENTIAL = {"conversation_finalize", "conversation_analysis",
                        "profile_update", "knowledge_extraction", "system_optimization",
                        "daily_summary", "daily_export"}

    def __init__(self):
        self._task_queue: collections.deque = collections.deque()
        self._queue_lock = threading.Lock()
        self._task_map: Dict[str, dict] = {}
        self._futures: Dict[str, Future] = {}

        self._conv_phase_locks: Dict[str, threading.Lock] = {}
        self._conv_phase_locks_guard = threading.Lock()

        self._conv_step_counter: Dict[str, int] = {}
        self._conv_step_counter_guard = threading.Lock()

        self._conv_finalize_wait: Dict[str, threading.Event] = {}
        self._conv_finalize_wait_guard = threading.Lock()

        try:
            from devpartner_agent.core.config import get_config
            _cfg = get_config()
            _num_parallel = _cfg.llm.ollama_num_parallel
        except Exception:
            _num_parallel = 2

        self._max_concurrent: int = _num_parallel
        self._semaphore: threading.Semaphore = threading.Semaphore(_num_parallel)
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=_num_parallel * 2,
            thread_name_prefix="task_worker_"
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

        self._handlers: Dict[str, Callable[[dict], Any]] = {}

        self._shutdown_flag: bool = False
        self._worker_thread: threading.Thread = threading.Thread(
            target=self._worker_loop,
            name="task_scheduler_main",
            daemon=True
        )
        self._worker_thread.start()

        self._recover_interrupted_tasks()

        self._retry_thread: threading.Thread = threading.Thread(
            target=self._retry_scheduler_loop,
            name="task_retry_scheduler",
            daemon=True
        )
        self._retry_thread.start()

        logger.info(f"🔄 异步任务队列已启动 (v8.1 阶段级并发 | Semaphore={_num_parallel} | Workers={_num_parallel * 2})")

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

    # ══════════════════════════════════════════════════════════
    # 任务提交
    # ══════════════════════════════════════════════════════════

    def submit_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = TaskPriority.MEDIUM,
        timeout_seconds: int = 3600,
        max_retries: int = 3,
        estimated_memory_mb: int = 100,
        callback: Optional[Callable] = None
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
            from devpartner_agent.core.database import get_db
            db = get_db()
            existing = db.query_local(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM task_queue"
            )
            sort_order = existing[0]["next_order"] if existing else 1
            db.query_local("""
                INSERT INTO task_queue (
                    task_id, task_type, payload, status, priority,
                    max_retries, estimated_memory_mb, queued_at, timeout_seconds, sort_order
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """, (
                task_id, task_type, json.dumps(payload, ensure_ascii=False),
                priority, max_retries, estimated_memory_mb, timestamp, timeout_seconds, sort_order
            ))
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
                    with self._queue_lock:
                        self._task_queue.appendleft(task)
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
                    task_id, task_meta, task_type, conversation_id
                )
                self._futures[task_id] = future

            except Exception as e:
                logger.error(f"❌ Worker loop error: {e}", exc_info=True)
                time.sleep(1.0)

    def _acquire_next_task(self) -> Optional[QueuedTask]:
        """从队列中获取下一个待执行的任务"""
        with self._queue_lock:
            if self._task_queue:
                return self._task_queue.popleft()
            return None

    def _check_phase_ready(self, task_type: str, conversation_id: str) -> bool:
        """检查任务是否满足阶段执行条件"""
        if task_type in self.PHASE_PARALLEL:
            return True

        if task_type in self.PHASE_SEQUENTIAL:
            with self._conv_step_counter_guard:
                running_steps = self._conv_step_counter.get(conversation_id, 0)
            if running_steps > 0:
                return False

            phase_lock = self._get_phase_lock(conversation_id)
            if phase_lock.locked():
                return False

        return True

    def _on_task_start(self, task_type: str, conversation_id: str):
        """任务开始前的阶段计数更新"""
        if task_type in self.PHASE_PARALLEL:
            with self._conv_step_counter_guard:
                self._conv_step_counter[conversation_id] = \
                    self._conv_step_counter.get(conversation_id, 0) + 1
        elif task_type in self.PHASE_SEQUENTIAL:
            phase_lock = self._get_phase_lock(conversation_id)
            phase_lock.acquire()

    def _on_task_finish(self, task_type: str, conversation_id: str):
        """任务完成后的阶段计数更新和 finalize 唤醒"""
        if task_type in self.PHASE_PARALLEL:
            with self._conv_step_counter_guard:
                self._conv_step_counter[conversation_id] = \
                    self._conv_step_counter.get(conversation_id, 1) - 1
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
            try:
                phase_lock.release()
            except RuntimeError:
                pass

    def _get_phase_lock(self, conversation_id: str) -> threading.Lock:
        with self._conv_phase_locks_guard:
            if conversation_id not in self._conv_phase_locks:
                self._conv_phase_locks[conversation_id] = threading.Lock()
            return self._conv_phase_locks[conversation_id]

    def _execute_task_with_phase_tracking(self, task_id: str, task_meta: dict,
                                           task_type: str, conversation_id: str):
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

            from devpartner_agent.core.database import get_db
            db = get_db()
            now_ts = datetime.now().isoformat()
            db.query_local("""
                UPDATE task_queue SET status = 'running', started_at = ?, last_heartbeat = ?, worker_id = ?
                WHERE task_id = ?
            """, (now_ts, now_ts, threading.current_thread().name, task_id))
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

            timeout_seconds = task_meta.get("timeout_seconds", 300)
            result = self._execute_with_timeout(task_meta, timeout_seconds)

            execution_time = time.time() - start_time

            with self._stats_lock:
                self._stats["total_completed"] += 1
                old_avg = self._stats["avg_execution_time_sec"]
                new_count = self._stats["total_completed"]
                self._stats["avg_execution_time_sec"] = (
                    (old_avg * (new_count - 1) + execution_time) / new_count
                )

            self._update_task_status(task_id, TaskStatus.COMPLETED.value, result=result)
            db.query_local("""
                UPDATE task_queue SET status = 'completed', result = ?, completed_at = ?, progress = 1.0,
                    actual_memory_mb = ?
                WHERE task_id = ?
            """, (json.dumps(result, ensure_ascii=False) if result else None,
                  datetime.now().isoformat(), task_meta.get("estimated_memory_mb", 100), task_id))

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
                    from devpartner_agent.core.database import get_db
                    db = get_db()
                    db.query_local(
                        "UPDATE task_queue SET status = 'failed', error_message = ? WHERE task_id = ? AND status = 'running'",
                        ("db_unavailable", task_id)
                    )
                except Exception:
                    pass

            if task_id in self._futures:
                del self._futures[task_id]

    def _execute_with_timeout(self, task_meta: dict, timeout_seconds: int) -> Any:
        result_container = {"result": None, "error": None, "done": False}
        lock = threading.Lock()

        def worker():
            try:
                r = self._dispatch_task_execution(task_meta)
                with lock:
                    result_container["result"] = r
                    result_container["done"] = True
            except Exception as e:
                with lock:
                    result_container["error"] = e
                    result_container["done"] = True

        t = threading.Thread(target=worker, name=f"timeout_worker_{task_meta.get('task_id', '')}", daemon=True)
        t.start()
        t.join(timeout=timeout_seconds)

        with lock:
            if result_container["done"]:
                if result_container["error"]:
                    raise result_container["error"]
                return result_container["result"]

        logger.error(f"⏰ 任务执行超时 ({timeout_seconds}s)")
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
        payload["_progress_callback"] = lambda progress, partial="", note="": \
            self.update_task_progress(task_id, progress, partial, note)

        handler = self._handlers.get(task_type)
        if handler is None:
            raise ValueError(
                f"未注册的任务类型: {task_type} | 已注册: {list(self._handlers.keys())}"
            )
        return handler(payload)

    # ══════════════════════════════════════════════════════════
    # 失败处理 & 重试
    # ══════════════════════════════════════════════════════════

    def _handle_task_failure(self, task_id: str, error_msg: str, db, release_event: threading.Event = None):
        task_meta = self._task_map.get(task_id)
        if not task_meta:
            return

        retry_count = task_meta.get("retry_count", 0)
        max_retries = task_meta.get("max_retries", 3)

        if retry_count < max_retries:
            new_retry_count = retry_count + 1
            delay = min(2 ** new_retry_count, 30)

            task_meta["retry_count"] = new_retry_count
            task_meta["error_message"] = error_msg
            task_meta["status"] = TaskStatus.PENDING.value

            next_retry = (datetime.now().isoformat()
                          if delay == 0
                          else (datetime.now().replace(microsecond=0).isoformat()
                                if delay <= 1
                                else (datetime.now() + timedelta(seconds=delay)).isoformat()))

            if db is not None:
                try:
                    db.query_local("""
                        UPDATE task_queue SET
                            status = 'pending', retry_count = ?, error_message = ?,
                            next_retry_at = ?
                        WHERE task_id = ?
                    """, (new_retry_count, error_msg, next_retry, task_id))
                except Exception:
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
                    db.query_local("""
                        UPDATE task_queue SET status = 'failed', error_message = ?, completed_at = ?
                        WHERE task_id = ?
                    """, (error_msg, datetime.now().isoformat(), task_id))
                except Exception:
                    pass

            with self._stats_lock:
                self._stats["total_failed"] += 1

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
            if status in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.TIMEOUT.value]:
                self._task_map[task_id]["completed_at"] = datetime.now().isoformat()

    def _update_memory_usage(self, memory_mb: int, delta: bool):
        with self._memory_lock:
            if delta:
                self._current_memory_mb += memory_mb
            else:
                self._current_memory_mb = max(0, self._current_memory_mb - memory_mb)

    def _invoke_callback(self, callback_name: str, task_id: str, result: Any):
        try:
            from devpartner_agent.services.callback_registry import get_callback_registry
            registry = get_callback_registry()

            task_meta = self._task_map.get(task_id, {})
            payload = task_meta.get("payload", {})
            conversation_id = payload.get("conversation_id", "")

            if conversation_id:
                triggered = registry.trigger_complete(
                    conversation_id=conversation_id,
                    result=result or {},
                    task_id=task_id,
                )
                logger.info(f"📞 回调触发: {callback_name} | 任务: {task_id} | 会话: {conversation_id}")
        except Exception as e:
            logger.warning(f"⚠️ 回调触发失败: {e}")

    # ══════════════════════════════════════════════════════════
    # 查询 & 控制
    # ══════════════════════════════════════════════════════════

    def get_task_status(self, task_id: str) -> Optional[dict]:
        if task_id not in self._task_map:
            from devpartner_agent.core.database import get_db
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
        from devpartner_agent.core.database import get_db
        db = get_db()
        db.query_local("UPDATE task_queue SET status = 'cancelled' WHERE task_id = ?", (task_id,))

        with self._stats_lock:
            self._stats["total_cancelled"] += 1
        return True

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
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local(
                "UPDATE task_queue SET last_heartbeat = ? WHERE task_id = ?",
                (now, task_id)
            )
        except Exception:
            pass

    def update_task_progress(self, task_id: str, progress: float,
                              partial_result: str = "", status_note: str = ""):
        """更新任务进度（0.0 ~ 1.0）和部分结果预览。

        Worker 在处理长任务时调用，让外部轮询者看到实时进度。

        Args:
            task_id: 任务ID
            progress: 进度 0.0 ~ 1.0
            partial_result: 部分生成结果的前若干字符（预览用）
            status_note: 状态备注（如 "正在生成用户画像..."）
        """
        progress = max(0.0, min(1.0, progress))
        now = datetime.now().isoformat()

        if task_id in self._task_map:
            self._task_map[task_id]["progress"] = progress
            self._task_map[task_id]["partial_result"] = partial_result[:2000] if partial_result else ""
            self._task_map[task_id]["status_note"] = status_note
            self._task_map[task_id]["last_heartbeat"] = now

        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local(
                "UPDATE task_queue SET progress = ?, partial_result = ?, status_note = ?, last_heartbeat = ? WHERE task_id = ?",
                (progress, partial_result[:2000] if partial_result else "", status_note, now, task_id)
            )
        except Exception:
            pass

    def get_running_tasks_with_progress(self) -> list:
        """获取所有运行中任务的进度信息（用于 Dashboard 展示）"""
        running = []
        for tid, meta in self._task_map.items():
            if meta.get("status") == TaskStatus.RUNNING.value:
                running.append({
                    "task_id": tid,
                    "task_type": meta.get("task_type", ""),
                    "progress": meta.get("progress", 0.0),
                    "partial_result": meta.get("partial_result", ""),
                    "status_note": meta.get("status_note", ""),
                    "last_heartbeat": meta.get("last_heartbeat", ""),
                    "started_at": meta.get("started_at", ""),
                    "conversation_id": meta.get("payload", {}).get("conversation_id", ""),
                })
        return running

    def get_queue_stats(self) -> dict:
        pending_count = sum(
            1 for t in self._task_map.values()
            if t["status"] in [TaskStatus.PENDING.value, TaskStatus.QUEUED.value]
        )
        running_count = sum(
            1 for t in self._task_map.values()
            if t["status"] == TaskStatus.RUNNING.value
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
                {"id": t.task_id, "type": t.task_data.get("task_type"),
                 "conv": t.task_data.get("payload", {}).get("conversation_id", "global")}
                for t in list(self._task_queue)[:5]
            ]

        with self._memory_lock:
            memory_info = {
                "current_mb": self._current_memory_mb,
                "max_mb": self._max_memory_mb,
                "usage_percent": (self._current_memory_mb / self._max_memory_mb * 100) if self._max_memory_mb > 0 else 0
            }

        status_count = {}
        for task_meta in self._task_map.values():
            status = task_meta.get("status", "unknown")
            status_count[status] = status_count.get(status, 0) + 1

        running_tasks = [
            {"id": tid, "type": meta.get("task_type"), "started": meta.get("started_at"),
             "conv": meta.get("payload", {}).get("conversation_id", "global")}
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
            "semaphore_value": self._semaphore._value if hasattr(self._semaphore, '_value') else "unknown",
            "active_futures": len(self._futures),
            "pending_in_queue": pending_count,
            "pending_preview": pending_tasks,
            "total_tracked": len(self._task_map),
            "active_phase_locks": len([l for l in self._conv_phase_locks.values() if l.locked()]),
            "total_phase_locks": len(self._conv_phase_locks),
            "conv_step_counters": step_counter_snapshot,
            "conv_phase_locks": conv_phase_status,
            "memory": memory_info,
            "status_breakdown": status_count,
            "running_tasks": running_tasks,
            "stats": self._stats.copy()
        }

    # ══════════════════════════════════════════════════════════
    # 启动恢复 & 重试调度
    # ══════════════════════════════════════════════════════════

    def _recover_interrupted_tasks(self):
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            if not db.is_local_initialized():
                return
            rows = db.query_local(
                "SELECT task_id, status FROM task_queue WHERE status IN ('processing', 'running') AND is_deleted = 0"
            )
            if rows:
                count = len(rows)
                db.query_local(
                    "UPDATE task_queue SET status = 'pending', started_at = NULL, worker_id = NULL, error_message = 'Recovered after restart' WHERE status IN ('processing', 'running') AND is_deleted = 0"
                )
                logger.info(f"🔄 启动恢复: {count} 个中断任务已重置为 pending")
        except Exception as e:
            logger.warning(f"⚠️ 启动恢复失败（非致命）: {e}")

    def _retry_scheduler_loop(self):
        while not self._shutdown_flag:
            try:
                time.sleep(10)
                from devpartner_agent.core.database import get_db
                db = get_db()
                if not db.is_local_initialized():
                    time.sleep(10)
                    continue
                now = datetime.now().isoformat()
                rows = db.query_local(
                    "SELECT task_id, retry_count, max_retries FROM task_queue "
                    "WHERE status = 'failed' AND is_deleted = 0 "
                    "AND next_retry_at IS NOT NULL AND next_retry_at <= ?",
                    (now,)
                )
                for row in (rows or []):
                    task_id = row["task_id"]
                    retry_count = row["retry_count"]
                    max_retries = row["max_retries"]

                    if retry_count < max_retries:
                        db.query_local(
                            "UPDATE task_queue SET status = 'pending', next_retry_at = NULL WHERE task_id = ?",
                            (task_id,)
                        )
                        logger.info(f"🔄 重试调度: {task_id} | 第{retry_count + 1}次")
                    else:
                        db.query_local(
                            "UPDATE task_queue SET status = 'dead', error_message = 'Max retries exceeded' WHERE task_id = ?",
                            (task_id,)
                        )
                        logger.warning(f"💀 任务永久失败: {task_id}")
            except Exception as e:
                logger.warning(f"⚠️ 重试调度异常（非致命）: {e}")

    # ══════════════════════════════════════════════════════════
    # 僵尸任务 & 孤儿步骤清理
    # ══════════════════════════════════════════════════════════

    def _auto_cleanup_zombies(self):
        """v9.5.1: 基于 last_heartbeat 判断僵尸（优先），fallback 到 started_at"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            if not db.is_local_initialized():
                return
            rows = db.query_local(
                "SELECT task_id, started_at, last_heartbeat FROM task_queue WHERE status='running'"
            )
            if not rows:
                return

            now = datetime.now()
            max_age = 3600  # 1 小时无心跳 = 僵尸
            cleaned = 0
            for row in rows:
                # 优先使用心跳时间判断
                heartbeat = row.get("last_heartbeat")
                if heartbeat:
                    try:
                        hb_time = datetime.fromisoformat(heartbeat)
                        age_s = (now - hb_time).total_seconds()
                        if age_s > max_age:
                            self._mark_zombie(db, row['task_id'], age_s, now)
                            cleaned += 1
                        continue
                    except Exception:
                        pass

                # fallback: 用 started_at 判断
                started_at = row.get("started_at")
                if not started_at:
                    continue
                try:
                    started = datetime.fromisoformat(started_at)
                    age_s = (now - started).total_seconds()
                    if age_s > max_age:
                        self._mark_zombie(db, row['task_id'], age_s, now)
                        cleaned += 1
                except Exception:
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
            (f"Auto zombie cleanup after {age_s/3600:.1f}h (no heartbeat)", now.isoformat(), task_id)
        )
        if task_id in self._task_map:
            self._update_task_status(task_id, TaskStatus.TIMEOUT.value,
                                      error=f"Zombie after {age_s/3600:.1f}h")
        if task_id in self._futures:
            try:
                self._futures[task_id].cancel()
            except Exception:
                pass
            del self._futures[task_id]

    def _auto_cleanup_orphan_steps(self):
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            if not db.is_local_initialized():
                return
            now = datetime.now()

            db.query_local("""
                UPDATE conversation_steps SET status = 'orphaned', error_message = ?
                WHERE status = 'pending'
                  AND created_at < ?
                  AND created_at IS NOT NULL
            """, (f"Auto orphaned after 24h at {now.isoformat()}", (now - timedelta(hours=24)).isoformat()))

            db.query_local("""
                UPDATE conversation_steps SET status = 'pending', error_message = ?
                WHERE status = 'in_progress'
                  AND started_at < ?
                  AND started_at IS NOT NULL
            """, (f"Auto reset from in_progress after 10min at {now.isoformat()}", (now - timedelta(minutes=10)).isoformat()))
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
                    self._update_task_status(task_id, TaskStatus.TIMEOUT.value, error=f"Force cleanup after {age_seconds:.1f}s")

                    try:
                        from devpartner_agent.core.database import get_db
                        db = get_db()
                        db.query_local("""
                            UPDATE task_queue SET status = 'timeout', error_message = ?, completed_at = ?
                            WHERE task_id = ?
                        """, (f"Zombie cleanup after {age_seconds:.1f}s", now.isoformat(), task_id))
                    except Exception:
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
            1 for meta in self._task_map.values()
            if meta.get("status") == TaskStatus.RUNNING.value
        )

        expected_value = max(0, 2 - actual_running)
        current_value = 0
        if hasattr(self._semaphore, '_value'):
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


_task_queue_instance: Optional[TaskQueue] = None

def get_task_queue() -> TaskQueue:
    global _task_queue_instance
    if _task_queue_instance is None:
        _task_queue_instance = TaskQueue()
    return _task_queue_instance