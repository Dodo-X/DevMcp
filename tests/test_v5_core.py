"""
DevPartner v5.2 单元测试 - 会话管理器
"""
import unittest
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
_project_root = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_project_root))


class TestConversationManager(unittest.TestCase):
    """测试会话管理器的核心功能"""

    @classmethod
    def setUpClass(cls):
        """初始化数据库连接"""
        from devpartner_agent.core.database import get_db
        db_path = str(_project_root / "data" / "databases" / "devpartner.db")
        db = get_db()
        if not db._local_conn:
            db.init_local(db_path)
        cls.db = db

    def setUp(self):
        """每个测试前创建新的会话管理器实例"""
        from devpartner_agent.services.conversation_manager import get_conversation_manager
        self.mgr = get_conversation_manager()

    def test_01_singleton(self):
        """测试单例模式"""
        from devpartner_agent.services.conversation_manager import ConversationManager
        mgr1 = ConversationManager()
        mgr2 = ConversationManager()
        self.assertIs(mgr1, mgr2)

    def test_02_generate_id(self):
        """测试 ID 生成"""
        conv_id = self.mgr.generate_conversation_id()
        self.assertTrue(conv_id.startswith("conv_"))
        self.assertEqual(len(conv_id), 21)  # conv_ + 16 hex chars

        step_id = self.mgr.generate_step_id(conv_id, 3)
        self.assertTrue(step_id.startswith(conv_id))
        self.assertTrue(step_id.endswith("003"))

    def test_03_create_conversation(self):
        """测试创建会话"""
        conv_id = self.mgr.create_conversation(
            client="test_client",
            topic="单元测试会话",
            task_type="testing",
            priority="high",
        )
        self.assertIsNotNone(conv_id)
        self.assertTrue(conv_id.startswith("conv_"))

        # 验证状态
        status = self.mgr.get_conversation_status(conv_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["conversation"]["status"], "active")

        # 清理
        self.db.query_local(
            "DELETE FROM conversations WHERE conversation_id = ?", (conv_id,))

    def test_04_create_steps(self):
        """测试创建步骤"""
        from devpartner_agent.services.conversation_manager import StepConfig, StepType

        conv_id = self.mgr.create_conversation(
            client="test", topic="步骤测试", task_type="testing")

        configs = [
            StepConfig(step_type=StepType.ANALYSIS, step_name="分析", order=1),
            StepConfig(step_type=StepType.KNOWLEDGE_GEN, step_name="知识提取", order=2),
            StepConfig(step_type=StepType.VALIDATION, step_name="验证", order=3),
        ]

        step_ids = self.mgr.create_steps(conv_id, configs)
        self.assertEqual(len(step_ids), 3)

        # 验证步骤顺序
        status = self.mgr.get_conversation_status(conv_id)
        self.assertEqual(status["conversation"]["total_steps"], 3)
        self.assertEqual(len(status["steps"]), 3)

        # 清理
        self.db.query_local(
            "DELETE FROM conversation_steps WHERE conversation_id = ?", (conv_id,))
        self.db.query_local(
            "DELETE FROM conversations WHERE conversation_id = ?", (conv_id,))

    def test_05_invalid_conversation(self):
        """测试无效会话ID"""
        status = self.mgr.get_conversation_status("conv_nonexistent")
        self.assertIsNone(status)

    def test_06_system_health(self):
        """测试系统健康检查"""
        health = self.mgr.get_system_health()
        self.assertIn("active_conversations", health)
        self.assertIn("running_tasks", health)
        self.assertIn("concurrency_limit", health)
        self.assertIn("memory_utilization_percent", health)


