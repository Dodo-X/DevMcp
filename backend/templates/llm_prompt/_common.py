import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def compact_json(obj, max_chars: int = 0) -> str:
    """压缩 JSON 序列化：去掉 indent 和多余空格，中文不转义。

    与 json.dumps(indent=2) 相比，可节省 20-35% 字符数。
    LLM 不需要漂亮缩进来理解 JSON，它解析语义结构。

    Args:
        obj: 待序列化的 dict/list
        max_chars: 如果 > 0，返回结果会截断到此长度（按字符边界）

    Returns:
        紧凑 JSON 字符串
    """
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if max_chars > 0 and len(text) > max_chars:
        text = smart_truncate(text, max_chars)
    return text


def smart_truncate(text: str, max_chars: int, min_chars: int = 0) -> str:
    """智能截断：优先按段落边界，其次按句子边界，最后按字符。

    保证不截断到句子中间，避免 prompt 末尾出现不完整的内容。
    如果 text 长度 < min_chars，不做截断。

    Args:
        text: 待截断文本
        max_chars: 最大字符数
        min_chars: 最小保留字符数（低于此值不截断）

    Returns:
        截断后的文本（如果截断，末尾添加提示）
    """
    if len(text) <= max_chars:
        return text

    # 在第 max_chars 字符范围内找最佳截断点
    # 策略1: 找最近的段落边界（双换行）
    chunk = text[:max_chars]
    para_break = chunk.rfind("\n\n")
    if para_break > max_chars * 0.5:
        return text[:para_break] + "\n\n[... 后续内容已截断 ...]"

    # 策略2: 找最近的句子边界（句号、问号、感叹号后跟换行或空格）
    for punct in ["。\n", "。", ".\n", ". ", "!\n", "! ", "?\n", "? "]:
        sent_break = chunk.rfind(punct)
        if sent_break > max_chars * 0.4:
            return text[: sent_break + len(punct.rstrip())] + "\n[... 后续内容已截断 ...]"

    # 策略3: 找最近的换行
    line_break = chunk.rfind("\n")
    if line_break > max_chars * 0.3:
        return text[:line_break] + "\n[... 后续内容已截断 ...]"

    # 兜底: 硬截断（但在 max_chars - 20 处截，留空间给提示）
    return text[: max_chars - 20] + "\n[... 后续内容已截断 ...]"


def parse_json(raw: str, fallback: dict = None):
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
        if isinstance(result, (dict, list)):
            return result
    except json.JSONDecodeError:
        pass

    # 尝试提取 markdown 代码块中的 JSON
    json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if json_match:
        try:
            result = json.loads(json_match.group(1).strip())
            if isinstance(result, (dict, list)):
                return result
        except json.JSONDecodeError:
            pass

    # 尝试找到第一个 { ... } 对象
    brace_start = raw.find("{")
    brace_end = raw.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            result = json.loads(raw[brace_start : brace_end + 1])
            if isinstance(result, (dict, list)):
                return result
        except json.JSONDecodeError:
            pass

    # 容错：修复尾部逗号
    try:
        cleaned = re.sub(r",\s*}", "}", raw)
        cleaned = re.sub(r",\s*]", "]", cleaned)
        result = json.loads(cleaned)
        if isinstance(result, (dict, list)):
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
    timeout: int = 0  # 0 = 使用配置默认值（重试自适应）
    feature_flag: str = ""


def run_analysis(
    task: AnalysisTask, on_progress: Callable = None, cancel_event=None, **kwargs
) -> dict | list | None:
    """
    执行 LLM 分析任务（统一入口）

    Args:
        task: 任务描述符
        on_progress: 进度回调 callable(partial_text, progress_pct)，用于流式推理进度报告
        cancel_event: threading.Event，外部取消信号（v9.5.3: task_queue 超时后通知 worker 停止）
        **kwargs: prompt 模板中的变量

    Returns:
        解析后的结果（dict 或 list），失败返回 None
    """
    from backend.core.llm_kernel.base_client import get_llm_engine

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

        # 智能截断：按语义边界截断，避免一刀切破坏数据完整性
        if len(prompt) > task.input_truncate:
            logger.warning(
                f"任务 {task.name} prompt 超长: {len(prompt)} > {task.input_truncate}，触发智能截断"
            )
            prompt = smart_truncate(prompt, task.input_truncate)

        # 推理（支持任务级 timeout，0=使用配置默认值）
        timeout = task.timeout if task.timeout > 0 else None
        raw = engine.infer(
            prompt,
            task.max_tokens,
            timeout=timeout,
            on_progress=on_progress,
            cancel_event=cancel_event,
        )
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
