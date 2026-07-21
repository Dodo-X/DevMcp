"""DevPartner Agent Services - 无状态服务层 (v8.3)

有效文件：
  - cleanup_service.py    ← 数据生命周期管理（清理+调度+完整性）
  - task_queue.py         ← 异步任务队列
  - knowledge_extractor.py← 知识提取
  - vault_exporter.py     ← Obsidian 导出（单向：SQLite → MD）
  - callback_registry.py  ← 回调注册

外部调用直接 from .xxx import，__init__.py 不提供包级导出。
"""