class TestTaskQueue(unittest.TestCase):
    """测试异步任务队列"""

    @classmethod
    def setUpClass(cls):
        """初始化数据库连接"""
        from devpartner_agent.core.database import get_db
        db_path = str(_project_root / "data" / "databases" / "devpartner.db")
        db = get_db()
        if not db._local_conn:
            db.init_local(db_path)
        cls.db = db

    def setUp(self):
        from devpartner_agent.services.task_queue import get_task_queue
        self.queue = get_task_queue()

    def test_01_singleton(self):
        """测试单例模式"""
        from devpartner_agent.services.task_queue import TaskQueue
        q1 = TaskQueue()
        q2 = TaskQueue()
        self.assertIs(q1, q2)

    def test_02_submit_task(self):
        """测试提交任务"""
        task_id = self.queue.submit_task(
            task_type="test_task",
            payload={"key": "value"},
            priority=5,
        )
        self.assertIsNotNone(task_id)
        self.assertTrue(task_id.startswith("task_"))

    def test_03_get_task_status(self):
        """测试查询任务状态"""
        task_id = self.queue.submit_task(
            task_type="test_task",
            payload={"key": "value"},
        )
        status = self.queue.get_task_status(task_id)
        self.assertIsNotNone(status)
        self.assertEqual(status["task_id"], task_id)
        self.assertEqual(status["task_type"], "test_task")

    def test_04_cancel_task(self):
        """测试取消任务"""
        task_id = self.queue.submit_task(
            task_type="test_task",
            payload={"key": "value"},
        )
        success = self.queue.cancel_task(task_id)
        self.assertTrue(success)

        status = self.queue.get_task_status(task_id)
        self.assertEqual(status["status"], "cancelled")

    def test_05_queue_stats(self):
        """测试队列统计"""
        stats = self.queue.get_queue_stats()
        self.assertIn("pending_tasks", stats)
        self.assertIn("running_tasks", stats)
        self.assertIn("memory_usage_mb", stats)
        self.assertIn("utilization_percent", stats)

    def test_06_nonexistent_task(self):
        """测试不存在的任务"""
        status = self.queue.get_task_status("task_nonexistent")
        self.assertIsNone(status)


class TestCallbackRegistry(unittest.TestCase):
    """测试回调注册表"""

    def setUp(self):
        from devpartner_agent.services.callback_registry import get_callback_registry
        self.registry = get_callback_registry()
        self._progress_values = []
        self._complete_values = []
        self._error_values = []

    def test_01_register(self):
        """测试注册回调"""
        reg_id = self.registry.register(
            conversation_id="test_conv_001",
            on_progress=lambda p, m: None,
        )
        self.assertTrue(reg_id.startswith("cb_"))

        info = self.registry.get_registration(reg_id)
        self.assertIsNotNone(info)
        self.assertEqual(info["conversation_id"], "test_conv_001")
        self.assertTrue(info["has_progress"])

        # 清理
        self.registry.unregister(reg_id)

    def test_02_trigger_progress(self):
        """测试触发进度回调"""
        progress_values = []

        reg_id = self.registry.register(
            conversation_id="test_conv_002",
            on_progress=lambda p, m: progress_values.append((p, m)),
        )

        triggered = self.registry.trigger_progress(
            "test_conv_002", 50.0, "处理中...")
        self.assertEqual(triggered, 1)
        self.assertEqual(len(progress_values), 1)
        self.assertEqual(progress_values[0], (50.0, "处理中..."))

        self.registry.unregister(reg_id)

    def test_03_trigger_complete(self):
        """测试触发完成回调"""
        complete_values = []

        reg_id = self.registry.register(
            conversation_id="test_conv_003",
            on_complete=lambda r: complete_values.append(r),
        )

        result = {"status": "success", "data": "test"}
        triggered = self.registry.trigger_complete("test_conv_003", result)
        self.assertEqual(triggered, 1)
        self.assertEqual(len(complete_values), 1)
        self.assertEqual(complete_values[0]["status"], "success")

        self.registry.unregister(reg_id)

    def test_04_trigger_error(self):
        """测试触发错误回调"""
        error_values = []

        reg_id = self.registry.register(
            conversation_id="test_conv_004",
            on_error=lambda e: error_values.append(e),
        )

        triggered = self.registry.trigger_error("test_conv_004", "测试错误")
        self.assertEqual(triggered, 1)
        self.assertEqual(len(error_values), 1)
        self.assertEqual(error_values[0], "测试错误")

        self.registry.unregister(reg_id)

    def test_05_unregister(self):
        """测试取消注册"""
        reg_id = self.registry.register(
            conversation_id="test_conv_005",
            on_complete=lambda r: None,
        )
        self.assertTrue(self.registry.unregister(reg_id))
        self.assertIsNone(self.registry.get_registration(reg_id))

    def test_06_multiple_registrations(self):
        """测试同一会话的多个注册"""
        values = []

        reg1 = self.registry.register(
            conversation_id="test_conv_006",
            on_complete=lambda r: values.append("reg1"),
        )
        reg2 = self.registry.register(
            conversation_id="test_conv_006",
            on_complete=lambda r: values.append("reg2"),
        )

        triggered = self.registry.trigger_complete("test_conv_006", {})
        self.assertEqual(triggered, 2)
        self.assertEqual(len(values), 2)
        self.assertIn("reg1", values)
        self.assertIn("reg2", values)

        self.registry.unregister(reg1)
        self.registry.unregister(reg2)

    def test_07_stats(self):
        """测试统计信息"""
        stats = self.registry.get_stats()
        self.assertIn("active_registrations", stats)
        self.assertIn("total_registered", stats)
        self.assertIn("total_triggered", stats)
        self.assertIn("total_cleaned", stats)

    def test_08_callback_error_isolation(self):
        """测试回调异常隔离——一个回调失败不影响其他回调"""
        values = []

        def failing_callback(result):
            raise RuntimeError("故意的错误")

        reg1 = self.registry.register(
            conversation_id="test_conv_008",
            on_complete=failing_callback,
        )
        reg2 = self.registry.register(
            conversation_id="test_conv_008",
            on_complete=lambda r: values.append("ok"),
        )

        # 这不应抛出异常
        triggered = self.registry.trigger_complete("test_conv_008", {})
        self.assertEqual(triggered, 1)  # reg2 仍然被触发
        self.assertEqual(values, ["ok"])

        self.registry.unregister(reg1)
        self.registry.unregister(reg2)


