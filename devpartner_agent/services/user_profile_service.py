#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用户画像服务 v6.0 (LLM 驱动)
============================
v6.0 重构说明：
- ✅ 废弃所有硬编码字段映射逻辑
- ✅ 统一委托给 LLMUnifiedAnalyzer.apply_user_traits()
- ✅ 代码量从 141行 → ~50行（减少 65%）
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def apply_user_traits(traits: dict, source: str = "unknown",
                     conversation_id: Optional[int] = None) -> dict:
    """
    将用户特征融合到 MCP 数据层（兼容旧接口）
    
    Args:
        traits: 用户特征字典（来自 LLM 分析结果）
        source: 来源标识
        conversation_id: 对话 ID
        
    Returns:
        操作统计：{"skills": N, "improvements": N, ...}
    """
    if not traits or not isinstance(traits, dict):
        logger.warning("收到空的用户特征数据")
        return {"skills": 0, "improvements": 0}
    
    try:
        from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
        analyzer = get_unified_analyzer()
        
        logger.info(f"融合用户特征 [{source}] - 技能数: {len(traits.get('skills_observed', []))}")
        
        result = analyzer.apply_user_traits(traits, source, conversation_id)
        
        return result
        
    except Exception as e:
        logger.error(f"用户画像融合失败: {e}", exc_info=True)
        return {"error": str(e), "skills": 0, "improvements": 0}


def request_user_profile_analysis(
    analysis_scope: str = "recent",
    client_context: Optional[dict] = None,
) -> dict:
    """
    请求客户端进行用户画像分析
    
    Args:
        analysis_scope: 分析范围 ("full" / "recent" / "daily" / "weekly")
        client_context: 客户端上下文信息
        
    Returns:
        包含分析请求的完整结构化响应
    """
    from devpartner_agent.core.database import get_db
    db = get_db()
    
    recent_conversations = db.get_recent_conversations(limit=5)
    
    profile_data = {
        "analysis_request": {
            "scope": analysis_scope,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "client_context": client_context or {},
        },
        "recent_data": recent_conversations[:3] if recent_conversations else [],
        "user_traits_schema": _USER_TRAITS_SCHEMA,
        "project_strategy": _PROJECT_STRATEGY,
        "few_shot_examples": _FEW_SHOT_EXAMPLES,
        "analysis_guidelines": {
            "focus_areas": [
                "技术技能识别与等级评估",
                "学习行为模式分析",
                "常见错误与改进方向",
                "沟通偏好与决策风格",
                "情绪状态与学习进度",
            ],
            "output_format": {
                "skills_observed": "已掌握/在学的技术栈列表",
                "behavior_notes": "学习习惯、问题解决方式、沟通特点",
                "tech_interests": "感兴趣的技术方向",
                "areas_for_growth": "需要提升的领域",
                "mistakes": "常见错误模式",
                "strengths": "明显优势",
                "learning_progress": "当前水平 → 目标水平的差距分析",
            },
            "quality_requirements": [
                "基于具体对话证据，避免主观臆断",
                "区分'已知能力'和'正在学习'",
                "标注置信度（high/medium/low）",
                "提供可操作的成长建议",
            ],
        },
    }
    
    return profile_data


def query_user_profile(
    dimensions: Optional[list[str]] = None,
    time_range: Optional[str] = None,
) -> dict:
    """
    查询用户画像数据
    
    Args:
        dimensions: 指定查询维度 ["skills", "behavior", "mistakes", "learning"]
        time_range: 时间范围 ("7d", "30d", "90d", "all")
        
    Returns:
        结构化的画像数据
    """
    from devpartner_agent.core.database import get_db
    db = get_db()
    
    skills_data = db.query_all_user_skills() or []
    
    behavior_data = []
    mistakes_data = []
    strengths_data = []
    learning_data = []
    
    for skill in skills_data:
        skill_name = skill.get("skill_name", "")
        if any(kw in skill_name.lower() for kw in ["习惯", "沟通", "决策", "情绪"]):
            behavior_data.append(skill)
        elif any(kw in skill_name.lower() for kw in ["错误", "问题", "不足"]):
            mistakes_data.append(skill)
        elif any(kw in skill_name.lower() for kw in ["优势", "强项", "擅长"]):
            strengths_data.append(skill)
        else:
            learning_data.append(skill)
    
    result = {
        "query_timestamp": __import__("datetime").datetime.now().isoformat(),
        "total_records": len(skills_data),
        "dimensions_available": {
            "skills": learning_data,
            "behavior": behavior_data,
            "mistakes": mistakes_data,
            "strengths": strengths_data,
            "learning_progress": learning_data[-5:] if learning_data else [],
        },
    }
    
    if dimensions:
        filtered = {k: v for k, v in result["dimensions_available"].items() 
                    if k in (dimensions or [])}
        result["dimensions_available"] = filtered
    
    return result


