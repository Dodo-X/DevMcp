#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用户画像定时汇总调度器 v6.0
============================
功能：
1. 每日自动触发画像摘要生成
2. 每周自动生成成长路线图
3. 支持手动触发全量分析

设计原则：
- 使用 threading + time.sleep 实现轻量级定时（避免额外依赖 schedule 库）
- 守护线程模式，不阻塞主进程
- 异常隔离：单次失败不影响后续执行
"""

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class ProfileScheduler:
    """
    用户画像定时汇总调度器
    
    调度策略：
    - 每天 23:00 触发每日画像摘要（daily_summary）
    - 每周一 09:00 触发每周成长路线图（weekly_roadmap）
    - 支持手动调用 trigger_analysis(scope="full")
    """

    _instance: Optional["ProfileScheduler"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        
        self._initialized = True
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_daily_run: Optional[str] = None
        self._last_weekly_run: Optional[str] = None

    def start(self):
        """启动定时调度器（守护线程模式）"""
        if self._running:
            logger.warning("⚠️ 定时调度器已在运行中")
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        
        logger.info("✅ 用户画像定时调度器已启动 (守护线程)")

    def stop(self):
        """停止调度器"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("⏹️ 定时调度器已停止")

    def _run_loop(self):
        """主循环：每分钟检查一次是否需要触发任务"""
        logger.debug("🔄 定时调度器主循环启动")
        
        while self._running:
            try:
                now = datetime.now()
                
                # 检查每日任务 (23:00 - 23:05 窗口期)
                if now.hour == 23 and now.minute == 0:
                    today_str = now.strftime("%Y-%m-%d")
                    if self._last_daily_run != today_str:
                        self._execute_daily_summary(now)
                        self._last_daily_run = today_str
                
                # 检查每周任务 (周一 09:00 - 09:10 窗口期)
                if now.weekday() == 0 and now.hour == 9 and now.minute == 0:
                    week_str = now.strftime("%Y-W%W")  # ISO 周编号
                    if self._last_weekly_run != week_str:
                        self._execute_weekly_roadmap(now)
                        self._last_weekly_run = week_str
                
            except Exception as e:
                logger.error(f"❌ 定时调度器循环异常: {e}", exc_info=True)
            
            # 休眠 60 秒再检查
            time.sleep(60)

    def _execute_daily_summary(self, trigger_time: datetime):
        """
        执行每日画像摘要生成
        
        收集今日所有对话，LLM 生成摘要，存入 learning_observations 表
        """
        logger.info(f"📊 开始执行每日画像摘要 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")
        
        try:
            from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
            from devpartner_agent.core.database import get_db
            
            analyzer = get_unified_analyzer()
            db = get_db()
            
            # 收集今日对话数据
            today_start = trigger_time.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_end = trigger_time.isoformat()
            
            daily_data = db.get_daily_work_data(today_start, today_end)
            
            if not daily_data or not daily_data.get("conversations"):
                logger.info("ℹ️ 今日无对话数据，跳过每日摘要")
                return
            
            # LLM 生成每日画像摘要
            summary = analyzer.generate_profile_summary(
                scope="daily",
                data=daily_data,
                date=trigger_time.strftime("%Y-%m-%d")
            )
            
            if summary:
                # 存储到数据库（使用 dimensions JSON 字段）
                db.insert_improvement_with_dimensions(
                    category="daily_profile_summary",
                    dimensions={
                        "summary_type": "daily",
                        "date": trigger_time.strftime("%Y-%m-%d"),
                        "total_conversations": len(daily_data.get("conversations", [])),
                        "key_findings": summary.get("key_findings", []),
                        "skills_updated": summary.get("skills_updated", []),
                        "growth_indicators": summary.get("growth_indicators", {}),
                        "generated_by": "scheduler_daily",
                    },
                    priority="low",
                )
                
                logger.info(f"✅ 每日画像摘要完成: {len(daily_data.get('conversations', []))} 条对话")
                
            else:
                logger.warning("⚠️ LLM 未能生成有效摘要")
                
        except Exception as e:
            logger.error(f"❌ 每日画像摘要执行失败: {e}", exc_info=True)

    def _execute_weekly_roadmap(self, trigger_time: datetime):
        """
        执行每周成长路线图生成
        
        汇总一周内所有对话，生成阶段性技能评估和学习建议
        """
        logger.info(f"🗺️ 开始执行每周成长路线图 [{trigger_time.strftime('%Y-%m-%d %H:%M')}]")
        
        try:
            from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
            from devpartner_agent.core.database import get_db
            
            analyzer = get_unified_analyzer()
            db = get_db()
            
            # 计算本周时间范围（周一到当前时间）
            week_start = trigger_time - timedelta(days=trigger_time.weekday())
            week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
            
            week_data = {
                "period_start": week_start.isoformat(),
                "period_end": trigger_time.isoformat(),
                "conversations": db.get_conversations_in_range(week_start.isoformat(), trigger_time.isoformat()),
                "skills_snapshot": db.query_all_user_skills(),
            }
            
            if not week_data.get("conversations"):
                logger.info("ℹ️ 本周无对话数据，跳过周报生成")
                return
            
            # LLM 生成成长路线图
            roadmap = analyzer.generate_growth_roadmap(
                scope="weekly",
                data=week_data,
                period_start=week_start.strftime("%Y-%m-%d"),
                period_end=trigger_time.strftime("%Y-%m-%d")
            )
            
            if roadmap:
                # 存储周报到数据库
                db.insert_improvement_with_dimensions(
                    category="weekly_growth_roadmap",
                    dimensions={
                        "summary_type": "weekly",
                        "period_start": week_start.strftime("%Y-%m-%d"),
                        "period_end": trigger_time.strftime("%Y-%m-%d"),
                        "total_conversations": len(week_data.get("conversations", [])),
                        "roadmap": roadmap.get("roadmap", []),
                        "milestones_achieved": roadmap.get("milestones_achieved", []),
                        "next_week_goals": roadmap.get("next_week_goals", []),
                        "skill_progression": roadmap.get("skill_progression", {}),
                        "recommendations": roadmap.get("recommendations", []),
                        "generated_by": "scheduler_weekly",
                    },
                    priority="medium",
                )
                
                logger.info(f"✅ 每周成长路线图已生成: {len(week_data.get('conversations', []))} 条对话")
                
            else:
                logger.warning("⚠️ LLM 未能生成有效的成长路线图")
                
        except Exception as e:
            logger.error(f"❌ 每周成长路线图执行失败: {e}", exc_info=True)

    def trigger_manual_analysis(self, scope: str = "full") -> dict:
        """
        手动触发全量分析（供外部调用）
        
        Args:
            scope: 分析范围 ("full" / "recent" / "daily" / "weekly")
            
        Returns:
            分析结果字典
        """
        logger.info(f"🎯 手动触发分析 [scope={scope}]")
        
        try:
            from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
            from devpartner_agent.services.user_profile_service import request_user_profile_analysis
            
            analyzer = get_unified_analyzer()
            
            # 构建分析请求数据
            profile_request = request_user_profile_analysis(
                analysis_scope=scope,
                client_context={"trigger": "manual_scheduler"},
            )
            
            result = {
                "status": "success",
                "scope": scope,
                "triggered_at": datetime.now().isoformat(),
                "request_id": f"manual_{datetime.now().strftime('%Y%m%d%H%M%S')}",
                "profile_request": {
                    "analysis_scope": scope,
                    "data_points": len(profile_request.get("recent_data", [])),
                    "has_few_shot_examples": bool(profile_request.get("few_shot_examples")),
                },
            }
            
            logger.info(f"✅ 手动分析请求已准备完成 [{result['request_id']}]")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 手动分析触发失败: {e}", exc_info=True)
            return {
                "status": "error",
                "scope": scope,
                "error": str(e),
                "triggered_at": datetime.now().isoformat(),
            }

    @property
    def is_running(self) -> bool:
        """检查调度器是否在运行"""
        return self._running and self._thread and self._thread.is_alive()

    @property
    def status(self) -> dict:
        """获取调度器状态信息"""
        return {
            "running": self.is_running,
            "last_daily_run": self._last_daily_run,
            "last_weekly_run": self._last_weekly_run,
            "thread_alive": self._thread.is_alive() if self._thread else False,
            "current_time": datetime.now().isoformat(),
        }


def get_scheduler() -> ProfileScheduler:
    """获取全局调度器单例"""
    return ProfileScheduler()


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 测试 ProfileScheduler")
    print("=" * 60)
    
    scheduler = get_scheduler()
    
    print("\n📋 调度器状态:")
    print(f"运行状态: {scheduler.is_running}")
    print(f"状态详情: {scheduler.status}")
    
    print("\n🎯 测试手动触发:")
    result = scheduler.trigger_manual_analysis(scope="recent")
    print(json.dumps(result, indent=2, ensure_ascii=False))