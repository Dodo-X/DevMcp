import re
import json
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, List

logger = logging.getLogger(__name__)

def parse_json(raw: str, fallback: dict = None) -> Optional[dict]:
    """
    通用 JSON 解析器
    
    依次尝试：
    1. 直接解析
    2. 提取 markdown 代码块中的 JSON
    3. 提取第一个 { ... } 对象
    4. 容错修复（尾部逗号）
    
    Args:
        raw: LLM 返回的原始文本
        fallback: 解析失败时的默认返回值
        
    Returns:
        解析后的 dict，失败返回 fallback
    """
    if not raw:
        return fallback or {}

    # 尝试直接解析
    try:
        result = json.loads(raw)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试提取 markdown 代码块中的 JSON
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(1).strip())
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 尝试找到第一个 { ... } 对象
    brace_start = raw.find('{')
    brace_end = raw.rfind('}')
    if brace_start != -1 and brace_end > brace_start:
        try:
            result = json.loads(raw[brace_start:brace_end + 1])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    # 容错：修复尾部逗号
    try:
        cleaned = re.sub(r',\s*}', '}', raw)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        result = json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    logger.warning("无法解析 LLM JSON 响应，前200字符: %s", raw[:200])
    return fallback or {"raw_response": raw[:500], "parse_error": True}

def normalize_analysis(parsed: dict) -> dict:
    """标准化对话分析结果（含 user_traits 9 维度完整传递）"""
    raw_traits = parsed.get("user_traits", {})
    return {
        "skill_domains": parsed.get("skill_domains", []),
        "complexity": parsed.get("complexity", "medium"),
        "feedback_type": parsed.get("feedback_type", "none"),
        "user_traits": {
            "skills_observed": raw_traits.get("skills_observed", []),
            "behavior_notes": raw_traits.get("behavior_notes", ""),
            "mistakes": raw_traits.get("mistakes", []),
            "strengths": raw_traits.get("strengths", []),
            "communication_style": raw_traits.get("communication_style", ""),
            "decision_pattern": raw_traits.get("decision_pattern", ""),
            "tech_interests": raw_traits.get("tech_interests", []),
            "areas_for_growth": raw_traits.get("areas_for_growth", []),
            "emotional_state": raw_traits.get("emotional_state", "平静"),
            "learning_progress": raw_traits.get("learning_progress", ""),
        },
        "tool_gaps": parsed.get("tool_gaps", []),
        "summary": parsed.get("summary", ""),
    }

@dataclass
class AnalysisTask:
    """
    LLM 分析任务描述符
    
    将业务逻辑从引擎中解耦：
    - prompt_template: 如何构造 prompt
    - parser: 如何解析输出
    - max_tokens / input_truncate / timeout: 推理参数
    
    使用示例：
        task = TASK_CONVERSATION_ANALYSIS
        result = run_analysis(task, content="...", source="cursor")
    """
    name: str
    description: str
    prompt_template: str
    parser: Callable[[str], dict] = parse_json
    max_tokens: int = 2048
    input_truncate: int = 8000
    timeout: int = 0       # 0 = 使用配置默认值（重试自适应）
    feature_flag: str = ""

def run_analysis(task: AnalysisTask, on_progress: Callable = None, **kwargs) -> Optional[dict | list]:
    """
    执行 LLM 分析任务（统一入口）

    Args:
        task: 任务描述符
        on_progress: 进度回调 callable(partial_text, progress_pct)，用于流式推理进度报告
        **kwargs: prompt 模板中的变量

    Returns:
        解析后的结果（dict 或 list），失败返回 None
    """
    from devpartner_agent.core.llm_engine import get_llm_engine
    engine = get_llm_engine()

    if not engine.is_available():
        logger.debug(f"LLM 不可用，跳过任务: {task.name}")
        return None

    # 检查 feature flag
    if task.feature_flag:
        cfg = engine._get_config()
        if not getattr(cfg.llm, task.feature_flag, False):
            logger.debug(f"功能开关 {task.feature_flag} 未启用，跳过任务: {task.name}")
            return None

    try:
        # 构造 prompt
        prompt = task.prompt_template.format(**kwargs)

        # 截断
        if len(prompt) > task.input_truncate:
            prompt = prompt[:task.input_truncate] + "..."

        # 推理（支持任务级 timeout，0=使用配置默认值）
        timeout = task.timeout if task.timeout > 0 else None
        raw = engine.infer(prompt, task.max_tokens, timeout=timeout,
                           on_progress=on_progress)
        if not raw or len(raw.strip()) < 20:
            logger.warning(f"LLM 推理返回空或过短: {task.name}")
            return None

        # 解析
        result = task.parser(raw)
        if result is None or (isinstance(result, dict) and result.get("parse_error")):
            logger.warning(f"LLM 输出解析失败: {task.name}")
            return None

        return result

    except KeyError as e:
        logger.error(f"任务 {task.name} prompt 模板缺少变量: {e}")
        return None
    except Exception as e:
        logger.error(f"任务 {task.name} 执行失败: {e}", exc_info=True)
        return None