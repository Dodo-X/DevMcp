"""
DevPartner Growth Analytics Tools
双向成长分析工具集 - 提供 Dashboard 所需的聚合数据

包含 5 个核心工具：
  1. get_user_growth_overview     - 用户成长总览（技能数、掌握率、学习效率等）
  2. get_system_evolution_stats   - 系统进化统计（自迭代次数、引擎分布、采纳率）
  3. get_user_skill_radar         - 用户技能六维雷达图数据
  4. get_learning_timeline        - 融合时间线（用户+系统事件交织）
  5. get_user_activity_heatmap    - 用户学习热力图（近4周活动强度）

设计原则：
  - 聚合计算：从多个表提取并计算衍生指标
  - 性能优化：使用 SQL 聚合函数减少数据传输
  - 缓存友好：返回结构化 JSON，适合前端缓存
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path


def get_user_growth_overview() -> str:
    """
    获取用户成长总览数据
    
    返回字段：
      - total_skills: 总技能数
      - avg_mastery: 平均掌握率 (0-100)
      - this_week_new: 本周新增技能数
      - streak_days: 连续学习天数
      - learning_efficiency: 学习效率 (0-1)
      - top_domain: 当前最专注领域
      - skills_by_domain: 各领域技能分布
    
    数据来源：
      - user_skills 表：技能列表和掌握度
      - conversations 表：学习活动记录
      - improvement_log 表：改进记录
    """
    try:
        from devpartner_agent.core.database import DatabaseManager
        
        db = DatabaseManager()
        
        # 1. 总技能数和平均掌握度
        skills_result = db.execute_query("""
            SELECT 
                COUNT(*) as total_skills,
                AVG(mastery_level) as avg_mastery,
                MAX(updated_at) as last_updated
            FROM user_skills
            WHERE is_active = 1
        """)
        
        total_skills = skills_result[0]['total_skills'] if skills_result else 0
        avg_mastery = round(skills_result[0]['avg_mastery'], 1) if skills_result and skills_result[0]['avg_mastery'] else 0
        
        # 2. 本周新增技能（7天内）
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        new_skills_result = db.execute_query("""
            SELECT COUNT(*) as new_count
            FROM user_skills
            WHERE created_at >= ?
        """, (week_ago,))
        this_week_new = new_skills_result[0]['new_count'] if new_skills_result else 0
        
        # 3. 连续学习天数（基于conversations表）
        streak_days = _calculate_learning_streak(db)
        
        # 4. 学习效率（最近30天 vs 前30天的技能增长比率）
        learning_efficiency = _calculate_learning_efficiency(db)
        
        # 5. 当前最专注领域
        top_domain_result = db.execute_query("""
            SELECT domain, COUNT(*) as cnt
            FROM user_skills
            WHERE is_active = 1
            GROUP BY domain
            ORDER BY cnt DESC
            LIMIT 1
        """)
        top_domain = top_domain_result[0]['domain'] if top_domain_result else '未分类'
        
        # 6. 各领域技能分布
        domain_dist_result = db.execute_query("""
            SELECT domain, COUNT(*) as count, AVG(mastery_level) as avg_mastery
            FROM user_skills
            WHERE is_active = 1
            GROUP BY domain
            ORDER BY count DESC
        """)
        skills_by_domain = [
            {
                'domain': row['domain'] or '其他',
                'count': row['count'],
                'avg_mastery': round(row['avg_mastery'], 1) if row['avg_mastery'] else 0
            }
            for row in domain_dist_result
        ] if domain_dist_result else []
        
        result = {
            'total_skills': total_skills,
            'avg_mastery': avg_mastery,
            'this_week_new': this_week_new,
            'streak_days': streak_days,
            'learning_efficiency': learning_efficiency,
            'top_domain': top_domain,
            'skills_by_domain': skills_by_domain,
            'last_updated': datetime.now().isoformat(),
            'status': 'success'
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': f'获取用户成长数据失败: {str(e)}',
            'total_skills': 0,
            'avg_mastery': 0,
            'this_week_new': 0,
            'streak_days': 0,
            'learning_efficiency': 0,
            'top_domain': '错误',
            'skills_by_domain': []
        }, ensure_ascii=False, indent=2)


def get_system_evolution_stats() -> str:
    """
    获取系统进化统计数据
    
    返回字段：
      - total_iterations: 自我迭代总次数
      - recent_changes: 最近变更记录（最新5条）
      - llm_call_ratio: LLM调用占比 (0-100)
      - rules_engine_ratio: 规则引擎占比 (0-100)
      - knowledge_growth_rate: 知识库月增长率 (%)
      - suggestion_adoption_rate: 优化建议采纳率 (%)
      - last_iteration_time: 最后一次迭代时间
    
    数据来源：
      - evolution_log 表：系统变更记录
      - improvement_log 表：改进日志
      - conversations 表：LLM调用记录
    """
    try:
        from devpartner_agent.core.database import DatabaseManager
        
        db = DatabaseManager()
        
        # 1. 自我迭代总次数（evolution_log 记录数）
        iterations_result = db.execute_query("""
            SELECT COUNT(*) as total,
                   MAX(timestamp) as last_time
            FROM evolution_log
            WHERE success = 1
        """)
        total_iterations = iterations_result[0]['total'] if iterations_result else 0
        last_iteration_time = iterations_result[0]['last_time'] if iterations_result and iterations_result[0]['last_time'] else None
        
        # 2. 最近变更记录（最新5条）
        recent_changes_result = db.execute_query("""
            SELECT 
                id,
                version,
                change_type,
                description,
                timestamp,
                success
            FROM evolution_log
            ORDER BY timestamp DESC
            LIMIT 5
        """)
        recent_changes = [
            {
                'id': row['id'],
                'version': row['version'],
                'change_type': row['change_type'],
                'description': row['description'],
                'timestamp': row['timestamp'],
                'success': bool(row['success'])
            }
            for row in recent_changes_result
        ] if recent_changes_result else []
        
        # 3. LLM vs 规则引擎调用占比（基于conversations表的分析标记）
        llm_stats_result = db.execute_query("""
            SELECT 
                SUM(CASE WHEN analyzed = 1 THEN 1 ELSE 0 END) as llm_calls,
                COUNT(*) as total_calls
            FROM conversations
            WHERE created_at >= datetime('now', '-30 days')
        """)
        total_calls = llm_stats_result[0]['total_calls'] if llm_stats_result else 0
        llm_calls = llm_stats_result[0]['llm_calls'] if llm_stats_result else 0
        
        if total_calls > 0:
            llm_call_ratio = round((llm_calls / total_calls) * 100, 1)
            rules_engine_ratio = round(100 - llm_call_ratio, 1)
        else:
            llm_call_ratio = 50.0
            rules_engine_ratio = 50.0
        
        # 4. 知识库月增长率（user_skills 的月度增长）
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()
        current_skills = db.execute_query("SELECT COUNT(*) as cnt FROM user_skills WHERE is_active = 1")[0]['cnt']
        past_skills_result = db.execute_query("""
            SELECT COUNT(*) as cnt 
            FROM user_skills 
            WHERE created_at < ? AND is_active = 1
        """, (month_ago,))
        past_skills = past_skills_result[0]['cnt'] if past_skills_result else 0
        
        if past_skills > 0:
            knowledge_growth_rate = round(((current_skills - past_skills) / past_skills) * 100, 1)
        else:
            knowledge_growth_rate = 100.0 if current_skills > 0 else 0.0
        
        # 5. 优化建议采纳率（optimization_feedback 中 status='adopted' 的比例）
        adoption_result = db.execute_query("""
            SELECT 
                SUM(CASE WHEN status = 'adopted' THEN 1 ELSE 0 END) as adopted,
                COUNT(*) as total
            FROM optimization_feedback
            WHERE created_at >= datetime('now', '-90 days')
        """)
        total_suggestions = adoption_result[0]['total'] if adoption_result else 0
        adopted = adoption_result[0]['adopted'] if adoption_result else 0
        
        suggestion_adoption_rate = round((adopted / total_suggestions) * 100, 1) if total_suggestions > 0 else 0.0
        
        result = {
            'total_iterations': total_iterations,
            'recent_changes': recent_changes,
            'llm_call_ratio': llm_call_ratio,
            'rules_engine_ratio': rules_engine_ratio,
            'knowledge_growth_rate': knowledge_growth_rate,
            'suggestion_adoption_rate': suggestion_adoption_rate,
            'last_iteration_time': last_iteration_time,
            'pending_suggestions': max(0, total_suggestions - adopted),
            'last_updated': datetime.now().isoformat(),
            'status': 'success'
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': f'获取系统进化数据失败: {str(e)}',
            'total_iterations': 0,
            'recent_changes': [],
            'llm_call_ratio': 50.0,
            'rules_engine_ratio': 50.0,
            'knowledge_growth_rate': 0.0,
            'suggestion_adoption_rate': 0.0,
            'pending_suggestions': 0
        }, ensure_ascii=False, indent=2)


def get_user_skill_radar() -> str:
    """
    获取用户技能六维雷达图数据
    
    返回6个维度的当前掌握度和30天前对比：
      - frontend: 前端开发
      - backend: 后端开发
      - database: 数据库
      - devops: DevOps
      - algorithm: 算法设计
      - ai_ml: AI/机器学习
    
    每个维度评分范围 0-100
    
    数据来源：
      - user_skills 表：按 domain 分组计算平均 mastery_level
    """
    try:
        from devpartner_agent.core.database import DatabaseManager
        
        db = DatabaseManager()
        
        # 定义6个维度及其对应的 domain 映射
        dimension_map = {
            'frontend': ['前端', 'Frontend', 'React', 'Vue', 'JavaScript', 'TypeScript', 'HTML', 'CSS'],
            'backend': ['后端', 'Backend', 'Python', 'Java', 'Go', 'Node.js', 'API', '微服务'],
            'database': ['数据库', 'Database', 'SQL', 'MySQL', 'PostgreSQL', 'Redis', 'MongoDB'],
            'devops': ['DevOps', '运维', 'Docker', 'Kubernetes', 'CI/CD', 'Linux', 'Nginx'],
            'algorithm': ['算法', 'Algorithm', '数据结构', 'LeetCode', '排序', '搜索'],
            'ai_ml': ['AI', 'ML', '机器学习', '深度学习', 'NLP', 'PyTorch', 'TensorFlow', 'LLM']
        }
        
        # 当前时间
        now = datetime.now()
        thirty_days_ago = (now - timedelta(days=30)).isoformat()
        
        radar_data = {'current': [], 'thirty_days_ago': [], 'labels': []}
        
        for dim_name, keywords in dimension_map.items():
            # 构建SQL查询：匹配域名的模糊查询
            conditions = ' OR '.join([f"domain LIKE ?" for _ in keywords])
            params = [f'%{kw}%' for kw in keywords]
            
            # 当前掌握度
            current_result = db.execute_query(f"""
                SELECT AVG(mastery_level) as avg_mastery
                FROM user_skills
                WHERE is_active = 1 AND ({conditions})
            """, params)
            current_score = round(current_result[0]['avg_mastery'], 1) if current_result and current_result[0]['avg_mastery'] else 0
            
            # 30天前的掌握度
            historical_result = db.execute_query(f"""
                SELECT AVG(mastery_level) as avg_mastery
                FROM user_skills
                WHERE ({conditions}) AND updated_at < ?
            """, params + [thirty_days_ago])
            historical_score = round(historical_result[0]['avg_mastery'], 1) if historical_result and historical_result[0]['avg_mastery'] else 0
            
            # 维度显示名称
            label_map = {
                'frontend': '前端开发',
                'backend': '后端开发',
                'database': '数据库',
                'devops': 'DevOps',
                'algorithm': '算法设计',
                'ai_ml': 'AI/ML'
            }
            
            radar_data['current'].append(current_score)
            radar_data['thirty_days_ago'].append(historical_score)
            radar_data['labels'].append(label_map.get(dim_name, dim_name))
        
        result = {
            'dimensions': radar_data['labels'],
            'current_scores': radar_data['current'],
            'thirty_days_ago_scores': radar_data['thirty_days_ago'],
            'overall_avg_current': round(sum(radar_data['current']) / len(radar_data['current']), 1),
            'overall_avg_past': round(sum(radar_data['thirty_days_ago']) / len(radar_data['thirty_days_ago']), 1),
            'improvement_vector': [
                round(c - p, 1) for c, p in zip(radar_data['current'], radar_data['thirty_days_ago'])
            ],
            'last_updated': datetime.now().isoformat(),
            'status': 'success'
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': f'获取技能雷达数据失败: {str(e)}',
            'dimensions': ['前端开发', '后端开发', '数据库', 'DevOps', '算法设计', 'AI/ML'],
            'current_scores': [0, 0, 0, 0, 0, 0],
            'thirty_days_ago_scores': [0, 0, 0, 0, 0, 0],
            'overall_avg_current': 0,
            'overall_avg_past': 0
        }, ensure_ascii=False, indent=2)


def get_learning_timeline(limit: int = 20) -> str:
    """
    获取融合时间线数据（用户事件 + 系统事件交织）
    
    参数：
      limit: 返回的事件数量限制（默认20条）
    
    事件类型：
      - user: 用户事件（新增技能、技能提升、对话讨论）
      - system: 系统事件（自我迭代、规则更新、知识库优化）
    
    每条事件包含：
      - time: 时间戳
      - type: 事件类型 ('user' | 'system')
      - icon: 图标emoji
      - content: 事件描述
      - skill/impact: 相关技能或影响（可选）
      - delta: 变化量（可选，如 "+12%"）
    
    数据来源：
      - user_skills: 技能创建/更新
      - conversations: 对话活动
      - evolution_log: 系统进化
      - improvement_log: 改进记录
    """
    try:
        from devpartner_agent.core.database import DatabaseManager
        
        db = DatabaseManager()
        events = []
        
        # 1. 用户事件：最近的技能创建（新技能学习）
        new_skills = db.execute_query("""
            SELECT 
                skill_name,
                domain,
                mastery_level,
                created_at as time,
                'user' as type,
                '🧑' as icon
            FROM user_skills
            WHERE is_active = 1
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit // 2,))
        
        for skill in new_skills:
            events.append({
                'time': skill['time'],
                'type': 'user',
                'icon': '🧑',
                'content': f"学习了 {skill['skill_name']} ({skill['domain'] or '通用'})",
                'skill': skill['skill_name'],
                'delta': f"+{skill['mastery_level'] or 0}%"
            })
        
        # 2. 系统事件：最近的进化记录
        evolutions = db.execute_query("""
            SELECT 
                description,
                change_type,
                version,
                timestamp as time,
                'system' as type,
                '🤖' as icon
            FROM evolution_log
            WHERE success = 1
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit // 2,))
        
        for evo in evolutions:
            impact_text = ""
            if evo['change_type'] == 'optimization':
                impact_text = "性能优化"
            elif evo['change_type'] == 'feature':
                impact_text = "功能增强"
            elif evo['change_type'] == 'bugfix':
                impact_text = "Bug修复"
            elif evo['change_type'] == 'refactor':
                impact_text = "代码重构"
            
            events.append({
                'time': evo['time'],
                'type': 'system',
                'icon': '🤖',
                'content': f"{evo['description'][:50]}{'...' if len(evo['description']) > 50 else ''}",
                'impact': f"{impact_text} (v{evo['version']})" if impact_text else f"v{evo['version']}"
            })
        
        # 3. 按时间排序（最新的在前）
        events.sort(key=lambda x: x['time'], reverse=True)
        
        # 4. 截取指定数量
        events = events[:limit]
        
        result = {
            'events': events,
            'total_events': len(events),
            'user_event_count': sum(1 for e in events if e['type'] == 'user'),
            'system_event_count': sum(1 for e in events if e['type'] == 'system'),
            'time_range': {
                'latest': events[0]['time'] if events else None,
                'oldest': events[-1]['time'] if events else None
            },
            'last_updated': datetime.now().isoformat(),
            'status': 'success'
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': f'获取时间线数据失败: {str(e)}',
            'events': [],
            'total_events': 0
        }, ensure_ascii=False, indent=2)


def get_user_activity_heatmap() -> str:
    """
    获取用户学习热力图数据（近4周每天的活动强度）
    
    返回格式：
      - dates: 日期数组 (YYYY-MM-DD 格式)
      - values: 活动强度数组 (0-10)
      - labels: 周几标签 ['日', '一', '二', ..., '六']
    
    活动强度计算依据：
      - 当天新增技能数 (权重: 3)
      - 当天对话轮数 (权重: 2)
      - 当天技能提升次数 (权重: 1)
    
    归一化到 0-10 范围
    
    数据来源：
      - user_skills: 技能创建/更新时间
      - conversations: 对话时间戳
    """
    try:
        from devpartner_agent.core.database import DatabaseManager
        
        db = DatabaseManager()
        
        # 计算28天（4周）的数据
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=28)
        
        heatmap_data = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = current_date.isoformat()
            next_day = (current_date + timedelta(days=1)).isoformat()
            
            # 当天新增技能数
            new_skills = db.execute_query("""
                SELECT COUNT(*) as cnt
                FROM user_skills
                WHERE created_at >= ? AND created_at < ?
            """, (date_str, next_day))
            skill_count = new_skills[0]['cnt'] if new_skills else 0
            
            # 当天对话数
            convs = db.execute_query("""
                SELECT COUNT(*) as cnt
                FROM conversations
                WHERE created_at >= ? AND created_at < ?
            """, (date_str, next_day))
            conv_count = convs[0]['cnt'] if convs else 0
            
            # 当天技能更新数（排除新建）
            updates = db.execute_query("""
                SELECT COUNT(*) as cnt
                FROM user_skills
                WHERE updated_at >= ? AND updated_at < ? 
                AND created_at < ?
            """, (date_str, next_day, date_str))
            update_count = updates[0]['cnt'] if updates else 0
            
            # 计算原始强度分数
            raw_intensity = (skill_count * 3) + (conv_count * 2) + (update_count * 1)
            
            # 归一化到 0-10 （假设最大可能值约为15）
            intensity = min(10, raw_intensity * 2 / 3)  # 简单归一化
            
            heatmap_data.append({
                'date': date_str,
                'day_of_week': current_date.weekday(),  # 0=周一, 6=周日
                'value': round(intensity, 1),
                'breakdown': {
                    'new_skills': skill_count,
                    'conversations': conv_count,
                    'skill_updates': update_count
                }
            })
            
            current_date += timedelta(days=1)
        
        # 提取用于图表的数据
        dates = [d['date'] for d in heatmap_data]
        values = [d['value'] for d in heatmap_data]
        
        result = {
            'dates': dates,
            'values': values,
            'labels': ['一', '二', '三', '四', '五', '六', '日'],
            'period': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
                'days': 28
            },
            'statistics': {
                'max_intensity': max(values) if values else 0,
                'min_intensity': min(values) if values else 0,
                'avg_intensity': round(sum(values) / len(values), 1) if values else 0,
                'active_days': sum(1 for v in values if v > 0),
                'peak_days': sorted(heatmap_data, key=lambda x: x['value'], reverse=True)[:3]
            },
            'detailed_data': heatmap_data,
            'last_updated': datetime.now().isoformat(),
            'status': 'success'
        }
        
        return json.dumps(result, ensure_ascii=False, indent=2)
    
    except Exception as e:
        return json.dumps({
            'status': 'error',
            'message': f'获取热力图数据失败: {str(e)}',
            'dates': [],
            'values': [],
            'labels': ['一', '二', '三', '四', '五', '六', '日']
        }, ensure_ascii=False, indent=2)


# ============================================================
# 辅助函数
# ============================================================

def _calculate_learning_streak(db) -> int:
    """计算连续学习天数"""
    try:
        result = db.execute_query("""
            SELECT DISTINCT DATE(created_at) as activity_date
            FROM conversations
            WHERE created_at >= datetime('now', '-90 days')
            ORDER BY activity_date DESC
        """)
        
        if not result:
            return 0
        
        dates = [row['activity_date'] for row in result]
        streak = 0
        today = datetime.now().date()
        
        for i, date_str in enumerate(dates):
            activity_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            expected_date = today - timedelta(days=i)
            
            if activity_date == expected_date:
                streak += 1
            else:
                break
        
        return streak
    
    except Exception:
        return 0


def _calculate_learning_efficiency(db) -> float:
    """计算学习效率（近30天 vs 前30天的技能增长率）"""
    try:
        now = datetime.now()
        recent_start = (now - timedelta(days=30)).isoformat()
        older_start = (now - timedelta(days=60)).isoformat()
        
        # 近30天的新增/提升技能数
        recent = db.execute_query("""
            SELECT COUNT(*) as cnt
            FROM user_skills
            WHERE (created_at >= ? OR updated_at >= ?)
              AND is_active = 1
        """, (recent_start, recent_start))
        recent_count = recent[0]['cnt'] if recent else 0
        
        # 前30天的数据
        older = db.execute_query("""
            SELECT COUNT(*) as cnt
            FROM user_skills
            WHERE (created_at >= ? AND created_at < ?)
              OR (updated_at >= ? AND updated_at < ?)
        """, (older_start, recent_start, older_start, recent_start))
        older_count = older[0]['cnt'] if older else 0
        
        if older_count > 0:
            efficiency = min(1.0, recent_count / (older_count * 2))  # 归一化到0-1
            return round(efficiency, 2)
        else:
            return 0.5 if recent_count > 0 else 0.0
    
    except Exception:
        return 0.0