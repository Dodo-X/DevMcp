"""
DevPartner Tools - 纯工具包

  📈 growth_analytics   — 成长分析 (5个: get_user_growth_overview, get_system_evolution_stats, get_user_skill_radar, get_learning_timeline, get_user_activity_heatmap)

设计原则：
  - 无状态：函数不持有内部状态，每次调用独立
  - 无副作用：所有函数只读
  - 即用即弃：输入 → 处理 → 输出

v9.5: filesystem/web_requests/system_utils 已移除（与 CodeBuddy 原生工具重复）。
"""