#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LLM 统一分析引擎 v6.0
=====================
核心使命：将全项目分散的数据处理硬编码逻辑整合到本地 LLM 统一提示词体系。

设计理念：
- 🎯 单一职责：所有数据分析、归纳、校验、统计工作由本引擎承载
- 🤖 LLM 驱动：依托 llama-cpp-python + Qwen3.5-9B 进行智能推理
- 📐 提示词工程：结构化 Prompt 模板确保输入输出精准可控
- 🔄 双模式：LLM 可用时智能分析，不可用时优雅降级到简化规则
- ⚡ 高性能：复用 LLMService 单例，懒加载模型

替代范围（废弃硬编码）：
❌ conversation_analyzer.py 中的 SKILL_DOMAINS / MCP_TOOL_PATTERNS / COMPLEXITY_PATTERNS / FEEDBACK_PATTERNS
❌ daily_summary.py 中的 Markdown 模板和解析逻辑
❌ self_iterate.py 中的 _generate_data_driven_suggestions 规则引擎
❌ user_profile_service.py 中的字段映射逻辑
❌ upgrade_to_v5.py 中的数据库验证逻辑

使用示例：
    from core.llm_unified_analyzer import get_unified_analyzer
    
    analyzer = get_unified_analyzer()
    
    # 对话分析
    result = analyzer.analyze_conversation(content, source="trae")
    
    # 每日总结
    report = analyzer.generate_daily_summary(work_data)
    
    # 自我迭代建议
    suggestions = analyzer.generate_self_improvements(system_data)
    
    # 用户画像融合
    analyzer.apply_user_traits(traits)
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class LLMUnifiedAnalyzer:
    """
    LLM 统一分析引擎（单例模式）
    
    整合所有数据分析能力到一个入口，通过不同的分析方法区分业务场景。
    所有方法共享同一个 LLM 实例，避免重复加载模型。
    """

    _instance: Optional["LLMUnifiedAnalyzer"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._llm_service = None
        _service_ready = False

    @property
    def is_available(self) -> bool:
        """检查 LLM 服务是否可用"""
        if self._service_ready and self._llm_service:
            return True
        
        try:
            from devpartner_agent.services.llm_service import LLMService
            self._llm_service = LLMService()
            
            if self._llm_service.is_available():
                self._service_ready = True
                logger.info("✅ LLM 统一分析引擎就绪")
                return True
                
            logger.warning("⚠️ LLM 服务未启用或模型不可用")
            return False
            
        except Exception as e:
            logger.error(f"❌ LLM 初始化失败: {e}")
            return False

    def _infer(self, prompt: str, max_tokens: int = 2048) -> Optional[str]:
        """调用 LLM 推理（统一入口）"""
        if not self.is_available:
            return None
            
        try:
            raw = self._llm_service._infer(prompt, max_tokens=max_tokens)
            
            if raw and isinstance(raw, str) and len(raw.strip()) > 20:
                return raw.strip()
                
            return None
            
        except Exception as e:
            logger.warning(f"LLM 推理异常: {e}")
            return None

    def _parse_json_response(self, response: str, fallback: dict = None) -> Optional[dict]:
        """安全解析 LLM 返回的 JSON"""
        if not response:
            return fallback or {}
            
        # 尝试直接解析
        try:
            result = json.loads(response)
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass
        
        # 尝试提取 markdown 代码块中的 JSON
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1).strip())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
        
        # 尝试找到第一个 { ... } 对象
        brace_start = response.find('{')
        brace_end = response.rfind('}')
        
        if brace_start != -1 and brace_end > brace_start:
            try:
                result = json.loads(response[brace_start:brace_end + 1])
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass
        
        logger.warning(f"无法解析 LLM JSON 响应，返回前200字符: {response[:200]}")
        return fallback or {"raw_response": response[:500], "parse_error": True}

    # ═══════════════════════════════════════════════════════
    # 方法 1: 对话内容分析（替代 conversation_analyzer 硬编码）
    # ═══════════════════════════════════════════════════════

    def analyze_conversation(self, content: str, source: str = "unknown",
                            client: str = "unknown") -> dict:
        """
        分析对话内容（LLM 主导模式）
        
        替代原有硬编码：
        - SKILL_DOMAINS 字典（100+ 关键词）
        - MCP_TOOL_PATTERNS 正则（7 个工具模式）
        - COMPLEXITY_PATTERNS 复杂度评估
        - FEEDBACK_PATTERNS 反馈检测
        
        Args:
            content: 对话原文
            source: 来源标识
            client: 客户端标识
            
        Returns:
            结构化分析结果（JSON 格式）
        """
        system_prompt = """你是一个专业的开发者对话分析 AI 助手。请分析以下对话内容并提取关键信息。

## 你的任务
1. 识别技术领域和技能点
2. 评估问题复杂度
3. 检测用户反馈信号
4. 识别应该调用但可能遗漏的 MCP 工具
5. 提取用户行为特征和技能画像

## 输出要求（严格 JSON 格式）
请只输出 JSON，不要包含任何其他文字：

```json
{
  "summary": "一句话概括对话核心内容（50字以内）",
  "skill_domains": [
    {
      "domain": "技术领域名称（如 Python、前端、DevOps、数据库、AI/ML 等）",
      "sub_skills": ["具体技能点列表"],
      "match_score": 0.95,
      "evidence": "支持判断的关键词或上下文"
    }
  ],
  "complexity": "simple 或 multi_step 或 complex",
  "complexity_reason": "复杂度判断依据",
  "user_feedback": {
    "has_feedback": true/false,
    "types": ["纠正/补充/不满/重试/追问"],
    "severity": "none/low/medium/high",
    "details": "反馈详情描述"
  },
  "tool_gaps": [
    {
      "tool": "应调用的 MCP 工具名",
      "reason": "为什么应该调用此工具",
      "confidence": "high/medium/low"
    }
  ],
  "optimization_suggestions": [
    {
      "type": "tool_description_weak/tool_logic_error/missing_optimization",
      "target_tool": "相关工具名",
      "description": "问题描述",
      "suggestion": "改进建议",
      "priority": "low/medium/high"
    }
  ],
  "user_traits": {
    "skills_observed": ["展现的技术技能"],
    "behavior_notes": "行为模式观察",
    "mistakes": ["犯过的错误或踩过的坑"],
    "strengths": ["用户的强项"],
    "communication_style": "沟通风格描述",
    "tech_interests": ["感兴趣的技术方向"],
    "areas_for_growth": ["需要提升的领域"]
  },
  "confidence": 0.95,
  "analysis_method": "llm_qwen3.5_9b"
}
```

## 分析原则
- skill_domains 从常见技术领域中选择或合理新增
- match_score 范围 0.0-1.0，表示匹配置信度
- tool_gaps 仅在明确暗示需要某工具时才列出
- user_traits 基于实际观察，不编造信息
- confidence 表示整体分析的置信度"""

        prompt = f"""## 对话元信息
- 来源: {source}
- 客户端: {client}

## 对话原文
{content[:8000]}

请严格按照要求的 JSON 格式输出分析结果。"""

        response = self._infer(prompt, max_tokens=2048)
        result = self._parse_json_response(response)

        if result and not result.get("parse_error"):
            result["analysis_timestamp"] = datetime.now().isoformat()
            result["inference_engine"] = "llama-cpp-python"
            result["model_info"] = "Qwen3.5-9B-Q4_1"
            return result

        # LLM 失败时降级到简化版规则（仅做基础提取）
        logger.info("LLM 对话分析失败，降级到简化规则")
        return self._fallback_simple_analysis(content, source, client)

    def _fallback_simple_analysis(self, content: str, source: str, 
                                  client: str) -> dict:
        """LLM 不可用时的极简降级方案"""
        content_lower = content.lower()
        
        # 极简关键词匹配（仅用于保底）
        domains = []
        simple_keywords = {
            "Python": ["python", "django", "flask", "pip", "conda"],
            "前端": ["react", "vue", "css", "html", "javascript"],
            "数据库": ["sql", "mysql", "redis", "mongodb", "sqlite"],
            "DevOps": ["docker", "kubernetes", "linux", "nginx", "git"],
        }
        
        for domain, keywords in simple_keywords.items():
            matched = [kw for kw in keywords if kw in content_lower]
            if matched:
                domains.append({
                    "domain": domain,
                    "sub_skills": matched[:3],
                    "match_score": 0.6,
                    "evidence": f"关键词匹配: {', '.join(matched)}"
                })

        return {
            "summary": content[:100] if len(content) < 100 else content[:97] + "...",
            "skill_domains": sorted(domains, key=lambda x: x["match_score"], reverse=True)[:3],
            "complexity": "multi_step" if len(content) > 1000 else "simple",
            "complexity_reason": "基于内容长度估算",
            "user_feedback": {"has_feedback": False, "types": [], "severity": "none"},
            "tool_gaps": [],
            "optimization_suggestions": [],
            "user_traits": {},
            "confidence": 0.4,
            "analysis_method": "fallback_rules",
            "note": "LLM 不可用，使用简化规则分析"
        }

    # ═══════════════════════════════════════════════════════
    # 方法 2: 每日工作总结生成（替代 daily_summary 硬编码模板）
    # ═══════════════════════════════════════════════════════

    def generate_daily_summary(self, work_data: Dict) -> Optional[Dict]:
        """
        生成每日工作总结（LLM 智能生成）
        
        替代原有硬编码：
        - Markdown 报告模板 (_generate_report_file)
        - 数据格式化和字段映射逻辑
        - 固定的报告结构和样式
        
        Args:
            work_data: 从数据库获取的工作数据（get_daily_work_data 返回值）
            
        Returns:
            结构化日报数据（可直接保存或展示）
        """
        if not work_data or not work_data.get("conversations"):
            return None

        system_prompt = """你是一个专业的开发者工作日报生成助手。基于今日工作数据，生成结构化的中文日报分析。

## 任务
1. 提取关键成果和学习收获
2. 识别潜在风险和技术债务
3. 评估工作效率和成长情况
4. 制定明日优先事项

## 输出格式（严格 JSON）

```json
{
  "date": "YYYY-MM-DD",
  "summary": "一句话总结今天的主要工作成果（100字以内）",
  
  "experience": {
    "deep_dive": "今天最深入的技术探索或解决的问题（200字以内）",
    "lesson": "今天学到的重要经验或教训（150字以内）"
  },
  
  "skills": {
    "new_skills": ["今天新接触或使用的技能"],
    "patterns": ["发现的可复用模式或规律"],
    "tools": ["使用过的工具清单"]
  },
  
  "knowledge": {
    "must_remember": ["必须记住的关键知识点（3-5条）"],
    "insights": ["重要洞察和发现（2-3条）"]
  },
  
  "danger_signals": {
    "repeated_mistakes": ["重复出现的错误（如有）"],
    "tech_debt": ["积累的技术债务（如有）"],
    "hot_files": ["频繁修改的高风险文件（如有）"]
  },
  
  "tomorrow_plan": "明天最优先要完成的1-3件事（50字以内）",
  
  "self_analysis": {
    "strengths": ["今天的优点（2-3条）"],
    "weaknesses": ["需要改进的地方（2-3条）"],
    "growthSuggestions": ["具体的成长建议（2-3条）"]
  },
  
  "metrics": {
    "productivity_score": 7,
    "learning_score": 8,
    "collaboration_score": 6
  },
  
  "confidence": 0.9,
  "generated_by": "llm_qwen3.5_9b"
}
```

## 评分标准（1-10分）
- productivity_score: 工作产出效率
- learning_score: 学习成长收获
- collaboration_score: 协作沟通效率

## 注意事项
- 基于实际数据进行分析，不要编造
- 突出重点，避免流水账
- 保持客观中立"""

        conversations_json = json.dumps(
            work_data.get("conversations", [])[:15], 
            ensure_ascii=False, 
            indent=2
        )[:6000]

        prompt = f"""## 今日日期
{work_data.get('date', '未知')}

## 工作数据概览
- 对话总数: {len(work_data.get('conversations', []))}
- 涉及文件数: {len(work_data.get('files_touched', []))}
- 主要任务类型: {', '.join(list(set(c.get('task_type', '') for c in work_data.get('conversations', [])))[:5])}

## 详细对话记录
{conversations_json}

请根据以上数据生成完整的每日工作总结 JSON。"""

        response = self._infer(prompt, max_tokens=2500)
        result = self._parse_json_response(response)

        if result and not result.get("parse_error"):
            result["generated_at"] = datetime.now().isoformat()
            result["data_source"] = work_data.get("data_source", "db")
            result["inference_engine"] = "llama-cpp-python"
            return result

        logger.warning("LLM 日报生成失败")
        return None

    # ═══════════════════════════════════════════════════════
    # 方法 3: 自我改进建议生成（替代 self_iterate 硬编码规则）
    # ═══════════════════════════════════════════════════════

    def generate_self_improvements(self, system_data: Dict, 
                                   improvement_history: List = None) -> List[Dict]:
        """
        生成系统自我改进建议（LLM 智能分析）
        
        替代原有硬编码：
        - 用户画像分析规则
        - MCP 工具优化规则（零使用清理/高频增强）
        - 系统健康度评估规则
        - 功能缺口识别逻辑
        
        Args:
            system_data: 系统状态数据（_collect_system_data 返回值）
            improvement_history: 历史优化记录（可选上下文）
            
        Returns:
            改进建议列表（每项包含详细执行方案）
        """
        history_json = json.dumps(improvement_history or [], ensure_ascii=False)[:3000]
        system_json = json.dumps(system_data, ensure_ascii=False, default=str)[:5000]

        system_prompt = """你是 DevPartner 系统的自我优化专家。基于系统运行数据和历史记录，生成可执行的改进建议。

## 任务维度
1. 性能瓶颈识别与优化建议
2. 用户体验提升方案
3. 功能缺口发现与补全建议
4. MCP 工具集优化（清理/增强/新增）
5. 代码质量和架构改进
6. 数据健康度和完整性提升

## 输出格式（严格 JSON 数组）

```json
[
  {
    "category": "performance/usability/reliability/feature/mcp_tool_cleanup/mcp_tool_hotspot/code_quality/data_health",
    "priority": "high/medium/low",
    "title": "简短标题（20字以内）",
    "suggestion": "具体问题描述和建议（100字以内）",
    "expected_impact": "预期影响和价值（50字以内）",
    "effort": "实现难度 easy/medium/hard",
    
    "detail": {
      "action": "review/enhance/disable/deprecate/add/refactor",
      "target_files": ["相关文件路径列表"],
      "current_issue": "当前问题描述",
      "proposed_solution": "解决方案概述（150字以内）",
      "code_changes": ["具体的代码变更建议（如有）"],
      "metrics_to_improve": ["预期改善的指标"]
    },
    
    "source": "llm",
    "confidence": 0.85,
    "generated_at": "ISO时间戳"
  }
]
```

## 建议原则
- 每条建议必须可执行、可度量
- 优先考虑高价值低成本改进（quick wins）
- 关注用户体验和系统稳定性
- 避免过度工程化
- 建议数量控制在 5-10 条"""

        prompt = f"""## 当前系统状态数据
```json
{system_json}
```

## 最近优化历史（最近20条）
```json
{history_json}
```

请基于以上数据，生成 5-8 条高价值的自我改进建议。重点关注：
1. 可以快速实施的改进（quick wins）
2. 影响用户体验的关键问题
3. 系统稳定性风险
4. MCP 工具使用效率优化"""

        response = self._infer(prompt, max_tokens=3000)
        result = self._parse_json_response(response, fallback=[])

        if isinstance(result, list) and len(result) > 0:
            for item in result:
                if isinstance(item, dict):
                    item["source"] = "llm_unified_analyzer"
                    item["model_type"] = "qwen3.5-9b-q4_1"
                    item["generated_at"] = datetime.now().isoformat()
            return result

        logger.warning("LLM 改进建议生成失败")
        return []

    # ═══════════════════════════════════════════════════════
    # 方法 4: 用户画像融合（替代 user_profile_service 硬编码映射）
    # ═══════════════════════════════════════════════════════

    def apply_user_traits(self, traits: Dict, source: str = "unified_analyzer",
                          conversations_id: int = None) -> Dict:
        """
        将用户画像特征写入数据库（LLM 智能处理 + 增量合并）
        
        v6.0 增强：
        - ✅ 技能增量合并：已存在则更新置信度，不存在则新增
        - ✅ 追溯能力：记录 source_conversation_id 和 source_timestamp
        - ✅ 防膨胀：同一技能不会重复插入
        
        Args:
            traits: 用户特征字典（来自对话分析结果）
            source: 来源标识
            conversations_id: 关联的对话 ID
            
        Returns:
            操作统计 {"skills": N, "inserted": N, "updated": N, "improvements": N}
        """
        if not traits or not isinstance(traits, dict):
            return {"error": "无效的用户特征数据"}

        from devpartner_agent.core.database import get_db
        db = get_db()

        updates = {"skills": 0, "inserted": 0, "updated": 0, "improvements": 0, "plans": 0}

        # 使用 LLM 智能拆分和处理特征（可选增强）
        processed = self._process_user_traits_with_llm(traits)

        # 写入技能观察（带增量合并逻辑）
        skills_observed = processed.get("skills_observed", [])
        if isinstance(skills_observed, str):
            skills_observed = [skills_observed]
            
        for skill in skills_observed:
            try:
                # ★ 增量合并逻辑
                merge_result = self._merge_skill_incremental(
                    db=db,
                    skill_name=skill,
                    context={
                        "skill_level": processed.get("skill_level", "intermediate"),
                        "sub_skills": processed.get("related_skills", []),
                        "evidence_text": processed.get("evidence_text", f"从对话中观察到 {skill} 技能"),
                        "estimated_hours": processed.get("estimated_hours", 0.3),
                        "growth_trend": processed.get("growth_trend", "growing"),
                        "source_conversation_id": conversations_id,
                        "source_timestamp": datetime.now().isoformat(),
                        "extraction_method": source,
                    }
                )
                
                if merge_result["action"] == "inserted":
                    updates["inserted"] += 1
                elif merge_result["action"] == "updated":
                    updates["updated"] += 1
                    
                updates["skills"] += 1
                
            except Exception as e:
                logger.debug(f"写入技能失败 [{skill}]: {e}")

        # 写入行为模式和强项/弱项
        behavior_items = []
        
        behavior_notes = processed.get("behavior_notes", "")
        communication_style = processed.get("communication_style", "")
        decision_pattern = processed.get("decision_pattern", "")
        
        if behavior_notes:
            behavior_items.append(("user_behavior_profile", f"行为模式: {behavior_notes}", "low"))
        if communication_style:
            behavior_items.append(("user_communication_profile", 
                                   f"沟通风格: {communication_style} | 决策: {decision_pattern or '未观察'}", "low"))

        mistakes = processed.get("mistakes", [])
        if isinstance(mistakes, str):
            mistakes = [mistakes]
        for mistake in mistakes:
            behavior_items.append(("user_lesson_learned", f"踩坑记录: {mistake}", "medium"))

        strengths = processed.get("strengths", [])
        if isinstance(strengths, str):
            strengths = [strengths]
        for strength in strengths:
            behavior_items.append(("user_strength", f"用户强项: {strength}", "low"))

        for category, suggestion, priority in behavior_items:
            try:
                db.insert_improvement(
                    category=category,
                    suggestion=suggestion,
                    priority=priority,
                    conversations_id=conversations_id,
                )
                updates["improvements"] += 1
            except Exception as e:
                logger.debug(f"写入改进记录失败 [{category}]: {e}")

        # 写入技能规划
        tech_interests = processed.get("tech_interests", [])
        areas_for_growth = processed.get("areas_for_growth", [])
        
        planning_items = []
        if isinstance(tech_interests, str):
            tech_interests = [tech_interests]
        for interest in tech_interests:
            planning_items.append((interest, f"深入学习 {interest}", "advanced"))
            
        if isinstance(areas_for_growth, str):
            areas_for_growth = [areas_for_growth]
        for area in areas_for_growth:
            planning_items.append((area, f"重点提升 {area} 能力", "intermediate"))

        for domain, goal, target_level in planning_items:
            try:
                db.set_skill_plan(domain=domain, goal=goal, target_level=target_level)
                updates["plans"] += 1
            except Exception as e:
                logger.debug(f"写入技能规划失败 [{domain}]: {e}")

        # 情绪状态（如有）
        emotional_state = processed.get("emotional_state", "")
        if emotional_state:
            try:
                db.insert_optimization_feedback({
                    "source": source,
                    "feedback_type": "emotional_state",
                    "description": f"用户情绪: {emotional_state}",
                    "suggestion": "关注用户情绪变化，调整交互策略",
                    "priority": "low",
                    "conversations_id": conversations_id,
                })
            except Exception:
                pass

        logger.info(f"用户画像融合完成: {updates}")
        return updates

    def _process_user_traits_with_llm(self, traits: Dict) -> Dict:
        """使用 LLM 智能处理和丰富用户特征（可选增强）"""
        if not self.is_available:
            return traits

        try:
            prompt = f"""请处理以下用户特征数据，进行智能拆分和丰富：

原始特征数据：
```json
{json.dumps(traits, ensure_ascii=False)}
```

请输出处理后的 JSON（保持相同结构，但优化内容）：
- 提取更精确的技能等级评估
- 补充相关的子技能
- 生成更自然的证据文本
- 估算合理的学习时间投入
- 判断成长趋势"""

            response = self._infer(prompt, max_tokens=1024)
            enhanced = self._parse_json_response(response)
            
            if enhanced and not enhanced.get("parse_error"):
                return enhanced
                
        except Exception as e:
            logger.debug(f"LLM 特征处理失败，使用原始数据: {e}")

        return traits

    # ═══════════════════════════════════════════════════════
    # 方法 5: 数据库 Schema 分析（替代升级脚本硬编码验证）
    # ═══════════════════════════════════════════════════════

    def analyze_database_schema(self, schema_metadata: Dict, 
                                expected_version: str = "v5.0") -> Dict:
        """
        分析数据库 Schema 合规性
        
        用于数据库升级验证、健康检查等场景。
        """
        system_prompt = """你是一个数据库 Schema 分析专家，精通 SQLite 和 DevPartner 系统架构。

## 任务
分析输入的数据库元信息，对照目标版本要求进行合规性检查。

## 输出格式（严格 JSON）

```json
{
  "status": "healthy/warning/critical",
  "version_compliant": true/false,
  "issues": [
    {
      "type": "missing_table/missing_column/constraint_error/data_type_mismatch/index_missing",
      "severity": "low/medium/high",
      "target": "受影响的表或列名",
      "description": "问题描述",
      "fix_sql": "修复 SQL（如适用）"
    }
  ],
  "recommendations": ["建议列表"],
  "statistics": {
    "table_count": 数量,
    "total_columns": 数量,
    "indexes_count": 数量,
    "estimated_data_size_mb": 数量
  },
  "data_quality_score": 0.85,
  "next_actions": ["下一步操作建议"]
}
```"""

        prompt = f"""## 目标版本: {expected_version}

## 当前数据库元信息
```json
{json.dumps(schema_metadata, indent=2, ensure_ascii=False)}
```

请进行详细的合规性分析。"""

        response = self._infer(prompt, max_tokens=2048)
        return self._parse_json_response(response)

    # ═══════════════════════════════════════════════════════
    # 私有方法：技能增量合并（v6.0 新增）
    # ═══════════════════════════════════════════════════════

    def _merge_skill_incremental(self, db, skill_name: str, context: dict) -> dict:
        """
        技能增量合并逻辑
        
        防止 user_skills 表快速膨胀：
        1. 查询 skill 是否已存在
           - 存在: 更新 last_seen, confidence += 0.1, 合并 sub_skills
           - 不存在: 新增记录
        2. 记录来源追溯信息（source_conversation_id, source_timestamp）
        
        Args:
            db: 数据库实例
            skill_name: 技能名称
            context: 技能上下文信息
            
        Returns:
            {"action": "inserted"/"updated", "skill": str, "confidence": float}
        """
        try:
            existing = db.query_user_skill(skill_name)
            
            if existing and isinstance(existing, dict):
                # ★ 已存在 → 增量更新
                old_confidence = float(existing.get("confidence", 0.5))
                new_confidence = min(old_confidence + 0.1, 1.0)  # 每次增加0.1，上限1.0
                
                # 合并 sub_skills（去重）
                old_sub_skills = set(existing.get("sub_skills", "").split(", ")) if existing.get("sub_skills") else set()
                new_sub_skills = set(context.get("sub_skills", []))
                merged_sub_skills = list(old_sub_skills | new_sub_skills)[:10]  # 最多保留10个
                
                # 更新记录
                update_data = {
                    "skill_level": context.get("skill_level", existing.get("skill_level", "intermediate")),
                    "sub_skills": ", ".join(merged_sub_skills) if merged_sub_skills else "",
                    "evidence": f"{context.get('extraction_method', 'unknown')}: {context.get('evidence_text', '')}",
                    "confidence": new_confidence,
                    "last_seen": context.get("source_timestamp", datetime.now().isoformat()),
                    "evidence_count": (existing.get("evidence_count", 1) or 1) + 1,
                    "hours_spent": (existing.get("hours_spent", 0) or 0) + context.get("estimated_hours", 0),
                    "growth_trend": context.get("growth_trend", "growing"),
                }
                
                db.update_user_skill(skill_name, update_data)
                
                logger.debug(f"技能增量更新 [{skill_name}] confidence: {old_confidence:.2f} → {new_confidence:.2f}")
                
                return {
                    "action": "updated",
                    "skill": skill_name,
                    "confidence": new_confidence,
                    "evidence_count": update_data["evidence_count"],
                }
                
            else:
                # ★ 不存在 → 新增
                insert_data = {
                    "skill_name": skill_name,
                    "skill_level": context.get("skill_level", "beginner"),
                    "sub_skills": ", ".join(context.get("sub_skills", [])) if context.get("sub_skills") else "",
                    "evidence": f"{context.get('extraction_method', 'unknown')}: {context.get('evidence_text', '')}",
                    "conversation_ids": str(context.get("source_conversation_id", "")),
                    "hours_spent": context.get("estimated_hours", 0.3),
                    "growth_trend": context.get("growth_trend", "stable"),
                    
                    # v6.0 新增字段：追溯能力
                    "confidence": 0.5,
                    "first_seen": context.get("source_timestamp", datetime.now().isoformat()),
                    "last_seen": context.get("source_timestamp", datetime.now().isoformat()),
                    "evidence_count": 1,
                    "source_conversation_id": context.get("source_conversation_id"),
                    "source_timestamp": context.get("source_timestamp"),
                    "extraction_method": context.get("extraction_method", "unknown"),
                }
                
                db.insert_user_skill(insert_data)
                
                logger.debug(f"技能新增 [{skill_name}] confidence: 0.5")
                
                return {
                    "action": "inserted",
                    "skill": skill_name,
                    "confidence": 0.5,
                    "evidence_count": 1,
                }
                
        except Exception as e:
            logger.error(f"技能增量合并失败 [{skill_name}]: {e}")
            
            # 降级：直接 upsert（兼容旧逻辑）
            try:
                db.upsert_user_skills(skill_name, {
                    "skill_level": context.get("skill_level", "intermediate"),
                    "sub_skills": ", ".join(context.get("sub_skills", [])) if context.get("sub_skills") else "",
                    "evidence": f"{context.get('extraction_method', 'unknown')}: {context.get('evidence_text', '')}",
                    "conversation_ids": str(context.get("source_conversation_id", "")),
                    "hours_spent": context.get("estimated_hours", 0.3),
                    "growth_trend": context.get("growth_trend", "growing"),
                })
                
                return {"action": "fallback_upsert", "skill": skill_name, "error": str(e)}
                
            except Exception as e2:
                logger.error(f"降级 upsert 也失败 [{skill_name}]: {e2}")
                return {"action": "failed", "skill": skill_name, "error": str(e2)}

    def query_skill_lineage(self, skill_name: str) -> list:
        """
        查询技能的学习轨迹（v6.0 新增）
        
        支持画像追溯：
        - 某个技能是什么时候学的？
        - 从哪个对话中提取的？
        - 置信度如何变化？
        
        Args:
            skill_name: 技能名称
            
        Returns:
            学习轨迹列表，按时间排序
        """
        from devpartner_agent.core.database import get_db
        db = get_db()
        
        try:
            lineage = db.query_skill_history(skill_name)
            
            if lineage and isinstance(lineage, list):
                return sorted(lineage, key=lambda x: x.get("timestamp", ""))
            
            return []
            
        except Exception as e:
            logger.error(f"查询技能轨迹失败 [{skill_name}]: {e}")
            return []


# ═══════════════════════════════════════════════════════
# 全局便捷访问
# ═══════════════════════════════════════════════════════

_analyzer_instance: Optional[LLMUnifiedAnalyzer] = None


def get_unified_analyzer() -> LLMUnifiedAnalyzer:
    """获取全局统一分析器单例"""
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = LLMUnifiedAnalyzer()
    return _analyzer_instance