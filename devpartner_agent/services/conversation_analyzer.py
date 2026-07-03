#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对话分析引擎 v6.0 (LLM 驱动)
============================
v6.0 重构说明：
- ✅ 废弃所有硬编码规则（SKILL_DOMAINS, MCP_TOOL_PATTERNS, COMPLEXITY_PATTERNS 等）
- ✅ 统一委托给 LLMUnifiedAnalyzer 进行智能分析
- ✅ 保留 analyze_and_store() 作为数据库写入入口（兼容旧接口）
- ✅ 代码量从 654行 → ~180行（减少 72%）

替代方案详见: core/llm_unified_analyzer.py
"""

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class ConversationAnalyzer:
    """
    对话分析引擎 v6.0 (LLM 驱动)
    
    完全废弃硬编码逻辑，统一由 LLM 承载分析工作。
    """

    _instance: Optional["ConversationAnalyzer"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True

    def analyze(self, content: str, source: str = "unknown",
                client: str = "unknown") -> dict:
        """
        分析对话内容（主入口）
        
        Args:
            content: 对话原文
            source: 来源标识 (codebuddy/cursor/windsurf/trae/...)
            client: 客户端标识
            
        Returns:
            结构化分析结果字典
        """
        try:
            from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
            
            analyzer = get_unified_analyzer()
            
            if analyzer.is_available:
                logger.debug(f"使用 LLM 分析对话 [{source}:{client}]")
                result = analyzer.analyze_conversation(content, source, client)
                
                if result and result.get("confidence", 0) > 0.5:
                    result["analysis_version"] = "v6.0_llm"
                    result["analyzer_type"] = "unified_llm"
                    return result
                
                logger.warning("LLM 分析置信度过低，降级到简化模式")
            
        except Exception as e:
            logger.error(f"LLM 分析失败: {e}")
        
        # Fallback: 极简规则保底
        logger.info(f"使用简化规则分析对话 [{source}:{client}]")
        return self._fallback_analysis(content, source, client)

    def _fallback_analysis(self, content: str, source: str,
                          client: str) -> dict:
        """极简降级方案（LLM 不可用时的保底逻辑）"""
        content_lower = content.lower()
        
        simple_domains = {
            "Python": ["python", "django", "flask", "fastapi"],
            "前端": ["react", "vue", "javascript", "typescript"],
            "数据库": ["sql", "mysql", "redis", "mongodb"],
            "DevOps": ["docker", "git", "linux", "nginx"],
        }
        
        domains = []
        for domain, keywords in simple_domains.items():
            matched = [kw for kw in keywords if kw in content_lower]
            if matched:
                domains.append({
                    "domain": domain,
                    "sub_skills": matched[:3],
                    "match_score": 0.5,
                    "evidence": f"基础关键词匹配"
                })
        
        complexity = "complex" if len(content) > 2000 else ("multi_step" if len(content) > 500 else "simple")

        return {
            "summary": content[:100] + ("..." if len(content) > 100 else ""),
            "skill_domains": sorted(domains, key=lambda x: x["match_score"], reverse=True)[:3],
            "complexity": complexity,
            "complexity_reason": "基于内容长度的简单估算",
            "user_feedback": {"has_feedback": False, "types": [], "severity": "none"},
            "tool_gaps": [],
            "optimization_suggestions": [{
                "type": "llm_unavailable",
                "description": "当前使用降级模式，建议检查 LLM 服务状态",
                "priority": "low"
            }],
            "user_traits": {},
            "confidence": 0.3,
            "analysis_method": "fallback_simple_rules",
            "analysis_version": "v6.0_fallback",
        }

    def analyze_and_store(self, content: str, source: str = "unknown",
                          client: str = "unknown", conversation_id: str = "") -> dict:
        """
        分析对话并存入数据库（兼容旧接口）
        
        保持与 v4.4 相同的行为：
        1. 调用 analyze() 获取分析结果
        2. 存档到 conversations 表
        3. 更新用户技能画像（增量合并）
        4. 写入优化反馈
        5. 融合用户画像特征
        """
        from devpartner_agent.core.database import get_db
        
        result = self.analyze(content, source, client)
        db = get_db()
        conv_id = conversation_id or datetime.now().strftime("%Y%m%d%H%M%S%f")

        try:
            db.archive_conversation({
                "timestamp": datetime.now().isoformat(),
                "source": source,
                "client": client,
                "conversation_id": conv_id,
                "raw_content": content,
                "summary": result.get("summary", ""),
                "skill_domains": json.dumps(result.get("skill_domains", []), ensure_ascii=False),
                "complexity": result.get("complexity", "simple"),
                "tool_calls": json.dumps(result.get("tool_gaps", {}).get("called_tools", []), ensure_ascii=False),
                "user_feedback": json.dumps(result.get("user_feedback", {}), ensure_ascii=False),
            })

            for domain_info in result.get("skill_domains", []):
                domain = domain_info.get("domain", "")
                sub_skills = domain_info.get("sub_skills", [])
                
                if domain:
                    db.upsert_user_skills(domain, {
                        "skill_level": self._estimate_skill_level(
                            domain, 
                            result.get("complexity", "simple"),
                            result.get("confidence", 0.5)
                        ),
                        "sub_skills": ", ".join(sub_skills) if sub_skills else "",
                        "evidence": result.get("summary", ""),
                        "conversation_ids": conv_id,
                        "hours_spent": self._estimate_time_spent(
                            result.get("complexity", "simple"),
                            len(content)
                        ),
                        "growth_trend": "stable",
                    })

            for suggestion in result.get("optimization_suggestions", []):
                try:
                    db.insert_optimization_feedback({
                        "source": source,
                        "feedback_type": suggestion.get("type", "unknown"),
                        "target_tool": suggestion.get("target_tool", ""),
                        "target_rule": suggestion.get("target_rule", ""),
                        "description": suggestion.get("description", ""),
                        "suggestion": suggestion.get("suggestion", ""),
                        "priority": suggestion.get("priority", "medium"),
                        "conversation_id": conv_id,
                    })
                except Exception as e:
                    logger.debug(f"写入优化反馈失败: {e}")

            user_traits = result.get("user_traits")
            if user_traits and isinstance(user_traits, dict) and result.get("confidence", 0) > 0.7:
                try:
                    from devpartner_agent.core.llm_unified_analyzer import get_unified_analyzer
                    analyzer = get_unified_analyzer()
                    analyzer.apply_user_traits(user_traits, f"conv:{source}", conv_id)
                except Exception as e:
                    logger.debug(f"用户画像融合失败: {e}")

        except Exception as e:
            logger.error(f"对话存档失败: {e}", exc_info=True)

        return result

    def _estimate_skill_level(self, domain: str, complexity: str, confidence: float) -> str:
        base_level = "beginner"
        if confidence > 0.8:
            if complexity == "complex":
                base_level = "advanced"
            elif complexity == "multi_step":
                base_level = "intermediate"
        elif confidence > 0.6:
            if complexity in ("multi_step", "complex"):
                base_level = "intermediate"
        return base_level

    def _estimate_time_spent(self, complexity: str, content_length: int) -> float:
        if complexity == "complex":
            return min(content_length / 1000, 2.0)
        elif complexity == "multi_step":
            return min(content_length / 2000, 1.0)
        else:
            return 0.2


_analyzer_instance: Optional[ConversationAnalyzer] = None


def get_analyzer() -> ConversationAnalyzer:
    """获取全局分析器单例"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = ConversationAnalyzer()
    return _analyzer_instance


def analyze_conversation(content: str, source: str = "unknown",
                        client: str = "unknown") -> dict:
    """便捷函数：直接分析对话"""
    return get_analyzer().analyze(content, source, client)


if __name__ == "__main__":
    test_content = """
    我在使用 React 和 TypeScript 开发一个前端项目，
    遇到了一个关于 Hooks 使用的性能问题。
    我尝试了 useMemo 和 useCallback 但效果不明显，
    能否帮我分析一下原因？
    
    另外我还想了解如何在项目中集成 Redux Toolkit 进行状态管理。
    """
    
    print("=" * 60)
    print("🧪 测试 ConversationAnalyzer v6.0 (LLM 驱动)")
    print("=" * 60)
    
    analyzer = get_analyzer()
    result = analyzer.analyze(test_content, "test", "cli")
    
    print("\n📊 分析结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))