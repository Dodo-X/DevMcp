"""
异步任务队列 (v6.0)
==================
管理后台任务的异步执行，支持 FIFO 调度和同会话顺序保证。

核心功能：
  ✅ FIFO 先进先出调度（解决"总结先于步骤执行"的问题）
  ✅ 同会话任务顺序执行（conversation_id 互斥）
  ✅ 跨会话并行执行（不同对话可同时处理）
  - 并发控制（Semaphore）
  - 内存占用监控
  - 任务超时处理
  - 失败重试机制
  - 与 LLMService / ConversationManager 集成

设计原则：
  - 内存友好（本地系统限制）
  - 非阻塞（不阻塞客户端交互）
  - 可观测性（日志 + 状态查询）
  - 容错（优雅降级）
  - 数据完整性（步骤必须按顺序完成后再总结）

使用示例：
    queue = TaskQueue()
    task_id = queue.submit_task("analysis", {"content": "...", "conversation_id": "xxx"})
    status = queue.get_task_status(task_id)

v6.0 变更：
  - 从优先级堆改为 FIFO 队列
  - 新增 conversation_id 级别的互斥锁
  - 保证同一会话内的任务严格按提交顺序执行
"""
import json
import uuid
import logging
import threading
import time
import collections
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskPriority:
    """任务优先级常量"""
    CRITICAL = 100  # 紧急任务（系统关键）
    HIGH = 10       # 高优先级（用户交互）
    MEDIUM = 5      # 中等优先级（常规分析）
    LOW = 1         # 低优先级（批量处理）
    BACKGROUND = 0  # 后台任务（清理/归档）


@dataclass
class QueuedTask:
    """FIFO 队列任务包装器"""
    task_id: str                            # 任务ID
    task_data: dict                         # 任务数据
    enqueue_time: float = field(default_factory=time.time)  # 入队时间戳