class TestDatabaseV5(unittest.TestCase):
    """测试 v5.0 数据库表结构"""

    @classmethod
    def setUpClass(cls):
        from devpartner_agent.core.database import get_db
        db_path = str(_project_root / "data" / "databases" / "devpartner.db")
        db = get_db()
        if not db._local_conn:
            db.init_local(db_path)
        cls.db = db

    def test_01_new_tables_exist(self):
        """测试 v5.0 新表是否存在"""
        cursor = self.db._local_conn.cursor()
        for table in ["conversation_steps", "knowledge_points", "task_queue"]:
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            self.assertIsNotNone(cursor.fetchone(),
                                 f"表 {table} 不存在！数据库迁移可能未完成。")

    def test_02_conversations_columns(self):
        """测试 conversations 表 v5.0 字段"""
        cursor = self.db._local_conn.cursor()
        cursor.execute("PRAGMA table_info(conversations)")
        columns = [row[1] for row in cursor.fetchall()]
        for col in ["status", "priority", "total_steps", "completed_steps",
                     "created_at", "updated_at"]:
            self.assertIn(col, columns, f"conversations 表缺少字段: {col}")

    def test_03_knowledge_points_structure(self):
        """测试 knowledge_points 表结构"""
        cursor = self.db._local_conn.cursor()
        cursor.execute("PRAGMA table_info(knowledge_points)")
        columns = [row[1] for row in cursor.fetchall()]
        essential = ["knowledge_id", "title", "content", "category",
                      "domain", "confidence", "version"]
        for col in essential:
            self.assertIn(col, columns, f"knowledge_points 表缺少字段: {col}")

    def test_04_task_queue_structure(self):
        """测试 task_queue 表结构"""
        cursor = self.db._local_conn.cursor()
        cursor.execute("PRAGMA table_info(task_queue)")
        columns = [row[1] for row in cursor.fetchall()]
        essential = ["task_id", "task_type", "payload", "status",
                      "priority", "progress", "timeout_seconds"]
        for col in essential:
            self.assertIn(col, columns, f"task_queue 表缺少字段: {col}")

    def test_05_create_and_query_knowledge(self):
        """测试知识点的创建和查询"""
        import uuid
        kp_id = f"kp_test_{uuid.uuid4().hex[:8]}"

        self.db.query_local("""
            INSERT INTO knowledge_points
            (knowledge_id, title, content, category, domain, tags, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (kp_id, "测试知识点", "测试内容", "skill", "Testing",
              '["test", "unittest"]', 0.9))

        result = self.db.query_local(
            "SELECT * FROM knowledge_points WHERE knowledge_id = ?", (kp_id,))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "测试知识点")

        # 清理
        self.db.query_local(
            "DELETE FROM knowledge_points WHERE knowledge_id = ?", (kp_id,))


if __name__ == "__main__":
    # 允许直接运行
    unittest.main(verbosity=2)