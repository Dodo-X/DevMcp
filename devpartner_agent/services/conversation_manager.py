"""
会话管理器 (v7.0)
==================
管理对话的完整生命周期，基于总分总架构。

核心功能：
  - 唯一 conversation_id 生成（UUID v4）
  - 状态机管理（active → completed/failed/paused）
  - record_step 即时记录 + 后台异步分析
  - 知识点有序落地（knowledge_points）
  - 内存占用监控

使用示例：
    mgr = ConversationManager()
    conv_id = mgr.create_conversation(client="codebuddy", topic="重构数据库")
    mgr.record_step(conv_id, "分析现状", step_type="design", content="...")
    mgr.finalize_conversation(conv_id, summary="...")
"""
import json
import uuid
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ConversationStatus(str, Enum):
    """会话状态枚举"""
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StepStatus(str, Enum):
    """步骤状态枚举"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepType(str, Enum):
    """步骤类型枚举"""
    ANALYSIS = "analysis"                    # 对话内容分析
    KNOWLEDGE_GEN = "knowledge_gen"           # 知识点生成
    USER_PROFILE = "user_profile"             # 用户画像更新
    SYSTEM_OPTIMIZE = "system_optimize"       # 系统优化建议
    DATA_MIGRATION = "data_migration"         # 数据迁移
    VALIDATION = "validation"                 # 数据校验


@dataclass
class StepConfig:
    """步骤配置"""
    step_type: StepType
    step_name: str
    order: int
    input_data: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)  # 依赖的step_id列表
    max_retries: int = 3
    timeout_seconds: int = 300
    estimated_memory_mb: int = 100  # 预估内存占用（MB）
    priority: int = 0


class ConversationManager:
    """
    对话生命周期管理器
    
    职责：
      1. 创建和管理会话（唯一ID + 状态跟踪）
      2. 拆分复杂任务为可执行的步骤
      3. 协调异步执行顺序和依赖关系
      4. 记录知识点到知识库
      5. 监控资源使用情况
    
    设计原则：
      - 单例模式，线程安全
      - 支持异步非阻塞操作
      - 内存友好（本地系统限制）
      - 失败重试机制
    """
    
    def __init__(self):
        self._active_conversations: Dict[str, dict] = {}  # conversation_id -> metadata
        self._memory_usage_mb: float = 0.0
        self._max_memory_mb: float = 2048.0  # 默认最大内存限制（2GB）
        self._concurrency_limit: int = 3       # 并发任务数限制
        self._running_tasks: int = 0
        self._task_lock = threading.Lock()
    
    def generate_conversation_id(self) -> str:
        """生成唯一的会话ID（UUID v4 格式）"""
        return f"conv_{uuid.uuid4().hex[:16]}"
    
    def generate_step_id(self, conversation_id: str, order: int) -> str:
        """生成步骤ID"""
        return f"{conversation_id}_step_{order:03d}"
    
    def create_conversation(
        self,
        client: str = "unknown",
        topic: str = "",
        task_type: str = "general",
        user_intent: str = "",
        priority: str = "medium",
        **kwargs
    ) -> str:
        """
        创建新会话
        
        Args:
            client: 客户端标识（codebuddy/trae/cursor等）
            topic: 对话主题
            task_type: 任务类型
            user_intent: 用户意图描述
            priority: 优先级（low/medium/high/critical）
            **kwargs: 其他字段
        
        Returns:
            conversation_id (str): 唯一会话标识符
        """
        conv_id = self.generate_conversation_id()
        timestamp = datetime.now().isoformat()
        
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        try:
            db.query_local("""
                INSERT INTO conversations (
                    conversation_id, timestamp, client, topic, task_type,
                    user_intent, status, priority, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
            """, (
                conv_id, timestamp, client, topic, task_type,
                user_intent, priority, timestamp, timestamp
            ))
            
            logger.info(f"✅ 创建会话成功: {conv_id} | 客户端: {client} | 主题: {topic}")
            
            # 缓存活跃会话元数据
            self._active_conversations[conv_id] = {
                "id": conv_id,
                "client": client,
                "topic": topic,
                "status": ConversationStatus.ACTIVE.value,
                "created_at": timestamp,
                "steps_count": 0,
                "completed_steps": 0,
            }
            
            return conv_id
            
        except Exception as e:
            logger.error(f"❌ 创建会话失败: {e}", exc_info=True)
            raise RuntimeError(f"Failed to create conversation: {e}")
    
    def ensure_conversation_exists(
        self,
        conversation_id: str,
        client: str = "codebuddy",
        topic: str = "自动创建的会话",
        task_type: str = "general",
    ) -> bool:
        """
        确保指定 conversation_id 的会话在 DB 中存在（record_step 的 FK 自保护）。

        背景：create_conversation 与 record_step 是两次独立的 MCP 请求，
        共享同一个 WAL 连接的读快照时，刚创建的会话可能尚未对 record_step 可见，
        导致 conversation_steps 的 FK 校验失败。本方法在写步骤前补齐父行，
        使 record_step 不依赖请求间的可见性时序。

        Returns:
            True 表示该会话原本就存在 / 已成功补齐；False 表示补齐失败。
        """
        if not conversation_id:
            return False
        from devpartner_agent.core.database import get_db
        db = get_db()
        try:
            row = db.query_local(
                "SELECT id FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            if row:
                return True

            ts = datetime.now().isoformat()
            db.query_local(
                """
                INSERT INTO conversations (
                    conversation_id, timestamp, client, topic, task_type,
                    status, priority, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', 'medium', ?, ?)
                """,
                (conversation_id, ts, client, topic, task_type, ts, ts),
            )
            logger.info(f"✅ ensure_conversation_exists: 补齐会话 {conversation_id}")
            return True
        except Exception as e:
            logger.error(f"❌ ensure_conversation_exists 失败: {e}")
            return False

    def create_steps(
        self,
        conversation_id: str,
        step_configs: List[StepConfig]
    ) -> List[str]:
        """
        为会话创建执行步骤
        
        Args:
            conversation_id: 会话ID
            step_configs: 步骤配置列表
        
        Returns:
            step_ids: 生成的步骤ID列表
        """
        if not self._validate_conversation(conversation_id):
            raise ValueError(f"Invalid conversation_id: {conversation_id}")
        
        step_ids = []
        from devpartner_agent.core.database import get_db
        db = get_db()

        # v7.0: 获取 conversations.id 用于 FK 关联
        conv_row = db.query_local(
            "SELECT id FROM conversations WHERE conversation_id = ?",
            (conversation_id,)
        )
        conversations_id = conv_row[0]["id"] if conv_row else None

        for config in step_configs:
            step_id = self.generate_step_id(conversation_id, config.order)

            db.query_local("""
                INSERT INTO conversation_steps (
                    step_id, conversation_id, conversations_id, step_order, step_type,
                    step_name, status, input_data, max_retries,
                    timeout_seconds, priority, depends_on, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
            """, (
                step_id, conversation_id, conversations_id, config.order, config.step_type.value,
                config.step_name, json.dumps(config.input_data, ensure_ascii=False),
                config.max_retries, config.timeout_seconds, config.priority,
                ",".join(config.depends_on), datetime.now().isoformat()
            ))
            
            step_ids.append(step_id)
            logger.info(f"📋 创建步骤: {step_id} ({config.step_name})")
        
        # 更新会话的总步骤数
        db.query_local("""
            UPDATE conversations SET total_steps = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (len(step_ids), datetime.now().isoformat(), conversation_id))
        
        if conversation_id in self._active_conversations:
            self._active_conversations[conversation_id]["steps_count"] = len(step_ids)
        
        return step_ids
    

    def execute_single_step(
        self,
        step_id: str,
        force_retry: bool = False
    ) -> Dict[str, Any]:
        """
        执行单个步骤（同步或异步）
        
        Args:
            step_id: 步骤ID
            force_retry: 强制重试（忽略状态检查）
        
        Returns:
            执行结果字典
        """
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        # 查询步骤信息
        steps = db.query_local("SELECT * FROM conversation_steps WHERE step_id = ?", (step_id,))
        if not steps:
            raise ValueError(f"Step not found: {step_id}")
        
        step = steps[0]
        current_status = step["status"]
        
        # 状态校验
        if current_status == StepStatus.COMPLETED.value and not force_retry:
            return {"status": "already_completed", "step_id": step_id}
        
        if current_status == StepStatus.RUNNING.value and not force_retry:
            return {"status": "already_running", "step_id": step_id}
        
        # 更新状态为运行中
        start_time = datetime.now()
        db.query_local("""
            UPDATE conversation_steps SET status = 'running', started_at = ?
            WHERE step_id = ?
        """, (start_time.isoformat(), step_id))
        
        try:
            # 根据步骤类型分发执行
            result = self._dispatch_step_execution(step)
            
            # 更新执行结果
            end_time = datetime.now()
            duration_ms = int((end_time - start_time).total_seconds() * 1000)
            
            knowledge_ids = result.get("knowledge_point_ids", [])
            
            db.query_local("""
                UPDATE conversation_steps SET
                    status = 'completed', output_data = ?, error_message = NULL,
                    knowledge_point_ids = ?, completed_at = ?, duration_ms = ?, retry_count = 0
                WHERE step_id = ?
            """, (
                json.dumps(result.get("output", {}), ensure_ascii=False),
                ",".join(knowledge_ids) if knowledge_ids else None,
                end_time.isoformat(), duration_ms, step_id
            ))
            
            # 更新会话已完成步骤数
            conv_id = step["conversation_id"]
            self._update_completed_steps(conv_id)
            
            logger.info(f"✅ 步骤执行成功: {step_id} | 耗时: {duration_ms}ms")
            
            return {
                "status": "success",
                "step_id": step_id,
                "duration_ms": duration_ms,
                "output": result.get("output", {}),
                "knowledge_points_created": len(knowledge_ids),
            }
            
        except Exception as e:
            # 错误处理与重试逻辑
            logger.error(f"❌ 步骤执行失败: {step_id} | 错误: {e}", exc_info=True)
            
            new_retry_count = step["retry_count"] + 1
            max_retries = step["max_retries"]
            
            if new_retry_count < max_retries:
                # 标记为待重试
                db.query_local("""
                    UPDATE conversation_steps SET
                        status = 'pending', error_message = ?, retry_count = ?
                    WHERE step_id = ?
                """, (str(e), new_retry_count, step_id))
                
                return {
                    "status": "retry_scheduled",
                    "step_id": step_id,
                    "retry_count": new_retry_count,
                    "max_retries": max_retries,
                    "error": str(e),
                }
            else:
                # 达到最大重试次数，标记为失败
                db.query_local("""
                    UPDATE conversation_steps SET
                        status = 'failed', error_message = ?, completed_at = ?
                    WHERE step_id = ?
                """, (str(e), datetime.now().isoformat(), step_id))
                
                return {
                    "status": "failed",
                    "step_id": step_id,
                    "error": str(e),
                    "retried": new_retry_count,
                }
    
    def _dispatch_step_execution(self, step: dict) -> Dict[str, Any]:
        """
        根据步骤类型分发执行逻辑
        
        Args:
            step: 步骤数据字典
        
        Returns:
            包含 output 和 knowledge_point_ids 的字典
        """
        step_type = step["step_type"]
        input_data = json.loads(step["input_data"]) if step["input_data"] else {}
        
        result = {"output": {}, "knowledge_point_ids": []}
        
        if step_type == StepType.ANALYSIS.value:
            # 对话内容分析（调用 LLM）
            result = self._execute_analysis_step(step, input_data)
        elif step_type == StepType.KNOWLEDGE_GEN.value:
            # 知识点生成
            result = self._execute_knowledge_generation_step(step, input_data)
        elif step_type == StepType.USER_PROFILE.value:
            # 用户画像更新
            result = self._execute_user_profile_step(step, input_data)
        elif step_type == StepType.SYSTEM_OPTIMIZE.value:
            # 系统优化建议
            result = self._execute_system_optimize_step(step, input_data)
        else:
            raise ValueError(f"Unknown step type: {step_type}")
        
        return result
    
    def _execute_analysis_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行对话分析步骤"""
        from devpartner_agent.services.llm_service import LLMService
        llm = LLMService()
        
        content = input_data.get("content", "")
        source = input_data.get("source", "unknown")
        client = input_data.get("client", "unknown")
        
        analysis_result = llm.analyze_conversation(content, source, client)
        
        if analysis_result:
            return {
                "output": analysis_result,
                "knowledge_point_ids": [],  # 分析本身不直接生成知识点
            }
        else:
            raise RuntimeError("LLM analysis failed or returned empty result")
    
    def _execute_knowledge_generation_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行知识点生成步骤"""
        analysis_output = input_data.get("analysis_output", {})
        skill_domains = analysis_output.get("skill_domains", [])
        knowledge_ids = []
        
        for domain_info in skill_domains:
            domain = domain_info.get("domain", "General")
            sub_skills = domain_info.get("sub_skills", [])
            
            for skill in sub_skills:
                kp_id = self._create_knowledge_point(
                    title=f"[{domain}] {skill}",
                    content=f"技能点: {skill}\n领域: {domain}\n来源: 自动提取\n时间: {datetime.now().isoformat()}",
                    category="skill",
                    domain=domain,
                    tags=[domain, skill],
                    source_type="step",
                    source_id=step["step_id"],
                )
                if kp_id:
                    knowledge_ids.append(kp_id)
        
        return {
            "output": {"knowledge_generated": len(knowledge_ids)},
            "knowledge_point_ids": knowledge_ids,
        }
    
    def _execute_user_profile_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行用户画像更新步骤"""
        analysis_output = input_data.get("analysis_output", {})
        user_traits = analysis_output.get("user_traits", {})
        
        # 更新 user_skills 表
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        skills_observed = user_traits.get("skills_observed", [])
        for skill in skills_observed:
            db.query_local("""
                INSERT OR IGNORE INTO user_skills (
                    timestamp, skill_domain, skill_level, sub_skills,
                    evidence, last_updated
                ) VALUES (?, 'intermediate', ?, ?, ?)
            """, (
                datetime.now().isoformat(),
                skill,
                json.dumps([skill], ensure_ascii=False),
                f"自动检测自会话 {step['conversation_id']}",
                datetime.now().isoformat(),
            ))
        
        return {
            "output": {"traits_extracted": len(skills_observed)},
            "knowledge_point_ids": [],
        }
    
    def _execute_system_optimize_step(self, step: dict, input_data: dict) -> Dict[str, Any]:
        """执行系统优化建议步骤"""
        from devpartner_agent.services.llm_service import LLMService
        llm = LLMService()
        
        system_data = input_data.get("system_data", {})
        suggestions = llm.generate_self_improvement_suggestions(system_data)
        
        if suggestions:
            # 写入 improvement_log
            from devpartner_agent.core.database import get_db
            db = get_db()
            
            for suggestion in suggestions:
                db.query_local("""
                    INSERT INTO improvement_log (
                        timestamp, category, suggestion, priority,
                        status, conversations_id
                    ) VALUES (?, ?, ?, ?, 'pending',
                        (SELECT id FROM conversations WHERE conversation_id = ?)
                    )
                """, (
                    datetime.now().isoformat(),
                    suggestion.get("category", "general"),
                    suggestion.get("suggestion", ""),
                    suggestion.get("priority", "medium"),
                    step["conversation_id"],
                ))
            
            return {
                "output": {"suggestions_generated": len(suggestions)},
                "knowledge_point_ids": [],
            }
        else:
            return {"output": {"suggestions_generated": 0}, "knowledge_point_ids": []}
    
    def _create_knowledge_point(
        self,
        title: str,
        content: str,
        category: str,
        domain: str,
        tags: list,
        source_type: str = "system",
        source_id: str = ""
    ) -> Optional[str]:
        """创建知识点记录"""
        # v7.2: source_type 断言，确保 source_id 格式统一
        assert source_type in ('step', 'finalize', 'manual', 'knowledge_graph', 'system', 'business_extraction'), \
            f"Unknown source_type: {source_type}"

        from devpartner_agent.core.database import get_db
        db = get_db()
        
        try:
            kp_id = f"kp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            
            db.query_local("""
                INSERT INTO knowledge_points (
                    knowledge_id, title, content, category, domain,
                    tags, source_type, source_id, confidence, difficulty,
                    created_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0.8, 'medium', 'system', ?, ?)
            """, (
                kp_id, title, content, category, domain,
                json.dumps(tags, ensure_ascii=False),
                source_type, source_id,
                datetime.now().isoformat(), datetime.now().isoformat()
            ))
            
            logger.info(f"💡 创建知识点: {kp_id} | {title}")
            return kp_id
            
        except Exception as e:
            logger.error(f"❌ 创建知识点失败: {e}", exc_info=True)
            return None
    
    def _update_completed_steps(self, conversation_id: str):
        """更新会话的已完成步骤计数"""
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        completed = db.query_local("""
            SELECT COUNT(*) as cnt FROM conversation_steps
            WHERE conversation_id = ? AND status = 'completed'
        """, (conversation_id,))[0]["cnt"]
        
        total = db.query_local("""
            SELECT COUNT(*) as cnt FROM conversation_steps
            WHERE conversation_id = ?
        """, (conversation_id,))[0]["cnt"]
        
        db.query_local("""
            UPDATE conversations SET
                completed_steps = ?, total_steps = ?, updated_at = ?
            WHERE conversation_id = ?
        """, (completed, total, datetime.now().isoformat(), conversation_id))
        
        # 检查是否所有步骤都已完成
        if completed >= total and total > 0:
            self.complete_conversation(conversation_id)
        
        if conversation_id in self._active_conversations:
            self._active_conversations[conversation_id]["completed_steps"] = completed
    
    def complete_conversation(self, conversation_id: str):
        """标记会话为已完成"""
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        db.query_local("""
            UPDATE conversations SET
                status = 'completed', completed_at = ?, updated_at = ?
            WHERE conversation_id = ? AND status != 'completed'
        """, (datetime.now().isoformat(), datetime.now().isoformat(), conversation_id))
        
        if conversation_id in self._active_conversations:
            self._active_conversations[conversation_id]["status"] = ConversationStatus.COMPLETED.value
        
        # 释放并发槽位
        with self._task_lock:
            self._running_tasks = max(0, self._running_tasks - 1)
        
        logger.info(f"🎉 会话完成: {conversation_id}")
    
    def fail_conversation(self, conversation_id: str, error: str = "Unknown error"):
        """标记会话为失败"""
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        db.query_local("""
            UPDATE conversations SET
                status = 'failed', updated_at = ?, self_reflection = ?
            WHERE conversation_id = ? AND status NOT IN ('completed', 'failed')
        """, (datetime.now().isoformat(), error, conversation_id))
        
        if conversation_id in self._active_conversations:
            self._active_conversations[conversation_id]["status"] = ConversationStatus.FAILED.value
        
        with self._task_lock:
            self._running_tasks = max(0, self._running_tasks - 1)
        
        logger.error(f"❌ 会话失败: {conversation_id} | 原因: {error}")
    
    def get_conversation_status(self, conversation_id: str) -> Optional[dict]:
        """获取会话详细状态"""
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        conv = db.query_local("SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,))
        if not conv:
            return None
        
        steps = db.query_local("""
            SELECT * FROM conversation_steps WHERE conversation_id = ? ORDER BY step_order ASC
        """, (conversation_id,))
        
        return {
            "conversation": dict(conv[0]),
            "steps": [dict(s) for s in steps],
            "progress": {
                "total": conv[0]["total_steps"],
                "completed": conv[0]["completed_steps"],
                "percentage": round(conv[0]["completed_steps"] / max(1, conv[0]["total_steps"]) * 100, 1),
            },
        }
    
    def _validate_conversation(self, conversation_id: str) -> bool:
        """验证会话ID有效性"""
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        result = db.query_local(
            "SELECT id FROM conversations WHERE conversation_id = ? AND status = 'active'",
            (conversation_id,)
        )
        return len(result) > 0
    
    def _estimate_memory_for_conversation(self, conversation_id: str) -> int:
        """估算处理某个会话所需的内存（MB）"""
        # 基础开销 + 步骤数 × 平均每步内存
        base_memory = 50  # 50MB 基础开销
        per_step_memory = 150  # 每个步骤平均 150MB（LLM推理）
        
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        rows = db.query_local("""
            SELECT COUNT(*) as cnt FROM conversation_steps WHERE conversation_id = ?
        """, (conversation_id,))
        steps_count = rows[0]["cnt"] if rows else 0
        
        estimated = base_memory + (steps_count * per_step_memory)
        return min(estimated, 1024)  # 上限 1GB
    
    def get_system_health(self) -> dict:
        """获取系统健康状态"""
        return {
            "active_conversations": len(self._active_conversations),
            "running_tasks": self._running_tasks,
            "concurrency_limit": self._concurrency_limit,
            "estimated_memory_usage_mb": round(self._memory_usage_mb, 2),
            "max_memory_limit_mb": self._max_memory_mb,
            "memory_utilization_percent": round(
                (self._memory_usage_mb / max(1, self._max_memory_mb)) * 100, 1
            ),
        }


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_conversation_manager_instance: Optional[ConversationManager] = None

def get_conversation_manager() -> ConversationManager:
    """获取全局会话管理器单例"""
    global _conversation_manager_instance
    if _conversation_manager_instance is None:
        _conversation_manager_instance = ConversationManager()
    return _conversation_manager_instance