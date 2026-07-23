"""
对话引擎子包 (v9.10.1)
=====================
分层重构，解耦 DB/数据构造/埋点/业务逻辑。

模块：
  - constants: 全局常量（截断、优先级、状态、SQL、表名）
  - types: 扩展类型定义（dataclass）
  - dao: ConversationDAO 纯 DB 操作层
  - builder: DataBuilder 统一构造 step_input / task_payload / 上下文
  - tracker: 埋点工具（写入追踪、耗时、日志包装）
  - engine: ConversationEngine 核心编排（对外 API）
  - handlers: 任务处理器独立文件
"""

from backend.business.conversation_mgr.engine import (
    ConversationEngine,
    get_conversation_engine,
    register_task_handlers,
)

__all__ = [
    "ConversationEngine",
    "get_conversation_engine",
    "register_task_handlers",
]
