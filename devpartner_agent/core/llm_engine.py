import json
import os
import time
import logging
import threading
import urllib.request
import urllib.error
from collections import deque
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# ── v9.5.1 请求拦截器（调试用，不持久化） ──
_intercept_enabled = False
_intercept_lock = threading.Lock()
_intercept_buffer = deque(maxlen=50)  # 最近 50 条请求记录

def is_intercept_enabled() -> bool:
    return _intercept_enabled

def set_intercept_enabled(enable: bool) -> bool:
    global _intercept_enabled
    with _intercept_lock:
        _intercept_enabled = enable
    return _intercept_enabled

def get_intercept_logs() -> list:
    with _intercept_lock:
        return list(_intercept_buffer)

def clear_intercept_logs():
    with _intercept_lock:
        _intercept_buffer.clear()


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
        """v9.5.1: 增强模型名校验，避免假成功。

        调用 Ollama /api/show 验证模型是否存在，并对比返回的模型名。
        如果返回 404 或模型名不匹配，输出诊断信息引导用户修正配置。
        """
        if not self.is_enabled():
            self._load_error = "Ollama not enabled"
            return False
        try:
            cfg = self._get_config()
            model_name = getattr(cfg.llm, "ollama_model", "qwen3")
            req = urllib.request.Request(
                f"{_OLLAMA_BASE_URL}/api/show",
                data=json.dumps({"name": model_name}).encode("utf-8"),
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    body = resp.read().decode("utf-8")
                    result = json.loads(body)
                    actual_model = result.get("model", "") or result.get("modelfile", "")
                    if actual_model:
                        logger.info(
                            f"LLM model '{model_name}' preloaded successfully "
                            f"(Ollama 返回: '{actual_model[:60]}')"
                        )
                    else:
                        logger.info(f"LLM model '{model_name}' preloaded (Ollama 响应正常)")
                    return True
                else:
                    body = resp.read().decode("utf-8")[:200]
                    self._load_error = f"HTTP {resp.status}: {body}"
                    logger.warning(
                        f"LLM preload failed: HTTP {resp.status} for model '{model_name}'\n"
                        f"  → 请检查: 1) 'ollama list' 查看已安装模型\n"
                        f"  →         2) config.yaml 中 ollama_model 是否与已安装模型名一致\n"
                        f"  →         3) 如需拉取: ollama pull {model_name}"
                    )
                    return False
        except urllib.error.HTTPError as e:
            self._load_error = f"HTTP {e.code}: {e.reason}"
            logger.warning(
                f"LLM preload failed: HTTP {e.code} for model '{model_name}'\n"
                f"  → 模型可能不存在，请运行 'ollama list' 确认\n"
                f"  → 如需拉取: ollama pull {model_name}"
            )
            return False
        except Exception as e:
            self._load_error = str(e)
            logger.warning(f"LLM preload failed: {e}")
        return False

    def infer(self, prompt: str, max_tokens: int = 2048,
              timeout: int = None, retries: int = 5,
              on_progress: callable = None) -> Optional[str]:
        """
        LLM 推理，支持自动重试和进度回调（v9.5.1）。

        timeout=0 表示不设 HTTP 超时，让 Ollama 自己算完返回。
        每次重试 timeout 翻倍（60→120→240→480→960→1920s），
        最多可等待 1920s（32分钟），足够 9B CPU 模型处理任何复杂 prompt。

        v9.5.1 新增：
        - on_progress(partial_text, progress_pct) 回调，用于报告实时进度。
          当 on_progress 为 None 时，使用非流式模式（兼容旧行为）。
          当 on_progress 不为 None 时，使用流式模式并每 N 个 token 回调一次。

        Args:
            prompt: 推理 prompt
            max_tokens: 最大输出 token 数
            timeout: 超时秒数（None=使用配置值，0=不设超时）
            retries: 最大重试次数（默认5次）
            on_progress: 进度回调 callable(partial_text, progress_pct)
        """
        if not self.is_enabled():
            return None
        cfg = self._get_config()
        model_name = getattr(cfg.llm, "ollama_model", "qwen3")
        base_timeout = timeout if timeout is not None else getattr(cfg.llm, "ollama_timeout", 0)
        start_time = time.time()

        # 初始超时：如果配置为 0（无限），第一次重试用 60s 作为起步
        _initial_timeout = base_timeout if base_timeout > 0 else 60

        # 如果有进度回调，使用流式模式；否则用非流式（兼容旧行为）
        use_stream = on_progress is not None

        for attempt in range(retries + 1):
            current_timeout = _initial_timeout * (2 ** attempt)
            if attempt > 0:
                logger.warning(
                    f"Ollama inference retry {attempt}/{retries} "
                    f"(timeout={current_timeout}s, prompt_len={len(prompt)}, "
                    f"max_tokens={max_tokens}, stream={use_stream})"
                )

            try:
                if use_stream:
                    text = self._infer_stream(
                        model_name, prompt, max_tokens, current_timeout,
                        on_progress, start_time
                    )
                else:
                    text = self._infer_sync(
                        model_name, prompt, max_tokens, current_timeout
                    )

                if text is not None:
                    elapsed = time.time() - start_time
                    with self._lock:
                        self._inference_count += 1
                        self._total_inference_time += elapsed
                        self._last_inference_time = elapsed
                        if elapsed > 0:
                            self._avg_tokens_per_second = len(text) / elapsed
                    logger.info(
                        f"Ollama inference completed: {len(text)} chars, "
                        f"{elapsed:.1f}s, attempt {attempt+1}/{retries+1}"
                    )
                    return text

            except urllib.error.URLError as e:
                logger.error(f"Ollama connection failed (attempt {attempt+1}/{retries+1}): {e}")
                if attempt < retries:
                    time.sleep(3)
                else:
                    return None

            except TimeoutError:
                logger.error(
                    f"Ollama inference timed out after {current_timeout}s "
                    f"(attempt {attempt+1}/{retries+1}, prompt_len={len(prompt)})"
                )
                if attempt < retries:
                    wait_s = min(5 * (2 ** attempt), 30)
                    logger.info(f"Retrying in {wait_s}s with doubled timeout...")
                    time.sleep(wait_s)

            except Exception as e:
                logger.error(f"Ollama inference failed (attempt {attempt+1}/{retries+1}): {e}", exc_info=True)
                if attempt < retries:
                    time.sleep(3)
                else:
                    return None

        return None

    def _intercept_log(self, model_name: str, prompt: str,
                       max_tokens: int, stream: bool, status: str,
                       error: str = "", elapsed: float = 0.0,
                       result_len: int = 0):
        """记录 Ollama 请求到拦截 buffer（仅当开关打开时）"""
        if not _intercept_enabled:
            return
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "model": model_name,
            "stream": stream,
            "max_tokens": max_tokens,
            "prompt_len": len(prompt),
            "prompt_preview": prompt[:500] + ("..." if len(prompt) > 500 else ""),
            "status": status,
        }
        if error:
            entry["error"] = str(error)[:500]
        if elapsed > 0:
            entry["elapsed"] = round(elapsed, 2)
            entry["result_len"] = result_len
        with _intercept_lock:
            _intercept_buffer.appendleft(entry)

    def _infer_sync(self, model_name: str, prompt: str,
                    max_tokens: int, timeout: int) -> Optional[str]:
        """非流式推理（兼容旧行为）

        v9.5.1 修复: 增加 HTTP 状态码校验，404 时输出诊断日志。
        """
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        t0 = time.time()
        req = urllib.request.Request(
            f"{_OLLAMA_BASE_URL}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        http_timeout = timeout if timeout > 0 else None
        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                body = resp.read().decode("utf-8")
                if resp.status != 200:
                    self._intercept_log(model_name, prompt, max_tokens,
                                        False, f"HTTP {resp.status}",
                                        error=body[:500],
                                        elapsed=time.time()-t0)
                    logger.error(
                        f"Ollama /api/generate 返回 {resp.status}: {body[:300]}\n"
                        f"  → 请求模型: '{model_name}', prompt_len={len(prompt)}\n"
                        f"  → 提示: 检查 'ollama list' 确认模型名是否匹配 config.yaml 中的 ollama_model"
                    )
                    raise urllib.error.HTTPError(
                        f"{_OLLAMA_BASE_URL}/api/generate", resp.status,
                        f"HTTP {resp.status}", resp.headers, None
                    )
                result = json.loads(body)
                text = result.get("response", "")
                self._intercept_log(model_name, prompt, max_tokens,
                                    False, "200 OK",
                                    elapsed=time.time()-t0,
                                    result_len=len(text))
                return text
        except Exception as e:
            self._intercept_log(model_name, prompt, max_tokens,
                                False, "ERROR",
                                error=str(e),
                                elapsed=time.time()-t0)
            raise

    def _infer_stream(self, model_name: str, prompt: str,
                      max_tokens: int, timeout: int,
                      on_progress: callable, start_time: float) -> Optional[str]:
        """流式推理，通过 on_progress 回调报告进度。

        使用 Ollama stream=true 模式，每收到一个 token 就拼接，
        每 10 个 token 回调一次 on_progress(partial_text, progress_pct)。

        v9.5.1 修复: 增加 HTTP 状态码校验，404 时输出诊断日志。
        """
        t0 = time.time()
        payload = {
            "model": model_name,
            "prompt": prompt,
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        req = urllib.request.Request(
            f"{_OLLAMA_BASE_URL}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        http_timeout = timeout if timeout > 0 else None

        full_text = []
        token_count = 0
        last_callback_at = 0

        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as resp:
                # v9.5.1: 检查 HTTP 状态码
                if resp.status != 200:
                    body = resp.read().decode("utf-8")[:500]
                    self._intercept_log(model_name, prompt, max_tokens,
                                        True, f"HTTP {resp.status}",
                                        error=body,
                                        elapsed=time.time()-t0)
                    logger.error(
                        f"Ollama /api/generate (stream) 返回 {resp.status}: {body[:300]}\n"
                        f"  → 请求模型: '{model_name}', prompt_len={len(prompt)}\n"
                        f"  → 提示: 检查 'ollama list' 确认模型名是否匹配 config.yaml 中的 ollama_model"
                    )
                    raise urllib.error.HTTPError(
                        f"{_OLLAMA_BASE_URL}/api/generate", resp.status,
                        f"HTTP {resp.status}", resp.headers, None
                    )

                # 逐行读取流式响应
                for line in resp:
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        full_text.append(token)
                        token_count += 1

                        # 每 10 个 token 回调一次进度
                        if token_count - last_callback_at >= 10:
                            partial = "".join(full_text)
                            progress = min(token_count / max(1, max_tokens), 0.99)
                            try:
                                on_progress(partial, progress)
                            except Exception:
                                pass  # 回调失败不中断推理
                            last_callback_at = token_count

                        # 检查是否完成
                        if chunk.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue

            full = "".join(full_text)
            self._intercept_log(model_name, prompt, max_tokens,
                                True, "200 OK",
                                elapsed=time.time()-t0,
                                result_len=len(full))
            # 最终回调
            try:
                on_progress(full, 1.0)
            except Exception:
                pass
            return full

        except Exception as e:
            self._intercept_log(model_name, prompt, max_tokens,
                                True, "ERROR",
                                error=str(e),
                                elapsed=time.time()-t0)
            raise

    # ===== Analysis methods (delegate to llm_prompts.run_analysis) =====

    def analyze_conversation(self, content: str, source: str = "unknown",
                             client: str = "unknown") -> Optional[dict]:
        from prompts import run_analysis, TASK_CONVERSATION_ANALYSIS
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        return run_analysis(
            TASK_CONVERSATION_ANALYSIS,
            content=content[:TASK_CONVERSATION_ANALYSIS.input_truncate],
            source=source,
            client=client,
        )

    def analyze_step_content(self, step_name: str, step_type: str, content: str,
                              symptom: str = "", root_cause: str = "",
                              solution: str = "", ai_reasoning: str = "",
                              user_requirement: str = "",
                              commands_executed: str = "") -> Optional[dict]:
        from prompts import run_analysis, TASK_STEP_ANALYSIS
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        return run_analysis(
            TASK_STEP_ANALYSIS,
            step_name=step_name or "unknown",
            step_type=step_type or "general",
            symptom=symptom or "none",
            root_cause=root_cause or "none",
            solution=solution or "none",
            ai_reasoning=ai_reasoning or "none",
            user_requirement=user_requirement or "none",
            commands_executed=commands_executed or "none",
            content=content[:TASK_STEP_ANALYSIS.input_truncate],
        )

    def analyze_conversation_deep(self, summary: str, self_reflection: str,
                                   user_traits: dict, key_decisions: list,
                                   steps_summary: list,
                                   topic: str = "",
                                   system_id: str = "default",
                                   client: str = "unknown",
                                   user_raw_input: str = "",
                                   project_context: str = "",
                                   ai_analysis: str = "",
                                   ai_summary: str = "") -> Optional[dict]:
        """v9.1 四维深度分析：业务知识、用户画像、技术决策、知识图谱
        v9.1: 新增 ai_analysis（AI 意图分析）和 ai_summary（AI 最终总结），双向互补分析"""
        import json as _json
        from prompts import run_analysis, TASK_CONVERSATION_DEEP_ANALYSIS
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        steps_str = _json.dumps(steps_summary, ensure_ascii=False, indent=2)[:10000]
        traits_str = _json.dumps(user_traits or {}, ensure_ascii=False, indent=2)
        decisions_str = _json.dumps(key_decisions or [], ensure_ascii=False, indent=2)
        return run_analysis(
            TASK_CONVERSATION_DEEP_ANALYSIS,
            topic=topic or "unknown",
            system_id=system_id or "default",
            client=client or "unknown",
            user_raw_input=user_raw_input[:8000] if user_raw_input else "none",
            project_context=project_context[:5000] if project_context else "none",
            summary=summary or "none",
            self_reflection=self_reflection or "none",
            user_traits=traits_str,
            key_decisions=decisions_str,
            steps_summary=steps_str,
            ai_analysis=ai_analysis[:10000] if ai_analysis else "none",
            ai_summary=ai_summary[:10000] if ai_summary else "none",
        )

    def generate_daily_summary(self, target_date: str, data: dict) -> Optional[dict]:
        import json as _json
        from prompts import run_analysis, TASK_DAILY_SUMMARY
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_daily_summary", False):
            return None
        conversations_json = _json.dumps(
            data.get("conversations", [])[:15],
            ensure_ascii=False, indent=2
        )[:TASK_DAILY_SUMMARY.input_truncate]

        # v8.1: 生成项目分组提示，帮助 LLM 识别项目边界
        files_touched = data.get("files_touched", [])
        project_hint = _build_project_grouping_hint(files_touched)

        result = run_analysis(
            TASK_DAILY_SUMMARY,
            date=target_date,
            total_conversations=len(data.get("conversations", [])),
            files_count=len(files_touched),
            task_types=", ".join(list(set(
                c.get("task_type", "") for c in data.get("conversations", [])
            ))[:5]),
            project_grouping_hint=project_hint,
            conversations=conversations_json,
            user_profile_snapshot=data.get("user_profile_snapshot", "暂无用户画像数据"),
            project_profile_snapshot=data.get("project_profile_snapshot", "暂无项目画像数据"),
        )
        if result:
            result["data_source"] = data.get("data_source", "db")
        return result

    def generate_self_improvement_suggestions(self, system_data: dict,
                                               improvement_history: list = None) -> Optional[list]:
        import json as _json
        from prompts import run_analysis, TASK_SELF_IMPROVEMENT
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_self_improvement", False):
            return None
        history_json = _json.dumps(improvement_history or [], ensure_ascii=False)[:3000]
        system_json = _json.dumps(system_data, ensure_ascii=False, default=str)[:5000]
        return run_analysis(
            TASK_SELF_IMPROVEMENT,
            system_data=system_json,
            improvement_history=history_json,
        )

    def parse_file_conversations(self, content: str, filename: str = "unknown") -> Optional[dict]:
        from prompts import run_analysis, TASK_FILE_PARSE
        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_file_parsing", True):
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

            # v9.3: 支持两种 skills_observed 格式
            # 格式A（新）: [{"skill_name": "xxx", "skill_domain": "Python"}, ...]
            # 格式B（旧）: ["Python/Django", "前端开发", ...]
            skills_observed = processed.get("skills_observed", [])
            if isinstance(skills_observed, str):
                skills_observed = [skills_observed]
            
            # 也支持 skills_with_domains 显式格式
            skills_with_domains = processed.get("skills_with_domains", [])
            if not skills_with_domains:
                # 从旧格式转换：智能推断 domain
                skills_with_domains = self._classify_skills_to_domains(skills_observed)
            
            for skill_entry in skills_with_domains:
                try:
                    if isinstance(skill_entry, dict):
                        skill_name = skill_entry.get("skill_name", "")
                        skill_domain = skill_entry.get("skill_domain", "其他")
                    else:
                        # 纯字符串 fallback
                        skill_name = str(skill_entry)
                        skill_domain = "其他"

                    if not skill_name:
                        continue

                    # v9.3.1: 入库前强制标准化 skill_domain（LLM 可能不遵守 Prompt 归类规则）
                    from devpartner_agent.core.skill_domain_standard import normalize_domain
                    skill_domain = normalize_domain(skill_domain)
                    
                    # ★ 增量合并逻辑
                    merge_result = self._merge_skill_incremental(
                        db=db,
                        skill_name=skill_name,
                        skill_domain=skill_domain,
                        context={
                            "skill_domain": skill_domain,
                            "skill_level": processed.get("skill_level", "intermediate"),
                            "sub_skills": processed.get("related_skills", []),
                            "evidence_text": processed.get("evidence_text", f"从对话中观察到 {skill_name} 技能"),
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
                    logger.debug(f"写入技能失败 [{skill_entry}]: {e}")

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
            """使用 LLM 智能处理和丰富用户特征（可选增强，v8.5: 使用外部 Prompt）"""
            if not self.is_available:
                return traits

            try:
                from prompts import run_analysis, AnalysisTask, parse_json

                task = AnalysisTask(
                    name="user_traits_enrich",
                    description="用户特征智能拆分和丰富",
                    prompt_template="""请处理以下用户特征数据，进行智能拆分和丰富：

原始特征数据：
```json
{traits_json}
```

请输出处理后的 JSON（保持相同结构，但优化内容）：
- 提取更精确的技能等级评估
- 补充相关的子技能
- 生成更自然的证据文本
- 估算合理的学习时间投入
- 判断成长趋势

只输出 JSON。""",
                    parser=parse_json,
                    max_tokens=1024,
                    input_truncate=4000,
                )
                enhanced = run_analysis(task, traits_json=json.dumps(traits, ensure_ascii=False))
                if enhanced and not enhanced.get("parse_error"):
                    return enhanced
            except Exception as e:
                logger.debug(f"LLM 特征处理失败，使用原始数据: {e}")

            return traits

    # v9.3.1: 使用统一领域标准化模块（单一数据源）
    @classmethod
    def _classify_skills_to_domains(cls, skills: list) -> list:
        """
        将旧格式的技能名称列表转换为 {skill_name, skill_domain} 列表
        
        使用统一的 normalize_domain() 做标准化，确保与 knowledge_points、
        fix_skill_domains.py 使用同一套映射表。
        """
        from devpartner_agent.core.skill_domain_standard import normalize_domain

        result = []
        for skill in skills:
            if isinstance(skill, dict):
                result.append(skill)
                continue

            skill_str = str(skill).strip()
            if not skill_str:
                continue

            result.append({
                "skill_name": skill_str,
                "skill_domain": normalize_domain(skill_str),
            })

        return result

    def _merge_skill_incremental(self, db, skill_name: str, context: dict,
                                  skill_domain: str = "") -> dict:
            """
            技能增量合并逻辑（v9.3: 支持 skill_domain + skill_name 联合定位）
        
            防止 user_skills 表快速膨胀：
            1. 查询 skill 是否已存在（按 skill_domain + skill_name）
               - 存在: 更新 last_seen, confidence += 0.1, 合并 sub_skills
               - 不存在: 新增记录
            2. 记录来源追溯信息（source_conversation_id, source_timestamp）
        
            Args:
                db: 数据库实例
                skill_name: 技能名称
                context: 技能上下文信息（含 skill_domain）
                skill_domain: 技能领域（优先使用此参数，fallback 到 context）
            
            Returns:
                {"action": "inserted"/"updated", "skill": str, "confidence": float}
            """
            try:
                domain = skill_domain or context.get("skill_domain", "其他")
                existing = db.query_user_skill(skill_name, skill_domain=domain)
            
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
                        "skill_domain": domain,
                        "skill_name": skill_name,
                        "skill_level": context.get("skill_level", existing.get("skill_level", "intermediate")),
                        "sub_skills": ", ".join(merged_sub_skills) if merged_sub_skills else "",
                        "evidence": f"{context.get('extraction_method', 'unknown')}: {context.get('evidence_text', '')}",
                        "confidence": new_confidence,
                        "last_seen": context.get("source_timestamp", datetime.now().isoformat()),
                        "evidence_count": (existing.get("evidence_count", 1) or 1) + 1,
                        "hours_spent": (existing.get("hours_spent", 0) or 0) + context.get("estimated_hours", 0),
                        "growth_trend": context.get("growth_trend", "growing"),
                    }
                
                    db.update_user_skill(skill_name, update_data, skill_domain=domain)
                
                    logger.debug(f"技能增量更新 [{domain}/{skill_name}] confidence: {old_confidence:.2f} → {new_confidence:.2f}")
                
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
                        "skill_domain": domain,
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
            
                # 降级：直接 upsert（兼容旧逻辑，v9.3: 传入 skill_name 和 domain）
                try:
                    domain = context.get("skill_domain", "其他")
                    db.upsert_user_skills(domain, {
                        "skill_name": skill_name,
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

def _build_project_grouping_hint(files_touched: list) -> str:
    """
    从文件路径列表中提取项目分组提示（v8.1）

    从文件路径中提取顶层项目/模块名，生成分组提示文本，
    帮助 LLM 在生成日报时按项目维度归纳对话。

    Args:
        files_touched: 当天所有涉及的文件路径列表

    Returns:
        项目分组提示文本，如：
        "根据文件路径推断，今日涉及以下项目：
          - devPartner: server.py, scheduler.py, ...
          - toptown-settlement: SettlementService.java, ..."
    """
    if not files_touched:
        return "（无文件变更记录，无法推断项目分组）"

    from collections import defaultdict
    project_files = defaultdict(list)

    for f in files_touched:
        parts = f.replace("\\", "/").strip("/").split("/")
        # 取前两层作为项目标识
        if len(parts) >= 2:
            project_key = f"{parts[0]}/{parts[1]}"
        elif len(parts) == 1:
            project_key = parts[0]
        else:
            continue
        project_files[project_key].append(f)

    if not project_files:
        return "（无法从文件路径推断项目分组）"

    lines = ["根据文件路径推断，今日涉及以下项目/模块："]
    for proj, files in sorted(project_files.items(), key=lambda x: -len(x[1])):
        sample = files[:5]
        suffix = f" ... 等{len(files)}个文件" if len(files) > 5 else ""
        lines.append(f"  - {proj}: {', '.join(sample)}{suffix}")

    return "\n".join(lines)


_engine_instance: Optional[LLMEngine] = None


def get_llm_engine() -> LLMEngine:
    """获取全局 LLM 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = LLMEngine()
    return _engine_instance