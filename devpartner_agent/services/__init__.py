"""DevPartner Agent Services - 无状态服务层 (v8.3)

有效文件：
  - cleanup_service.py    ← 数据生命周期管理（清理+调度+完整性）
  - task_queue.py         ← 异步任务队列
  - knowledge_extractor.py← 知识提取
  - vault_exporter.py     ← Obsidian 导出（单向：SQLite → MD）
  - optimization_loop.py  ← 优化闭环引擎
  - callback_registry.py  ← 回调注册
"""

from .cleanup_service import (
    CleanupService, get_cleanup_service,
    CleanupScheduler, get_cleanup_scheduler,
    WriteTracker, get_write_tracker,
    log_write_result, check_and_log_integrity,
)
from .task_queue import get_task_queue, TaskQueue
from .callback_registry import get_callback_registry, CallbackRegistry
from .optimization_loop import get_optimization_loop, OptimizationLoop