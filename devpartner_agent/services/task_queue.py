"""
异步任务队列 (v5.0)
==================
管理后台任务的异步执行，支持优先级调度和资源控制。

核心功能：
  - 优先级任务调度（最大堆）
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

使用示例：
    queue = TaskQueue()
    task_id = queue.submit_task("analysis", {"content": "..."}, priority=10)
    status = queue.get_task_status(task_id)
"""
import json
import uuid
import logging
import threading
import time
import heapq
from datetime import datetime
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


@dataclass(order=True)
class PriorityTask:
    """优先级任务包装器（用于堆排序）"""
    priority: int                          # 优先级（负数用于最大堆）
    task_id: str = field(compare=False)     # 任务ID
    task_data: dict = field(compare=False) # 任务数据


class TaskQueue:
    """
    异步任务队列管理器
    
    特性：
      - 基于最大堆的优先级调度
      - Semaphore 并发控制
      - 动态内存监控
      - 超时自动取消
      - 指数退避重试
    
    资源策略：
      - 默认并发数: 2（本地系统保守配置）
      - 最大内存阈值: 1.5GB（为LLM预留空间）
      - 单任务超时: 300秒（5分钟）
      - 最大重试: 3次
    """
    
    _instance: Optional["TaskQueue"] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        
        # ── 核心数据结构 ──
        self._task_heap: List[PriorityTask] = []       # 优先级堆
        self._heap_lock = threading.Lock()              # 堆操作锁
        self._task_map: Dict[str, dict] = {}             # task_id -> 元数据
        self._futures: Dict[str, Future] = {}           # task_id -> Future对象
        
        # ── 并发控制 ──
        self._semaphore: threading.Semaphore = threading.Semaphore(2)  # 默认并发数=2
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=4,                              # 工作线程池大小
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
        logger.info("🔄 异步任务队列已启动")
    
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
            db.query_local("""
                INSERT INTO task_queue (
                    task_id, task_type, payload, status, priority,
                    max_retries, estimated_memory_mb, queued_at, timeout_seconds
                ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            """, (
                task_id, task_type, json.dumps(payload, ensure_ascii=False),
                priority, max_retries, estimated_memory_mb, timestamp, timeout_seconds
            ))
        except Exception as e:
            logger.error(f"❌ 任务持久化失败: {e}")
        
        # 加入内存队列
        with self._heap_lock:
            # 使用负数实现最大堆（heapq默认是最小堆）
            heapq.heappush(self._task_heap, PriorityTask(-priority, task_id, task_meta))
        
        self._task_map[task_id] = task_meta
        
        with self._stats_lock:
            self._stats["total_submitted"] += 1
        
        logger.info(f"📥 提交任务: {task_id} | 类型: {task_type} | 优先级: {priority}")
        return task_id
    
    def _worker_loop(self):
        """工作线程主循环 - 从队列中取任务并执行"""
        while not self._shutdown_flag:
            try:
                # 从堆中取出最高优先级任务
                task = self._acquire_next_task()
                if task is None:
                    time.sleep(0.5)  # 无任务时短暂休眠
                    continue
                
                task_id = task.task_id
                task_meta = task.task_data
                
                # 检查资源是否充足
                if not self._check_resource_availability(task_meta):
                    logger.warning(f"⚠️ 资源不足，任务排队等待: {task_id}")
                    with self._heap_lock:
                        heapq.heappush(self._task_heap, task)  # 重新入队
                    time.sleep(2.0)
                    continue
                
                # 执行任务
                future = self._executor.submit(self._execute_task_wrapper, task_id, task_meta)
                self._futures[task_id] = future
                
            except Exception as e:
                logger.error(f"❌ Worker loop error: {e}", exc_info=True)
                time.sleep(1.0)
    
    def _acquire_next_task(self) -> Optional[PriorityTask]:
        """从堆中获取下一个待执行任务"""
        with self._heap_lock:
            while self._task_heap:
                task = heapq.heappop(self._task_heap)
                task_id = task.task_id
                
                # 检查任务是否已被取消
                if task_id in self._task_map and self._task_map[task_id]["status"] != TaskStatus.CANCELLED.value:
                    return task
            return None
    
    def _check_resource_availability(self, task_meta: dict) -> bool:
        """检查系统资源是否足够执行任务"""
        # 检查并发槽位
        if self._semaphore._value <= 0:  # 非标准用法，仅用于快速检查
            return False
        
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
            
            # 执行实际任务逻辑
            result = self._dispatch_task_execution(task_meta)
            
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
                UPDATE task_queue SET status = 'completed', result = ?, completed_at = ?, progress = 1.0
                WHERE task_id = ?
            """, (json.dumps(result, ensure_ascii=False) if result else None,
                  datetime.now().isoformat(), task_id))
            
            logger.info(f"✅ 任务完成: {task_id} | 耗时: {execution_time:.2f}s")
            
            # 执行回调（如果有）
            callback_name = task_meta.get("callback")
            if callback_name:
                self._invoke_callback(callback_name, task_id, result)
            
        except TimeoutError:
            logger.error(f"⏰ 任务超时: {task_id} (>{task_meta.get('timeout_seconds', 300)}s)")
            self._handle_task_failure(task_id, "Timeout exceeded", db)
            self._update_task_status(task_id, TaskStatus.TIMEOUT.value)
            
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.error(f"❌ 任务执行失败: {task_id} | 错误: {error_msg}", exc_info=True)
            self._handle_task_failure(task_id, error_msg, db)
            
        finally:
            # 释放资源
            self._semaphore.release()
            self._update_memory_usage(task_meta.get("estimated_memory_mb", 100), delta=False)
            
            if task_id in self._futures:
                del self._futures[task_id]
    
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
        if knowledge_points:
            from devpartner_agent.services.conversation_manager import ConversationManager
            mgr = ConversationManager()
            kp_ids = []
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
        
        # 2. 更新步骤状态为已完成（output_data 记录 LLM 分析详情）
        db.query_local("""
            UPDATE conversation_steps SET
                status = 'completed', output_data = ?,
                completed_at = ?, duration_ms = ?
            WHERE step_id = ?
        """, (
            json.dumps(results, ensure_ascii=False),
            datetime.now().isoformat(),
            0,  # 实际耗时由外层计算
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
                        kp_id = mgr._create_knowledge_point(
                            title=node.get("label", node.get("title", "未知节点")),
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
            except Exception as e:
                logger.error(f"系统优化建议生成失败: {e}")
        
        # 5. 标记 conversations 表 analyzed=1 + 存储 LLM 深层分析结果
        llm_deep_result_json = json.dumps({
            "system_issues": results.get("system_issues", []),
            "system_deficiencies": results.get("system_deficiencies", []),
            "user_insights": results.get("user_insights", []),
            "recurring_patterns": results.get("recurring_patterns", []),
            "overall_assessment": results.get("overall_assessment", ""),
            "risk_areas": results.get("risk_areas", []),
            "positive_patterns": results.get("positive_patterns", []),
        }, ensure_ascii=False)
        
        db.query_local("""
            UPDATE conversations SET analyzed = 1, updated_at = ?,
                actions = CASE WHEN actions IS NULL OR actions = '' 
                    THEN ? ELSE actions || ' | LLM_DEEP: ' || ? END
            WHERE conversation_id = ?
        """, (
            datetime.now().isoformat(),
            f"LLM深层分析: {results.get('overall_assessment', '')[:500]}",
            f"系统问题={len(results.get('system_issues', []))}个, 不足={len(results.get('system_deficiencies', []))}个, 风险={len(results.get('risk_areas', []))}个",
            conversation_id
        ))
        
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
    
    def _handle_task_failure(self, task_id: str, error_msg: str, db):
        """处理任务失败（重试或标记失败）"""
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
            
            # 更新数据库
            db.query_local("""
                UPDATE task_queue SET
                    status = 'pending', retry_count = ?, error_message = ?
                WHERE task_id = ?
            """, (new_retry_count, error_msg, task_id))
            
            # 重新入队（延迟后）
            def requeue():
                time.sleep(delay)
                with self._heap_lock:
                    heapq.heappush(
                        self._task_heap,
                        PriorityTask(-task_meta["priority"], task_id, task_meta)
                    )
                logger.info(f"🔄 重试任务: {task_id} | 第{new_retry_count}次 | 延迟{delay}s")
            
            threading.Thread(target=requeue, daemon=True).start()
            
            with self._stats_lock:
                self._stats["total_failed"] += 1
        else:
            # 达到最大重试次数，永久失败
            self._update_task_status(task_id, TaskStatus.FAILED.value, error=error_msg)
            db.query_local("""
                UPDATE task_queue SET status = 'failed', error_message = ?, completed_at = ?
                WHERE task_id = ?
            """, (error_msg, datetime.now().isoformat(), task_id))
            
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
    
    def shutdown(self, wait: bool = True):
        """优雅关闭任务队列"""
        logger.info("🛑 正在关闭任务队列...")
        self._shutdown_flag = True
        
        if wait:
            # 等待运行中的任务完成
            for future in list(self._futures.values()):
                future.result(timeout=10.0)
        
        self._executor.shutdown(wait=wait)
        logger.info("✅ 任务队列已关闭")


def get_task_queue() -> TaskQueue:
    """获取全局任务队列单例"""
    return TaskQueue()