# PONYTATIL: 静态数据直接定义为模块级常量，避免每次调用时重新构建 dict
_USER_TRAITS_SCHEMA = {
    "version": "7.2",
    "schema_type": "json_schema",
    "fields": {
        "skills_observed": {"type": "array[string]", "description": "从对话中识别的技术技能列表"},
        "behavior_notes": {"type": "string", "description": "学习习惯、问题解决方式、沟通特点"},
        "tech_interests": {"type": "array[string]", "description": "用户表现出的技术兴趣方向"},
        "areas_for_growth": {"type": "array[string]", "description": "需要提升或学习的领域"},
        "mistakes": {"type": "array[string]", "description": "常见的错误模式或知识盲区"},
        "strengths": {"type": "array[string]", "description": "明显的优势和能力"},
        "communication_style": {"type": "string", "enum": ["详细型", "简洁型", "示例驱动型", "理论导向型"]},
        "decision_pattern": {"type": "string", "enum": ["快速决策", "深思熟虑", "依赖建议", "自主探索"]},
        "emotional_state": {"type": "string", "enum": ["积极", "中性", "焦虑", "沮丧"]},
        "learning_progress": {"type": "object", "properties": {"current_level": "string", "target_level": "string", "gap_analysis": "string"}},
    },
    "required_fields": ["skills_observed", "behavior_notes"],
}

_PROJECT_STRATEGY = {
    "focus_areas": ["前端框架 (React/Vue/Angular)", "后端开发 (Python/Django/FastAPI)", "数据库设计 (SQL/NoSQL)", "DevOps 工具链 (Docker/Git/CI-CD)", "AI/ML 应用 (LLM/RAG/Agent)"],
    "priority_skills": ["TypeScript 类型安全编程", "现代前端工程化", "微服务架构设计", "云原生部署实践"],
    "learning_path_suggestion": "1) 基础巩固阶段：熟练掌握当前技术栈核心概念。2) 进阶提升阶段：深入理解底层原理和最佳实践。3) 专家成长阶段：关注前沿技术和架构趋势。",
}

_FEW_SHOT_EXAMPLES = [
    {"scenario": "前端开发者讨论 React 性能优化", "input_dialogue": "我在用 React + TypeScript 开发一个电商项目，遇到了 Redux Toolkit 的异步 action 类型定义错误。", "expected_output": {"skills_observed": ["React 开发", "TypeScript 使用", "Redux Toolkit 状态管理"], "behavior_notes": "能够清晰描述技术问题和上下文", "tech_interests": ["现代前端框架", "类型安全", "状态管理"], "areas_for_growth": ["TypeScript 高级类型", "Redux 异步流程"], "mistakes": ["async/await 与 Promise 混用"], "strengths": ["问题描述准确"]}},
    {"scenario": "后端开发者讨论数据库性能", "input_dialogue": "Django ORM 的 N+1 查询问题怎么解决？我试了 select_related 但还是慢。", "expected_output": {"skills_observed": ["Python/Django", "ORM 使用", "数据库性能调优"], "behavior_notes": "遇到性能问题会主动尝试常见方案再求助", "tech_interests": ["后端架构", "数据库优化"], "areas_for_growth": ["SQL 执行计划分析", "缓存策略设计"], "mistakes": ["混淆 select_related 和 prefetch_related"], "strengths": ["有性能优化意识"]}},
    {"scenario": "DevOps 工具链讨论", "input_dialogue": "我想搭建一个 CI/CD 流水线，用 GitHub Actions 自动部署到 Docker 容器。", "expected_output": {"skills_observed": ["Docker 容器化", "CI/CD 概念", "GitHub Actions"], "behavior_notes": "目标明确，希望系统性地解决问题", "tech_interests": ["自动化运维", "DevOps 实践"], "areas_for_growth": ["YAML 工作流编写", "多环境部署策略"], "mistakes": ["缺少根因分析"], "strengths": ["有自动化意识"]}},
]