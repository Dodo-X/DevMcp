import json
import time
import logging
import threading
import urllib.request
import urllib.error
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = "http://localhost:11434"


class LLMEngine:
    """统一 LLM 推理引擎 + 业务方法"""

    def __init__(self):
        self._lock = threading.Lock()
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_inference_time = 0.0
        self._avg_tokens_per_second = 0.0
        self._load_error: Optional[str] = None

    def _get_config(self):
        from devpartner_agent.core.config import get_config
        return get_config()

    def is_enabled(self) -> bool:
        cfg = self._get_config()
        return getattr(cfg.llm, "enabled", False) if hasattr(cfg, "llm") else False

    def is_available(self) -> bool:
        if not self.is_enabled():
            return False
        try:
            req = urllib.request.Request(f"{_OLLAMA_BASE_URL}/api/tags", method="GET")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_status(self) -> dict:
        return {
            "enabled": self.is_enabled(),
            "available": self.is_available(),
            "inference_count": self._inference_count,
            "avg_tokens_per_second": round(self._avg_tokens_per_second, 1),
            "last_inference_time": round(self._last_inference_time, 2),
            "load_error": self._load_error,
        }

    def preload(self):
        if not self.is_enabled():
            self._load_error = "Ollama not enabled"
            return False
        try:
            cfg = self._get_config()
            model_name = getattr(cfg, "ollama_model", "qwen3")
            req = urllib.request.Request(
                f"{_OLLAMA_BASE_URL}/api/show",
                data=json.dumps({"name": model_name}).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    logger.info(f"LLM model {model_name} preloaded")
                    return True
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"LLM preload failed: {e}")
        return False

    def infer(self, prompt: str, max_tokens: int = 2048) -> Optional[str]:
        if not self.is_enabled():
            return None
        cfg = self._get_config()
        model_name = getattr(cfg, "ollama_model", "qwen3")
        timeout = getattr(cfg, "ollama_timeout", 120)
        start_time = time.time()
        try:
            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
            req = urllib.request.Request(
                f"{_OLLAMA_BASE_URL}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                text = result.get("response", "")
                elapsed = time.time() - start_time
                with self._lock:
                    self._inference_count += 1
                    self._total_inference_time += elapsed
                    self._last_inference_time = elapsed
                    if elapsed > 0:
                        tokens = len(text)
                        self._avg_tokens_per_second = tokens / elapsed
                return text
        except urllib.error.URLError as e:
            logger.error(f"Ollama connection failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Ollama inference failed: {e}", exc_info=True)
            return None

    # ===== Analysis methods (delegate to llm_prompts.run_analysis) =====

    def analyze_conversation(self, content: str, source: str = "unknown",
                             client: str = "unknown") -> Optional[dict]:
        from devpartner_agent.core.llm_prompts import run_analysis, TASK_CONVERSATION_ANALYSIS
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg, "enhance_analysis", True):
            return None
        return run_analysis(
            TASK_CONVERSATION_ANALYSIS,
            content=content[:TASK_CONVERSATION_ANALYSIS.input_truncate],
            source=source,
            client=client,
        )

    def analyze_step_content(self, step_name: str, step_type: str, content: str,
                              symptom: str = "", root_cause: str = "",
                              solution: str = "") -> Optional[dict]:
        from devpartner_agent.core.llm_prompts import run_analysis, TASK_STEP_ANALYSIS
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg, "enhance_analysis", True):
            return None
        return run_analysis(
            TASK_STEP_ANALYSIS,
            step_name=step_name or "unknown",
            step_type=step_type or "general",
            symptom=symptom or "none",
            root_cause=root_cause or "none",
            solution=solution or "none",
            content=content[:TASK_STEP_ANALYSIS.input_truncate],
        )

    def analyze_conversation_deep(self, summary: str, self_reflection: str,
                                   user_traits: dict, key_decisions: list,
                                   steps_summary: list) -> Optional[dict]:
        import json as _json
        from devpartner_agent.core.llm_prompts import run_analysis, TASK_CONVERSATION_DEEP_ANALYSIS
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg, "enhance_analysis", True):
            return None
        steps_str = _json.dumps(steps_summary, ensure_ascii=False, indent=2)[:10000]
        traits_str = _json.dumps(user_traits or {}, ensure_ascii=False, indent=2)
        decisions_str = _json.dumps(key_decisions or [], ensure_ascii=False, indent=2)
        return run_analysis(
            TASK_CONVERSATION_DEEP_ANALYSIS,
            summary=summary or "none",
            self_reflection=self_reflection or "none",
            user_traits=traits_str,
            key_decisions=decisions_str,
            steps_summary=steps_str,
        )

    def generate_daily_summary(self, target_date: str, data: dict) -> Optional[dict]:
        import json as _json
        from devpartner_agent.core.llm_prompts import run_analysis, TASK_DAILY_SUMMARY
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg, "enhance_daily_summary", False):
            return None
        conversations_json = _json.dumps(
            data.get("conversations", [])[:15],
            ensure_ascii=False, indent=2
        )[:TASK_DAILY_SUMMARY.input_truncate]
        result = run_analysis(
            TASK_DAILY_SUMMARY,
            date=target_date,
            total_conversations=len(data.get("conversations", [])),
            files_count=len(data.get("files_touched", [])),
            task_types=", ".join(list(set(
                c.get("task_type", "") for c in data.get("conversations", [])
            ))[:5]),
            conversations=conversations_json,
        )
        if result:
            result["data_source"] = data.get("data_source", "db")
        return result

    def generate_self_improvement_suggestions(self, system_data: dict,
                                               improvement_history: list = None) -> Optional[list]:
        import json as _json
        from devpartner_agent.core.llm_prompts import run_analysis, TASK_SELF_IMPROVEMENT
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg, "enhance_self_improvement", False):
            return None
        history_json = _json.dumps(improvement_history or [], ensure_ascii=False)[:3000]
        system_json = _json.dumps(system_data, ensure_ascii=False, default=str)[:5000]
        return run_analysis(
            TASK_SELF_IMPROVEMENT,
            system_data=system_json,
            improvement_history=history_json,
        )

    def parse_file_conversations(self, content: str, filename: str = "unknown") -> Optional[dict]:
        from devpartner_agent.core.llm_prompts import run_analysis, TASK_FILE_PARSE
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg, "enhance_file_parsing", True):
            return None
        return run_analysis(
            TASK_FILE_PARSE,
            content=content[:TASK_FILE_PARSE.input_truncate],
            filename=filename,
        )

    # ===== Business logic methods (from LLMUnifiedAnalyzer) =====

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

            # 学习进度（如有）
            learning_progress = processed.get("learning_progress", "")
            if learning_progress:
                try:
                    db.insert_improvement(
                        category="learning_progress",
                        suggestion=f"学习收获: {learning_progress}",
                        priority="low",
                        conversations_id=conversations_id,
                    )
                    updates["improvements"] += 1
                except Exception as e:
                    logger.debug(f"写入学习进度失败: {e}")

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


_engine_instance: Optional[LLMEngine] = None


def get_llm_engine() -> LLMEngine:
    """获取全局 LLM 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = LLMEngine()
    return _engine_instance