class TaskQueue:
    """
    异步任务队列管理器 (v6.0 - FIFO + 同会话顺序保证)

    特性：
      ✅ FIFO 先进先出调度（按提交顺序执行）
      ✅ 同会话任务串行执行（conversation_id 互斥锁）
      ✅ 跨会话并行执行（不同对话可同时处理）
      - Semaphore 全局并发控制
      - 动态内存监控
      - 超时自动取消
      - 指数退避重试

    资源策略：
      - 默认全局并发数: 2（本地系统保守配置）
      - 最大内存阈值: 1.5GB（为LLM预留空间）
      - 单任务超时: 300秒（5分钟）
      - 最大重试: 3次

    调度规则：
      1. 同一 conversation_id 的任务必须按提交顺序执行
         （步骤1 → 步骤2 → ... → 总结，不能乱序）
      2. 不同 conversation_id 的任务可以并行执行
      3. 全局最多 N 个任务并发（默认2个）
    """

    def __init__(self):

        # ── 核心数据结构（FIFO 队列）──
        self._task_queue: collections.deque = collections.deque()  # FIFO 队列
        self._queue_lock = threading.Lock()                        # 队列操作锁
        self._task_map: Dict[str, dict] = {}                       # task_id -> 元数据
        self._futures: Dict[str, Future] = {}                     # task_id -> Future对象

        # ── 同会话互斥锁 ──
        self._conversation_locks: Dict[str, threading.Lock] = {}   # conversation_id -> Lock
        self._conversation_locks_lock = threading.Lock()          # 锁字典的锁

        # ── 并发控制 ──
        self._semaphore: threading.Semaphore = threading.Semaphore(2)  # 默认全局并发数=2
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=4,                                          # 工作线程池大小
            thread_name_prefix="task_worker_"
        )
        
        # ── 资源监控 ──
        self._max_memory_mb: float = 1536.0             # 最大内存限制（1.5GB）
        self._current_memory_mb: float = 0.0            # 当前内存使用
        self._memory_lock = threading.Lock()
        
        # ── 统计信息 ──
        self._stats = {
            "total_submitted": 0,
            "total_completed": 0,
            "total_failed": 0,
            "total_cancelled": 0,
            "avg_execution_time_sec": 0.0,
        }
        self._stats_lock = threading.Lock()
        
        # ── 启动工作线程 ──
        self._shutdown_flag: bool = False
        self._worker_thread: threading.Thread = threading.Thread(
            target=self._worker_loop,
            name="task_scheduler_main",
            daemon=True
        )
        self._worker_thread.start()

        # v7.0: 启动恢复 — 将上次异常中断卡在 processing/running 的任务重置为 pending
        self._recover_interrupted_tasks()

        # v7.0: 重试调度线程 — 定时扫描 failed 任务，到期后重置为 pending
        self._retry_thread: threading.Thread = threading.Thread(
            target=self._retry_scheduler_loop,
            name="task_retry_scheduler",
            daemon=True
        )
        self._retry_thread.start()

        logger.info("🔄 异步任务队列已启动 (v7.0 恢复+重试调度)")
    
    def submit_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: int = TaskPriority.MEDIUM,
        timeout_seconds: int = 300,
        max_retries: int = 3,
        estimated_memory_mb: int = 100,
        callback: Optional[Callable] = None
    ) -> str:
        """
        提交新任务到队列
        
        Args:
            task_type: 任务类型（conversation_analysis/knowledge_extraction等）
            payload: 任务载荷（JSON可序列化字典）
            priority: 优先级（数字越大越优先）
            timeout_seconds: 超时时间（秒）
            max_retries: 最大重试次数
            estimated_memory_mb: 预估内存占用（MB）
            callback: 完成回调函数
        
        Returns:
            task_id (str): 唯一任务标识符
        """
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
        }
        
        # 写入数据库持久化
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            # v7.0: 自动计算 sort_order（自增序号，保证 FIFO）
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
        
        # 加入 FIFO 队列（v6.0：不再使用优先级堆）
        with self._queue_lock:
            self._task_queue.append(QueuedTask(task_id, task_meta))

        self._task_map[task_id] = task_meta

        conversation_id = payload.get("conversation_id", "global")
        with self._stats_lock:
            self._stats["total_submitted"] += 1

        logger.info(f"📥 提交任务: {task_id} | 类型: {task_type} | 会话: {conversation_id}")
        return task_id
    
    def _worker_loop(self):
        """工作线程主循环 - FIFO 调度 + 同会话顺序保证 + 僵尸任务自动清理"""
        _last_zombie_check = 0      # ponytail: 每60s检查一次，避免频繁DB查询
        _last_orphan_check = 0      # v7.2: 每300s检查孤儿 conversation_steps
        while not self._shutdown_flag:
            try:
                # 定期清理僵尸任务（卡死在 LLM 推理的任务）
                if time.time() - _last_zombie_check > 60:
                    self._auto_cleanup_zombies()
                    _last_zombie_check = time.time()

                # v7.2: 定期清理孤儿 conversation_steps（pending超24h / in_progress超10min）
                if time.time() - _last_orphan_check > 300:
                    self._auto_cleanup_orphan_steps()
                    _last_orphan_check = time.time()

                # 从 FIFO 队列中取出下一个任务
                task = self._acquire_next_task()
                if task is None:
                    time.sleep(0.5)  # 无任务时短暂休眠
                    continue

                task_id = task.task_id
                task_meta = task.task_data
                conversation_id = task_meta.get("payload", {}).get("conversation_id", "global")

                # ✅ 检查同会话是否有任务正在运行（顺序保证）
                conv_lock = self._get_conversation_lock(conversation_id)
                if conv_lock.locked():
                    # 同会话有任务在执行，放回队首（不丢失位置）
                    logger.debug(f"⏳ 会话 {conversation_id} 有任务运行中，{task_id} 等待")
                    with self._queue_lock:
                        self._task_queue.appendleft(task)  # 放回队首
                    time.sleep(0.5)
                    continue

                # 检查全局资源是否充足
                if not self._check_resource_availability(task_meta):
                    logger.warning(f"⚠️ 资源不足，任务排队等待: {task_id}")
                    with self._queue_lock:
                        self._task_queue.appendleft(task)  # 放回队首
                    time.sleep(2.0)
                    continue

                # ✅ 获取会话锁（保证同一会话任务串行）
                conv_lock.acquire()

                # 执行任务（传入会话锁以便释放）
                future = self._executor.submit(
                    self._execute_task_with_conv_lock,
                    task_id, task_meta, conv_lock
                )
                self._futures[task_id] = future

            except Exception as e:
                logger.error(f"❌ Worker loop error: {e}", exc_info=True)
                time.sleep(1.0)

    def _acquire_next_task(self) -> Optional[QueuedTask]:
        """从 FIFO 队列中获取下一个待执行任务"""
        with self._queue_lock:
            while self._task_queue:
                task = self._task_queue.popleft()  # FIFO：从队首取出
                task_id = task.task_id

                # 检查任务是否已被取消
                if task_id in self._task_map and self._task_map[task_id]["status"] != TaskStatus.CANCELLED.value:
                    return task
            return None

    def _get_conversation_lock(self, conversation_id: str) -> threading.Lock:
        """获取或创建指定会话的互斥锁（线程安全）"""
        with self._conversation_locks_lock:
            if conversation_id not in self._conversation_locks:
                self._conversation_locks[conversation_id] = threading.Lock()
                logger.debug(f"🔒 创建会话锁: {conversation_id}")
            return self._conversation_locks[conversation_id]

    def _execute_task_with_conv_lock(
        self,
        task_id: str,
        task_meta: dict,
        conv_lock: threading.Lock
    ):
        """带会话锁的任务执行包装器（确保 finally 中释放会话锁）"""
        try:
            return self._execute_task_wrapper(task_id, task_meta)
        finally:
            # ✅ 无论成功/失败/超时，都必须释放会话锁
            conv_lock.release()
            logger.debug(f"🔓 释放会话锁: {task_meta.get('payload', {}).get('conversation_id', 'global')}")
    
    def _check_resource_availability(self, task_meta: dict) -> bool:
        """检查系统资源是否足够执行任务"""
        # 检查并发槽位（用 acquire(blocking=False) 原子操作，避免访问私有属性 _value 的竞态）
        if not self._semaphore.acquire(blocking=False):
            return False
        # 立即释放：这里只是"检查"而非"获取"，真正获取在 _execute_task_wrapper 中
        self._semaphore.release()

        # 检查内存
        required_memory = task_meta.get("estimated_memory_mb", 100)
        with self._memory_lock:
            available_memory = self._max_memory_mb - self._current_memory_mb
            if required_memory > available_memory * 0.8:  # 保留20%余量
                return False

        return True
    
    def _execute_task_wrapper(self, task_id: str, task_meta: dict):
        """任务执行包装器（包含资源获取/释放、超时控制、错误处理）"""
        start_time = time.time()
        db = None
        release_event = threading.Event()  # #3 修复：通知重试线程"资源已释放"

        # 获取并发许可
        acquired = self._semaphore.acquire(timeout=1.0)
        if not acquired:
            logger.warning(f"⚠️ 无法获取并发许可: {task_id}")
            return

        try:
            # 更新状态为运行中
            self._update_task_status(task_id, TaskStatus.RUNNING.value)
            self._update_memory_usage(task_meta.get("estimated_memory_mb", 100), delta=True)

            # 更新数据库状态
            from devpartner_agent.core.database import get_db
            db = get_db()
            db.query_local("""
                UPDATE task_queue SET status = 'running', started_at = ?, worker_id = ?
                WHERE task_id = ?
            """, (datetime.now().isoformat(), threading.current_thread().name, task_id))

            # 执行实际任务逻辑（带超时控制）
            timeout_seconds = task_meta.get("timeout_seconds", 300)
            result = self._execute_with_timeout(task_meta, timeout_seconds)

            # 计算执行时间
            execution_time = time.time() - start_time

            # 更新统计信息
            with self._stats_lock:
                self._stats["total_completed"] += 1
                old_avg = self._stats["avg_execution_time_sec"]
                new_count = self._stats["total_completed"]
                self._stats["avg_execution_time_sec"] = (
                    (old_avg * (new_count - 1) + execution_time) / new_count
                )

            # 标记完成
            self._update_task_status(task_id, TaskStatus.COMPLETED.value, result=result)
            db.query_local("""
                UPDATE task_queue SET status = 'completed', result = ?, completed_at = ?, progress = 1.0,
                    actual_memory_mb = ?
                WHERE task_id = ?
            """, (json.dumps(result, ensure_ascii=False) if result else None,
                  datetime.now().isoformat(), task_meta.get("estimated_memory_mb", 100), task_id))

            logger.info(f"✅ 任务完成: {task_id} | 耗时: {execution_time:.2f}s")

            # 执行回调（如果有）
            callback_name = task_meta.get("callback")
            if callback_name:
                self._invoke_callback(callback_name, task_id, result)

        except TimeoutError:
            logger.error(f"⏰ 任务超时: {task_id} (>{task_meta.get('timeout_seconds', 300)}s)")
            self._handle_task_failure(task_id, "Timeout exceeded", db, release_event)
            self._update_task_status(task_id, TaskStatus.TIMEOUT.value)

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"❌ 任务执行失败: {task_id} | 错误: {error_msg}", exc_info=True)
            self._handle_task_failure(task_id, error_msg, db, release_event)

        finally:
            # 先释放资源（semaphore + 内存）
            self._semaphore.release()
            self._update_memory_usage(task_meta.get("estimated_memory_mb", 100), delta=False)
            release_event.set()  # #3 修复：通知重试线程"资源已释放，可以入队了"

            # db 连接失败时也确保任务状态不卡死
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
        """在独立线程中执行任务，带超时保护

        ponytail: 用 Thread + join(timeout) 而非 future，当超时或 LLM 卡死时直接中断线程
        """
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

        # 超时：join 返回但线程仍在运行（LLM 推理卡死场景）
        logger.error(f"⏰ 任务执行超时 ({timeout_seconds}s)，LLM 推理可能已卡死")
        raise TimeoutError(f"Task execution exceeded {timeout_seconds}s")

    def _dispatch_task_execution(self, task_meta: dict) -> Any:
        """根据任务类型分发到具体的执行逻辑"""
        task_type = task_meta["task_type"]
        payload = task_meta["payload"]
        
        if task_type == "conversation_analysis":
            return self._execute_conversation_analysis(payload)
        elif task_type == "step_analysis":
            return self._execute_step_analysis(payload)
        elif task_type == "conversation_finalize":
            return self._execute_conversation_finalize(payload)
        elif task_type == "knowledge_extraction":
            return self._execute_knowledge_extraction(payload)
        elif task_type == "profile_update":
            return self._execute_profile_update(payload)
        elif task_type == "system_optimization":
            return self._execute_system_optimization(payload)
        else:
            raise ValueError(f"Unknown task type: {task_type}")
    
    def _execute_step_analysis(self, payload: dict) -> dict:
        """
        执行单步骤分析任务（v7.1 增强 — 系统 LLM 深度分析）
        
        分析单个子任务的内容，提取：
          - 思考模式：AI/开发者如何分析问题、推理决策
          - 使用的命令：便于复现和学习
          - 语法知识点：涉及的编程语言特性和模式
          - 客户端提供的 knowledge_points 写入 DB
          - 文件变更记录
        
        用户未来可以按图索骥，通过知识点搜索快速找到解决方案。
        """
        step_start = datetime.now()  # v7.2: 记录步骤开始时间，用于计算实际耗时

        conversation_id = payload.get("conversation_id", "")
        step_id = payload.get("step_id", "")
        step_name = payload.get("step_name", "")
        content = payload.get("content", "")
        knowledge_points = payload.get("knowledge_points", [])
        files_changed = payload.get("files_changed", [])
        step_type = payload.get("step_type", "general")
        symptom = payload.get("symptom", "")
        root_cause = payload.get("root_cause", "")
        solution = payload.get("solution", "")

        from devpartner_agent.core.database import get_db
        db = get_db()

        results = {
            "step_id": step_id,
            "knowledge_points_created": 0,
            "skill_domains": [],
            "files_indexed": len(files_changed),
            "llm_analyzed": False,
        }

        # ════ 0. 系统 LLM 深度分析步骤内容 ════
        try:
            from devpartner_agent.services.llm_service import get_llm_service
            llm = get_llm_service()
            if llm and llm.is_available():
                llm_result = llm.analyze_step_content(
                    step_name=step_name,
                    step_type=step_type,
                    content=content,
                    symptom=symptom,
                    root_cause=root_cause,
                    solution=solution,
                )
                if llm_result:
                    results["llm_analyzed"] = True
                    
                    # 存储 LLM 提取的思考模式
                    thinking_patterns = llm_result.get("thinking_patterns", [])
                    results["thinking_patterns"] = thinking_patterns
                    
                    # 存储 LLM 提取的命令
                    commands_used = llm_result.get("commands_used", [])
                    results["commands_used"] = commands_used
                    
                    # 存储 LLM 提取的语法知识点
                    syntax_points = llm_result.get("syntax_points", [])
                    results["syntax_points"] = syntax_points
                    
                    # 存储复杂度评估
                    results["complexity_level"] = llm_result.get("complexity_level", "simple")
                    
                    # 存储关键决策
                    results["key_decision"] = llm_result.get("key_decision", "")
                    
                    # LLM 提取的知识点也写入 knowledge_points 表
                    extracted_kp = llm_result.get("extracted_knowledge", [])
                    if extracted_kp:
                        from devpartner_agent.services.conversation_manager import ConversationManager
                        mgr = ConversationManager()
                        for kp in extracted_kp:
                            mgr._create_knowledge_point(
                                title=kp.get("title", "LLM提取知识点"),
                                content=kp.get("desc", ""),
                                category="llm_extracted",
                                domain=kp.get("domain", "General"),
                                tags=kp.get("tags", [step_type]),
                                source_type="step_llm",
                                source_id=step_id,
                            )
                        results["llm_knowledge_points"] = len(extracted_kp)
                    else:
                        results["llm_knowledge_points"] = 0
        except Exception as e:
            logger.warning(f"LLM 步骤分析失败（非致命）: {e}")

        # 1. 如果提供了知识点，写入 knowledge_points 表
        kp_ids = []
        if knowledge_points:
            from devpartner_agent.services.conversation_manager import ConversationManager
            mgr = ConversationManager()
            for kp in knowledge_points:
                kp_id = mgr._create_knowledge_point(
                    title=kp.get("title", "未命名知识点"),
                    content=kp.get("desc", ""),
                    category="step_extracted",
                    domain=kp.get("domain", "General"),
                    tags=kp.get("tags", [step_type]),
                    source_type="step",
                    source_id=step_id,
                )
                if kp_id:
                    kp_ids.append(kp_id)
            results["knowledge_points_created"] = len(kp_ids)

        # v7.2: 计算实际耗时
        actual_duration_ms = int((datetime.now() - step_start).total_seconds() * 1000)

        # 2. 更新步骤状态为已完成（output_data 记录 LLM 分析详情 + knowledge_point_ids）
        db.query_local("""
            UPDATE conversation_steps SET
                status = 'completed', output_data = ?,
                knowledge_point_ids = ?,
                completed_at = ?, duration_ms = ?
            WHERE step_id = ?
        """, (
            json.dumps(results, ensure_ascii=False),
            json.dumps(kp_ids, ensure_ascii=False) if kp_ids else "",
            datetime.now().isoformat(),
            actual_duration_ms,
            step_id
        ))
        
        # 3. 更新会话已完成步骤数
        from devpartner_agent.services.conversation_manager import ConversationManager
        mgr = ConversationManager()
        mgr._update_completed_steps(conversation_id)
        
        logger.info(f"📋 Step analysis done: {step_id} | KP: {results['knowledge_points_created']} | LLM: {results['llm_analyzed']}")
        return results
    
    def _execute_conversation_finalize(self, payload: dict) -> dict:
        """
        执行对话全局分析任务（v7.1 增强 — 系统 LLM 深层分析）
        
        总分总的「总」环节，在对话所有步骤完成后执行：
          0. 🆕 系统 LLM 深层分析：系统问题/反复模式/系统不足/用户洞察
          1. 聚合所有步骤的分析结果
          2. 更新用户画像（user_skills + improvement_log）
          3. 构建/更新知识图谱
          4. 生成系统优化建议
          5. 对话质量评估
        """
        conversation_id = payload.get("conversation_id", "")
        summary = payload.get("summary", "")
        user_traits = payload.get("user_traits", {})
        key_decisions = payload.get("key_decisions", [])
        kg_data = payload.get("knowledge_graph", {})
        self_reflection = payload.get("self_reflection", "")
        
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        results = {
            "conversation_id": conversation_id,
            "traits_updated": 0,
            "decisions_recorded": 0,
            "knowledge_graph_updated": 0,
            "optimization_suggestions": 0,
            "quality_score": 0,
            "llm_deep_analyzed": False,
        }
        
        # ════ 0. 系统 LLM 深层对话分析 ════
        try:
            from devpartner_agent.services.llm_service import get_llm_service
            llm = get_llm_service()
            if llm and llm.is_available():
                # 收集所有已完成步骤的摘要
                steps_rows = db.query_local(
                    "SELECT step_name, step_type, status, output_data, created_at "
                    "FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order",
                    (conversation_id,)
                )
                steps_summary = []
                for row in (steps_rows or []):
                    step_info = {
                        "name": row.get("step_name", ""),
                        "type": row.get("step_type", ""),
                        "status": row.get("status", ""),
                        "created_at": row.get("created_at", ""),
                    }
                    # 尝试解析 output_data 中的关键信息
                    output = row.get("output_data", "")
                    if output:
                        try:
                            output_dict = json.loads(output)
                            step_info["thinking_patterns"] = output_dict.get("thinking_patterns", [])
                            step_info["complexity"] = output_dict.get("complexity_level", "")
                        except (json.JSONDecodeError, TypeError):
                            pass
                    steps_summary.append(step_info)
                
                # 调用系统 LLM 深层分析
                deep_result = llm.analyze_conversation_deep(
                    summary=summary,
                    self_reflection=self_reflection,
                    user_traits=user_traits,
                    key_decisions=key_decisions,
                    steps_summary=steps_summary,
                )
                
                if deep_result:
                    results["llm_deep_analyzed"] = True
                    
                    # 存储系统问题分析
                    system_issues = deep_result.get("system_issues", [])
                    results["system_issues"] = system_issues
                    
                    # 存储系统不足分析
                    system_deficiencies = deep_result.get("system_deficiencies", [])
                    results["system_deficiencies"] = system_deficiencies
                    
                    # 存储用户洞察
                    user_insights = deep_result.get("user_insights", [])
                    results["user_insights"] = user_insights
                    
                    # 存储反复出现的模式
                    recurring_patterns = deep_result.get("recurring_patterns", [])
                    results["recurring_patterns"] = recurring_patterns
                    
                    # 存储综合评估
                    results["overall_assessment"] = deep_result.get("overall_assessment", "")
                    
                    # 存储风险领域
                    results["risk_areas"] = deep_result.get("risk_areas", [])
                    
                    # 存储好做法
                    results["positive_patterns"] = deep_result.get("positive_patterns", [])
                    
                    # 将 LLM 分析的系统问题写入 improvement_log
                    if system_issues:
                        for issue in system_issues[:5]:  # 限制数量
                            db.query_local("""
                                INSERT INTO improvement_log (
                                    timestamp, category, suggestion, priority, status, conversations_id
                                ) VALUES (?, 'system_issue', ?, ?, 'pending',
                                    (SELECT id FROM conversations WHERE conversation_id = ?)
                                )
                            """, (
                                datetime.now().isoformat(),
                                f"系统问题: {issue.get('issue', '')} | 根因: {issue.get('root_cause', '')} | 重复: {issue.get('is_recurring', False)}",
                                issue.get("severity", "medium"),
                                conversation_id,
                            ))
                    
                    # 将用户洞察写入 improvement_log
                    if user_insights:
                        for insight in user_insights[:5]:
                            db.query_local("""
                                INSERT INTO improvement_log (
                                    timestamp, category, suggestion, priority, status, conversations_id
                                ) VALUES (?, 'user_insight', ?, 'low', 'pending',
                                    (SELECT id FROM conversations WHERE conversation_id = ?)
                                )
                            """, (
                                datetime.now().isoformat(),
                                f"用户观察: {insight.get('observation', '')} | 模式: {insight.get('pattern', '')} | 建议: {insight.get('suggestion', '')}",
                                conversation_id,
                            ))
        except Exception as e:
            logger.warning(f"LLM 深层对话分析失败（非致命）: {e}")
        
        # 1. 用户画像更新
        if user_traits:
            try:
                # 获取 conversations.id
                conv_row = db.query_local(
                    "SELECT id FROM conversations WHERE conversation_id = ?",
                    (conversation_id,)
                )
                conversations_id = conv_row[0]["id"] if conv_row else None
                
                from server import _apply_user_traits
                trait_result = _apply_user_traits(user_traits, "codebuddy", conversations_id)
                results["traits_updated"] = trait_result.get("skills_updated", 0) if isinstance(trait_result, dict) else 0
            except Exception as e:
                logger.error(f"用户画像更新失败: {e}")
        
        # 2. 关键决策记录
        if key_decisions:
            try:
                for decision in key_decisions:
                    db.query_local("""
                        INSERT INTO improvement_log (
                            timestamp, category, suggestion, priority, status, conversations_id
                        ) VALUES (?, 'decision', ?, 'medium', 'pending',
                            (SELECT id FROM conversations WHERE conversation_id = ?)
                        )
                    """, (
                        datetime.now().isoformat(),
                        f"决策: {decision.get('decision', '')} | 原因: {decision.get('reason', '')} | 权衡: {decision.get('tradeoff', '')}",
                        conversation_id,
                    ))
                results["decisions_recorded"] = len(key_decisions)
            except Exception as e:
                logger.error(f"决策记录失败: {e}")
        
        # 3. 知识图谱更新
        if kg_data:
            try:
                nodes = kg_data.get("nodes", [])
                edges = kg_data.get("edges", [])
                if nodes or edges:
                    from devpartner_agent.services.conversation_manager import ConversationManager
                    mgr = ConversationManager()
                    kp_count = 0
                    for node in nodes:
                        title = node.get("label", node.get("title", "未知节点"))
                    # v7.2: 检查是否已有同名知识点，有则递增 usage_count
                    existing = db.query_local(
                        "SELECT id FROM knowledge_points WHERE title = ? LIMIT 1",
                        (title,)
                    )
                    if existing:
                        db.query_local("""
                            UPDATE knowledge_points SET
                                usage_count = usage_count + 1,
                                last_used_at = ?
                            WHERE id = ?
                        """, (datetime.now().isoformat(), existing[0]["id"]))
                        kp_count += 1
                    else:
                        kp_id = mgr._create_knowledge_point(
                            title=title,
                            content=node.get("description", ""),
                            category="knowledge_graph",
                            domain=node.get("domain", "General"),
                            tags=node.get("tags", []),
                            source_type="finalize",
                            source_id=conversation_id,
                        )
                        if kp_id:
                            kp_count += 1
                    results["knowledge_graph_updated"] = kp_count
            except Exception as e:
                logger.error(f"知识图谱更新失败: {e}")
        
        # 4. 系统优化建议（基于对话复盘 + LLM 分析）
        if self_reflection or results.get("llm_deep_analyzed"):
            try:
                from devpartner_agent.services.conversation_manager import ConversationManager, StepConfig, StepType
                mgr = ConversationManager()
                
                # 将 LLM 深层分析结果也传入系统优化步骤
                enhanced_system_data = {
                    "reflection": self_reflection,
                    "summary": summary,
                    "conversation_id": conversation_id,
                    "llm_deep_analysis": {
                        "system_issues": results.get("system_issues", []),
                        "system_deficiencies": results.get("system_deficiencies", []),
                        "recurring_patterns": results.get("recurring_patterns", []),
                        "risk_areas": results.get("risk_areas", []),
                        "overall_assessment": results.get("overall_assessment", ""),
                    },
                }
                
                fake_step = {
                    "step_id": f"optimize_{conversation_id}",
                    "conversation_id": conversation_id,
                    "step_type": "system_optimize",
                    "input_data": json.dumps({
                        "system_data": enhanced_system_data
                    }, ensure_ascii=False),
                }
                
                opt_result = mgr._execute_system_optimize_step(
                    fake_step,
                    {"system_data": enhanced_system_data}
                )
                results["optimization_suggestions"] = opt_result.get("output", {}).get("suggestions_generated", 0)

                # v7.2: 当优化建议中包含自动应用的变更时，写入 evolution_log
                auto_applied = opt_result.get("auto_applied")
                if auto_applied:
                    from devpartner_agent.core.config import get_project_version
                    current_version = get_project_version()
                    db.log_evolution(
                        change_type="auto_optimize",
                        description=f"对话 {conversation_id} 触发自动优化: {opt_result.get('description', '')}",
                        files_changed=opt_result.get("files", ""),
                        version=current_version,
                    )
                    results["evolution_logged"] = True
            except Exception as e:
                logger.error(f"系统优化建议生成失败: {e}")
        
        # 4.5 🆕 统一知识提取（技能+业务+关联分析）+ Vault 导出
        results["skill_extracted"] = 0
        results["business_extracted"] = 0
        results["vault_exported"] = 0
        try:
            # 构建完整对话文本（供 LLM 提取知识）
            conversation_text_parts = []
            for step in (steps_summary or []):
                name = step.get("name", "")
                stype = step.get("type", "")
                if name:
                    conversation_text_parts.append(f"[{stype}] {name}")
            conversation_text = "\n".join(conversation_text_parts) if conversation_text_parts else summary

            from devpartner_agent.services.knowledge_extractor import get_knowledge_extractor
            extractor = get_knowledge_extractor()
            extract_result = extractor.extract_all(
                conversation_id=conversation_id,
                conversation_text=conversation_text,
                key_decisions=key_decisions,
                source_session_id=conversation_id,
            )
            results["skill_extracted"] = extract_result.get("skill_extracted", 0)
            results["business_extracted"] = extract_result.get("business_extracted", 0)
            results["knowledge_ids"] = extract_result.get("knowledge_ids", [])

            # 🆕 导出到 Obsidian Vault（仅知识卡片，对话/统计走 SQL 直连）
            from devpartner_agent.services.vault_exporter import get_vault_exporter
            exporter = get_vault_exporter()
            vault_result = exporter.export_batch(
                conversation_id=conversation_id,
                summary=summary,
                key_decisions=key_decisions,
                steps_summary=steps_summary,
                knowledge_ids=extract_result.get("knowledge_ids", []),
            )
            results["vault_exported"] = (
                vault_result.get("skills_exported", 0) +
                vault_result.get("business_exported", 0)
            )
            results["vault_errors"] = vault_result.get("errors", [])
        except Exception as e:
            logger.warning(f"知识提取/Vault导出失败（非致命）: {e}")
        
        # 5. 标记 conversations 表 analyzed=1 + 存储 LLM 深层分析结果
        overall = results.get('overall_assessment', '')
        summary_stats = (
            f"系统问题={len(results.get('system_issues', []))}个, "
            f"不足={len(results.get('system_deficiencies', []))}个, "
            f"风险={len(results.get('risk_areas', []))}个"
        )

        # v7.2: 空值保护 — overall_assessment 为空时不拼接空文本
        if overall:
            llm_actions = f"LLM深层分析: {overall[:500]}"
            db.query_local("""
                UPDATE conversations SET analyzed = 1, updated_at = ?,
                    actions = CASE WHEN actions IS NULL OR actions = '' 
                        THEN ? ELSE actions || ' | LLM_DEEP: ' || ? END
                WHERE conversation_id = ?
            """, (
                datetime.now().isoformat(),
                llm_actions,
                summary_stats,
                conversation_id
            ))
        else:
            db.query_local("""
                UPDATE conversations SET analyzed = 1, updated_at = ?
                WHERE conversation_id = ?
            """, (datetime.now().isoformat(), conversation_id))

        # v7.2: 将本对话关联的 pending improvement_log 标记为 reviewed
        try:
            reviewed = db.query_local("""
                UPDATE improvement_log SET status = 'reviewed'
                WHERE conversations_id = (
                    SELECT id FROM conversations WHERE conversation_id = ?
                ) AND status = 'pending'
            """, (conversation_id,))
            reviewed_count = reviewed if isinstance(reviewed, int) else (reviewed.rowcount if hasattr(reviewed, 'rowcount') else 0)
            if reviewed_count > 0:
                results["improvements_reviewed"] = reviewed_count
                logger.info(f"📋 improvement_log 流转: {reviewed_count} pending → reviewed (会话: {conversation_id})")
        except Exception as e:
            logger.warning(f"improvement_log 状态流转失败（非致命）: {e}")
        logger.info(f"🎉 对话全局分析完成: {conversation_id} | LLM深层: {results['llm_deep_analyzed']} | {json.dumps({k: v for k, v in results.items() if k not in ('system_issues', 'system_deficiencies', 'user_insights', 'recurring_patterns')}, ensure_ascii=False)}")
        return results
    
    def _execute_conversation_analysis(self, payload: dict) -> dict:
        """执行对话分析任务"""
        conversation_id = payload.get("conversation_id")
        if not conversation_id:
            raise ValueError("Missing conversation_id in payload")

        from devpartner_agent.services.conversation_manager import ConversationManager
        mgr = ConversationManager()

        # 获取会话的步骤列表并按顺序执行
        status_info = mgr.get_conversation_status(conversation_id)
        if not status_info:
            raise ValueError(f"Conversation not found: {conversation_id}")

        steps = status_info["steps"]
        total_steps = len(steps)
        results = []

        # 集成回调注册表通知进度
        try:
            from devpartner_agent.services.callback_registry import get_callback_registry
            registry = get_callback_registry()

            for i, step in enumerate(steps):
                if step["status"] in ["pending", "failed"]:
                    # 通知步骤开始
                    registry.trigger_step_start(
                        conversation_id=conversation_id,
                        step_id=step["step_id"],
                        step_name=step.get("step_name", "Unknown"),
                    )

                    step_result = mgr.execute_single_step(step["step_id"])
                    results.append(step_result)

                    # 通知步骤完成
                    registry.trigger_step_complete(
                        conversation_id=conversation_id,
                        step_id=step["step_id"],
                        result=step_result,
                    )

                    # 通知整体进度
                    progress_pct = ((i + 1) / total_steps) * 100
                    registry.trigger_progress(
                        conversation_id=conversation_id,
                        percentage=progress_pct,
                        message=f"步骤 {i + 1}/{total_steps}: {step.get('step_name', 'Unknown')}",
                    )

                    # 如果步骤失败且未安排重试，中断整个会话
                    if step_result["status"] == "failed":
                        mgr.fail_conversation(conversation_id,
                                              f"Step failed: {step['step_id']}")
                        registry.trigger_error(
                            conversation_id=conversation_id,
                            error_message=f"Step failed: {step['step_id']}",
                        )
                        break
        except ImportError:
            # Callback registry not available, execute without callbacks
            for step in steps:
                if step["status"] in ["pending", "failed"]:
                    step_result = mgr.execute_single_step(step["step_id"])
                    results.append(step_result)
                    if step_result["status"] == "failed":
                        mgr.fail_conversation(conversation_id,
                                              f"Step failed: {step['step_id']}")
                        break

        return {
            "conversation_id": conversation_id,
            "steps_executed": len(results),
            "final_status": mgr.get_conversation_status(conversation_id)["conversation"]["status"],
        }
    
    def _execute_knowledge_extraction(self, payload: dict) -> dict:
        """执行知识点提取任务"""
        content = payload.get("content", "")
        domain = payload.get("domain", "General")
        
        if not content.strip():
            return {"knowledge_extracted": 0, "error": "Empty content"}
        
        from devpartner_agent.services.conversation_manager import ConversationManager
        mgr = ConversationManager()
        
        kp_id = mgr._create_knowledge_point(
            title=f"[{domain}] 自动提取知识点",
            content=content[:2000],  # 截断过长内容
            category="concept",
            domain=domain,
            tags=[domain, "auto-extracted"],
            source_type="task",
        )
        
        return {
            "knowledge_extracted": 1 if kp_id else 0,
            "knowledge_id": kp_id,
        }
    
    def _execute_profile_update(self, payload: dict) -> dict:
        """执行用户画像更新任务"""
        user_traits = payload.get("user_traits", {})
        conversation_id = payload.get("conversation_id", "unknown")
        
        from devpartner_agent.services.conversation_manager import ConversationManager, StepConfig, StepType
        mgr = ConversationManager()
        
        # 创建一个虚拟步骤来执行画像更新
        fake_step = {
            "step_id": f"profile_{uuid.uuid4().hex[:8]}",
            "conversation_id": conversation_id,
            "step_type": "user_profile",
            "input_data": json.dumps({"analysis_output": {"user_traits": user_traits}}, ensure_ascii=False),
        }
        
        result = mgr._execute_user_profile_step(fake_step, {"analysis_output": {"user_traits": user_traits}})
        return result["output"]
    
    def _execute_system_optimization(self, payload: dict) -> dict:
        """执行系统优化建议生成任务"""
        system_data = payload.get("system_data", {})
        improvement_history = payload.get("improvement_history", [])
        
        from devpartner_agent.services.llm_service import LLMService
        llm = LLMService()
        
        suggestions = llm.generate_self_improvement_suggestions(system_data, improvement_history)
        
        return {
            "suggestions_generated": len(suggestions) if suggestions else 0,
            "suggestions": suggestions or [],
        }
    
    def _handle_task_failure(self, task_id: str, error_msg: str, db, release_event: threading.Event = None):
        """处理任务失败（重试或标记失败）

        Args:
            release_event: #3 修复 — 通知重试线程等待资源释放后再入队，
                          避免 semaphore 槽位被"僵尸任务"占用导致假死锁。
        """
        task_meta = self._task_map.get(task_id)
        if not task_meta:
            return

        retry_count = task_meta.get("retry_count", 0)
        max_retries = task_meta.get("max_retries", 3)

        if retry_count < max_retries:
            # 安排重试（指数退避）
            new_retry_count = retry_count + 1
            delay = min(2 ** new_retry_count, 30)  # 最大延迟30秒

            task_meta["retry_count"] = new_retry_count
            task_meta["error_message"] = error_msg
            task_meta["status"] = TaskStatus.PENDING.value

            # v7.0: 计算下次重试时间（用于跨进程重启后的重试调度）
            next_retry = (datetime.now().isoformat()
                          if delay == 0
                          else (datetime.now().replace(microsecond=0).isoformat()
                                if delay <= 1
                                else (datetime.now() + datetime.timedelta(seconds=delay)).isoformat()))

            # 更新数据库（db 可能为 None，安全处理）
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

            # #3 修复：重新入队前等待资源释放（semaphore + 内存），
            #  避免任务在资源释放前就推回队列导致假死锁
            def requeue():
                # 先等指数退避延迟
                time.sleep(delay)
                # 再等资源释放（如果调用方传了 release_event）
                if release_event is not None:
                    release_event.wait()
                with self._queue_lock:
                    self._task_queue.append(
                        QueuedTask(task_id, task_meta)
                    )  # FIFO 入队到队尾
                logger.info(f"🔄 重试任务: {task_id} | 第{new_retry_count}次 | 延迟{delay}s")

            threading.Thread(target=requeue, daemon=True).start()

            with self._stats_lock:
                self._stats["total_failed"] += 1
        else:
            # 达到最大重试次数，永久失败
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
    
    def _update_task_status(self, task_id: str, status: str, result: Any = None, error: str = None):
        """更新任务状态（内存+日志）"""
        if task_id in self._task_map:
            self._task_map[task_id]["status"] = status
            if result is not None:
                self._task_map[task_id]["result"] = result
            if error is not None:
                self._task_map[task_id]["error_message"] = error
            if status in [TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.TIMEOUT.value]:
                self._task_map[task_id]["completed_at"] = datetime.now().isoformat()
    
    def _update_memory_usage(self, memory_mb: int, delta: bool):
        """更新内存使用统计"""
        with self._memory_lock:
            if delta:
                self._current_memory_mb += memory_mb
            else:
                self._current_memory_mb = max(0, self._current_memory_mb - memory_mb)
    
    def _invoke_callback(self, callback_name: str, task_id: str, result: Any):
        """调用完成回调（集成 CallbackRegistry）"""
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
                logger.info(f"📞 回调触发: {callback_name} | 任务: {task_id} | "
                            f"会话: {conversation_id} | 触发: {triggered} 个")
            else:
                logger.info(f"📞 回调触发: {callback_name} | 任务: {task_id}")
        except Exception as e:
            logger.warning(f"⚠️ 回调触发失败: {e}")
    
    def get_task_status(self, task_id: str) -> Optional[dict]:
        """查询任务状态"""
        if task_id not in self._task_map:
            # 尝试从数据库加载
            from devpartner_agent.core.database import get_db
            db = get_db()
            # v6.0 修复: query_list → query_local（API方法名统一）
            rows = db.query_local("SELECT * FROM task_queue WHERE task_id = ?", (task_id,))
            if rows:
                return dict(rows[0])
            return None
        
        return self._task_map[task_id].copy()
    
    def cancel_task(self, task_id: str) -> bool:
        """取消任务（仅在 pending/queued 状态有效）"""
        task_meta = self._task_map.get(task_id)
        if not task_meta:
            return False
        
        if task_meta["status"] not in [TaskStatus.PENDING.value, TaskStatus.QUEUED.value]:
            logger.warning(f"⚠️ 无法取消非等待状态的任务: {task_id} (当前: {task_meta['status']})")
            return False
        
        self._update_task_status(task_id, TaskStatus.CANCELLED.value)
        
        from devpartner_agent.core.database import get_db
        db = get_db()
        db.query_local("UPDATE task_queue SET status = 'cancelled' WHERE task_id = ?", (task_id,))
        
        with self._stats_lock:
            self._stats["total_cancelled"] += 1
        
        logger.info(f"❌ 任务已取消: {task_id}")
        return True
    
    def get_queue_stats(self) -> dict:
        """获取队列统计信息"""
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
        }
    
    def get_diagnostics(self) -> dict:
        """获取队列诊断信息（用于排查阻塞问题）v6.0"""
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

        conv_locks_status = {}
        with self._conversation_locks_lock:
            for conv_id, lock in self._conversation_locks.items():
                conv_locks_status[conv_id] = {"locked": lock.locked()}

        return {
            "timestamp": datetime.now().isoformat(),
            "scheduler_mode": "FIFO + conversation_mutex (v6.0)",
            "semaphore_value": self._semaphore._value if hasattr(self._semaphore, '_value') else "unknown",
            "active_futures": len(self._futures),
            "pending_in_queue": pending_count,
            "pending_preview": pending_tasks,
            "total_tracked": len(self._task_map),
            "active_conversation_locks": len([l for l in self._conversation_locks.values() if l.locked()]),
            "total_conversation_locks": len(self._conversation_locks),
            "conversation_locks": conv_locks_status,
            "memory": memory_info,
            "status_breakdown": status_count,
            "running_tasks": running_tasks,
            "stats": self._stats.copy()
        }

    def _recover_interrupted_tasks(self):
        """
        v7.0: 启动恢复 — 将上次异常中断卡在 processing/running 的任务重置为 pending。

        场景：进程崩溃/强制重启时，正在执行的任务状态停留在 processing，
        重启后不会被 Worker 消费（Worker 只取 pending），导致任务永久挂起。
        """
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
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
        """
        v7.0: 重试调度线程 — 定时扫描 failed 且已到达重试时间的任务，重置为 pending。

        与 _handle_task_failure 中的即时重试互补：
        - 即时重试：指数退避延迟后直接入队（同一进程内）
        - 调度重试：跨进程重启后，根据 next_retry_at 字段重新调度
        """
        while not self._shutdown_flag:
            try:
                time.sleep(10)  # 每 10 秒扫描一次
                from devpartner_agent.core.database import get_db
                db = get_db()
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
                        # 超过最大重试，标记为 dead
                        db.query_local(
                            "UPDATE task_queue SET status = 'dead', error_message = 'Max retries exceeded' WHERE task_id = ?",
                            (task_id,)
                        )
                        logger.warning(f"💀 任务永久失败: {task_id} | 已达最大重试 {max_retries} 次")
            except Exception as e:
                logger.warning(f"⚠️ 重试调度异常（非致命）: {e}")

    def _auto_cleanup_zombies(self):
        """自动清理僵尸任务 — 在 _worker_loop 中定期调用

        ponytail: 只检查 DB 中 running 状态的任务（不依赖 _task_map，因为进程重启后 _task_map 为空），
        将超时的任务标记为 timeout，释放 semaphore 槽位。
        """
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            rows = db.query_local(
                "SELECT task_id, started_at FROM task_queue WHERE status='running'"
            )
            if not rows:
                return

            now = datetime.now()
            max_age = 600  # 10分钟僵尸阈值
            cleaned = 0
            for row in rows:
                started_at = row.get("started_at")
                if not started_at:
                    continue
                try:
                    started = datetime.fromisoformat(started_at)
                    age_s = (now - started).total_seconds()
                    if age_s > max_age:
                        logger.warning(f"🧹 自动清理僵尸任务: {row['task_id']} | 运行时长: {age_s/3600:.1f}h")
                        db.query_local(
                            "UPDATE task_queue SET status='timeout', error_message=?, completed_at=? WHERE task_id=?",
                            (f"Auto zombie cleanup after {age_s/3600:.1f}h", now.isoformat(), row['task_id'])
                        )
                        cleaned += 1
                except Exception:
                    pass

            if cleaned > 0:
                # 释放被僵尸任务占用的 semaphore 槽位
                self.reset_semaphore_leak()
                logger.info(f"✅ 自动清理完成: {cleaned} 个僵尸任务")
        except Exception as e:
            logger.warning(f"⚠️ 僵尸任务检查失败（非致命）: {e}")

    def _auto_cleanup_orphan_steps(self):
        """
        v7.2: 自动清理孤儿 conversation_steps — 在 _worker_loop 中定期调用。

        状态机兜底策略：
          - pending 超过 24 小时 → 标记为 orphaned（不删除，保留数据）
          - in_progress 超过 10 分钟 → 回退为 pending（允许 Worker 重新拾取）

        ponytail: 只查 DB，不依赖内存状态。
        """
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()
            now = datetime.now()

            # 1. pending 超过 24h → orphaned
            orphaned = db.query_local("""
                UPDATE conversation_steps SET status = 'orphaned', error_message = ?
                WHERE status = 'pending'
                  AND created_at < ?
                  AND created_at IS NOT NULL
            """, (f"Auto orphaned after 24h at {now.isoformat()}", (now - timedelta(hours=24)).isoformat()))
            orphaned_count = orphaned if isinstance(orphaned, int) else (orphaned.rowcount if hasattr(orphaned, 'rowcount') else 0)

            # 2. in_progress 超过 10min → 回退为 pending
            reset = db.query_local("""
                UPDATE conversation_steps SET status = 'pending', error_message = ?
                WHERE status = 'in_progress'
                  AND started_at < ?
                  AND started_at IS NOT NULL
            """, (f"Auto reset from in_progress after 10min at {now.isoformat()}", (now - timedelta(minutes=10)).isoformat()))
            reset_count = reset if isinstance(reset, int) else (reset.rowcount if hasattr(reset, 'rowcount') else 0)

            if orphaned_count > 0 or reset_count > 0:
                logger.info(f"🧹 孤儿步骤清理: {orphaned_count} orphaned, {reset_count} reset → pending")
        except Exception as e:
            logger.warning(f"⚠️ 孤儿步骤检查失败（非致命）: {e}")

    def force_cleanup_zombie_tasks(self, max_age_seconds: int = 300) -> int:
        """强制清理僵尸任务（运行时间超过阈值的 RUNNING 任务）"""
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
                    logger.warning(f"🧹 清理僵尸任务: {task_id} | 运行时长: {age_seconds:.1f}s")

                    self._update_task_status(task_id, TaskStatus.TIMEOUT.value, error=f"Force cleanup after {age_seconds:.1f}s")

                    try:
                        from devpartner_agent.core.database import get_db
                        db = get_db()
                        db.query_local("""
                            UPDATE task_queue SET status = 'timeout', error_message = ?, completed_at = ?
                            WHERE task_id = ?
                        """, (f"Zombie cleanup after {age_seconds:.1f}s", now.isoformat(), task_id))
                    except Exception as e:
                        logger.warning(f"⚠️ 更新僵尸任务状态失败: {e}")

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
        """重置 semaphore 泄漏（根据实际运行任务数调整）"""
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
            logger.warning(f"🔧 检测到 Semaphore 泄漏: {leak_count} 个 | 实际运行: {actual_running} | 当前值: {current_value}")

            for _ in range(leak_count):
                try:
                    self._semaphore.release()
                except ValueError:
                    break

            logger.info(f"✅ 已释放 {leak_count} 个泄漏的信号量")
            return leak_count

        return 0

    def shutdown(self, wait: bool = True):
        """优雅关闭任务队列"""
        logger.info("🛑 正在关闭任务队列...")
        self._shutdown_flag = True

        if wait:
            for future in list(self._futures.values()):
                future.result(timeout=10.0)

        self._executor.shutdown(wait=wait)
        logger.info("✅ 任务队列已关闭")


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_task_queue_instance: Optional[TaskQueue] = None

def get_task_queue() -> TaskQueue:
    """获取全局任务队列单例"""
    global _task_queue_instance
    if _task_queue_instance is None:
        _task_queue_instance = TaskQueue()
    return _task_queue_instance