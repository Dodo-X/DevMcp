"""
优化闭环引擎 (v3.0.0)
======================
月报触发：汇总已审核的优化反馈 → 生成新的 Prompt 优化。

仅保留：
  - generate_optimization_report: 汇总待处理反馈
  - apply_optimization: 标记已处理
"""

import json
from datetime import datetime
from typing import Optional


class OptimizationLoop:
    """优化闭环引擎"""

    def __init__(self):
        pass

    # ── 批量分析：从数据库中的待处理反馈生成优化报告 ──

    def generate_optimization_report(self) -> dict:
        """
        生成优化报告：汇总所有待处理的反馈，给出优先级排序的建议。
        """
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            pending = db.get_pending_optimizations(limit=50)
            skill_summary = db.get_skill_summary()
            domain_stats = db.get_domain_stats()

            # 按类型分组
            by_type: dict[str, list] = {}
            for item in pending:
                ft = item.get("feedback_type", "unknown")
                if ft not in by_type:
                    by_type[ft] = []
                by_type[ft].append(item)

            # 生成建议
            suggestions = []
            for ft, items in by_type.items():
                if ft == "prompt_optimize":
                    suggestions.append({
                        "priority": "high",
                        "category": "Prompt 优化",
                        "detail": f"检测到 {len(items)} 条 Prompt 优化建议",
                        "action": "审核建议，手动更新 Prompt 模板",
                    })
                elif ft == "analysis_add":
                    suggestions.append({
                        "priority": "medium",
                        "category": "新增分析",
                        "detail": f"建议新增 {len(items)} 个分析维度",
                        "action": "审核后添加新的分析方向",
                    })

            # 技能画像摘要
            skill_insights = []
            for ds in domain_stats:
                skill_insights.append({
                    "domain": ds["skill_domain"],
                    "total_hours": ds.get("total_hours", 0) or 0,
                    "conversation_count": ds.get("cnt", 0),
                })

            return {
                "timestamp": datetime.now().isoformat(),
                "pending_optimizations": len(pending),
                "by_type": {k: len(v) for k, v in by_type.items()},
                "suggestions": suggestions,
                "skill_summary": skill_summary,
                "domain_stats": skill_insights,
            }

        except Exception as e:
            return {"error": str(e)}

    def apply_optimization(self, feedback_id: int) -> dict:
        """应用指定的优化（标记已处理）"""
        try:
            from devpartner_agent.core.database import get_db
            db = get_db()

            # 获取反馈详情
            rows = db.query_local(
                "SELECT * FROM optimization_feedback WHERE id = ?", (feedback_id,)
            )
            if not rows:
                return {"success": False, "error": f"反馈 ID {feedback_id} 不存在"}
            feedback = rows[0]
            fb_type = feedback.get("feedback_type", "")

            # 根据类型执行不同的优化动作
            result_msg = f"已标记优化 {feedback_id} 已处理"

            if fb_type == "prompt_optimize":
                result_msg += "，请手动更新 Prompt 模板"
            elif fb_type == "analysis_add":
                result_msg += "，请手动添加分析"

            db.mark_optimization_applied(feedback_id, result_msg)
            return {"success": True, "message": result_msg}
        except Exception as e:
            return {"success": False, "error": str(e)}


# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入
_optimization_loop_instance: Optional[OptimizationLoop] = None

def get_optimization_loop() -> OptimizationLoop:
    global _optimization_loop_instance
    if _optimization_loop_instance is None:
        _optimization_loop_instance = OptimizationLoop()
    return _optimization_loop_instance


# ══════════════════════════════════════════════════════════
# Task Handler 注册（v8.1）
# ══════════════════════════════════════════════════════════

def handle_optimization_report(payload: dict) -> dict:
    """异步生成优化报告"""
    loop = get_optimization_loop()
    return loop.generate_optimization_report()


def handle_optimization_apply(payload: dict) -> dict:
    """异步应用优化"""
    loop = get_optimization_loop()
    return loop.apply_optimization(payload.get("feedback_id", 0))


def register_task_handlers():
    """注册优化任务处理器到 task_queue"""
    from devpartner_agent.services.task_queue import get_task_queue
    queue = get_task_queue()
    queue.register_handler("optimization_report", handle_optimization_report)
    queue.register_handler("optimization_apply", handle_optimization_apply)
    print("优化任务处理器已注册 (2个handler)")