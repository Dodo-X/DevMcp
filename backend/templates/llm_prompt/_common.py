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


def compact_for_llm(text: str, max_chars: int = 4000) -> str:
    """将大段文本压缩为 LLM 友好的摘要格式。
    用于日报/周报/月报输入数据过大的场景 — 在 build prompt 之前先压缩。
    策略：保留前 max_chars 字符的完整内容，超出部分只保留前 200 字符作为摘要。
    """
    if not text:
        return "(无数据)"
    if len(text) <= max_chars:
        return text
    # 按段落切分，保留前 N 个段落的完整内容
    paragraphs = text.split("\n\n")
    result = []
    total = 0
    for i, p in enumerate(paragraphs):
        if total + len(p) <= max_chars:
            result.append(p)
            total += len(p) + 2  # +2 for \n\n
        else:
            # 当前段落超限：保留开头作为摘要
            remaining = max_chars - total
            if remaining > 100:
                result.append(p[:remaining] + "\n[... 摘要截断]")
            break
    if len(result) < len(paragraphs):
        result.append(f"\n[... 共 {len(paragraphs)} 段数据, 已截断到 {max_chars} 字符 ...]")
    return "\n\n".join(result)


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
    # 匹配 ```json ... ```，支持代码块内嵌反引号、截断无结尾等情况
    m = re.search(r"```(?:json)?\s*\n?(.*)", raw, re.DOTALL)
    if m:
        inner = m.group(1)
        # 尝试剥离尾部 ```
        end = inner.rfind("\n```")
        if end == -1:
            end = inner.rfind("```")
        if end != -1:
            inner = inner[:end]
        inner = inner.strip()
        try:
            result = json.loads(inner)
            if isinstance(result, (dict, list)):
                return result
        except json.JSONDecodeError:
            pass
        # 代码块内 JSON 解析失败 → 继续尝试后面的提取方法
        raw = inner  # 用剥离后的内容继续下面的提取

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


def extract_behavior_signals(
    user_raw_input: str,
    ai_analysis: str = "",
    topic: str = "",
    task_type: str = "",
) -> dict:
    """Python 代码替代 TASK_BEHAVIOR_SIGNALS LLM 调用。

    原来 LLM 做的所有事情都是简单的关键词/正则匹配，
    不需要浪费一次 LLM round-trip。直接在 Python 中完成，
    确定性 100%、延迟 0ms、token 消耗 0。

    Returns:
        dict: 与原 TASK_BEHAVIOR_SIGNALS 输出格式完全一致
    """
    from datetime import datetime

    raw = user_raw_input or ""
    ai = ai_analysis or ""

    # ── 关键词检测（从用户原始输入中检测） ──
    _ERROR_KEYWORDS = [
        "error",
        "错误",
        "exception",
        "异常",
        "bug",
        "崩溃",
        "crash",
        "failed",
        "失败",
        "traceback",
        "stacktrace",
        "报错",
    ]
    _DEBUG_KEYWORDS = [
        "debug",
        "调试",
        "排查",
        "定位",
        "log",
        "日志",
        "断点",
        "breakpoint",
        "调试器",
        "debugger",
        "print",
        "console.log",
    ]
    _DESIGN_KEYWORDS = [
        "设计",
        "架构",
        "design",
        "architecture",
        "模式",
        "pattern",
        "重构",
        "refactor",
        "规划",
        "方案",
    ]
    _OPTIMIZE_KEYWORDS = [
        "优化",
        "optimize",
        "性能",
        "performance",
        "提速",
        "加速",
        "瓶颈",
        "bottleneck",
        "慢",
        "slow",
    ]
    _LEARN_KEYWORDS = [
        "学习",
        "learn",
        "教程",
        "tutorial",
        "入门",
        "入门",
        "了解",
        "理解",
        "原理",
        "概念",
        "讲解",
    ]

    def _has_kw(text: str, keywords: list[str]) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in keywords)

    has_code_block = bool(re.search(r"```|`[^`]+`", raw))
    has_question_mark = "?" in raw or "？" in raw or "怎么" in raw or "如何" in raw
    has_error_keyword = _has_kw(raw, _ERROR_KEYWORDS)
    has_debug_keyword = _has_kw(raw, _DEBUG_KEYWORDS)
    has_design_keyword = _has_kw(raw, _DESIGN_KEYWORDS)
    has_optimize_keyword = _has_kw(raw, _OPTIMIZE_KEYWORDS)
    has_learn_keyword = _has_kw(raw, _LEARN_KEYWORDS)

    # ── 语言推断（从 AI 分析中推断） ──
    _LANG_MAP = {
        "python": "python",
        "django": "python",
        "flask": "python",
        "fastapi": "python",
        "pytest": "python",
        "pip": "python",
        "conda": "python",
        "javascript": "javascript",
        "js": "javascript",
        "typescript": "javascript",
        "ts": "javascript",
        "react": "javascript",
        "vue": "javascript",
        "angular": "javascript",
        "node": "javascript",
        "npm": "javascript",
        "java": "java",
        "spring": "java",
        "maven": "java",
        "gradle": "java",
        "kotlin": "java",
        "rust": "rust",
        "cargo": "rust",
        "go": "go",
        "golang": "go",
        "sql": "sql",
        "sqlite": "sql",
        "mysql": "sql",
        "postgres": "sql",
        "docker": "devops",
        "kubernetes": "devops",
        "k8s": "devops",
        "nginx": "devops",
        "linux": "devops",
        "git": "devops",
    }
    language_hints = []
    combined = (raw + " " + ai).lower()
    seen = set()
    for keyword, lang in _LANG_MAP.items():
        if keyword in combined and lang not in seen:
            language_hints.append(lang)
            seen.add(lang)
    if not language_hints:
        language_hints = ["unknown"]

    # ── 技术领域 ──
    _DOMAIN_KEYWORDS = {
        "Python": ["python", "django", "fastapi", "flask", "pytest", "pip", "conda"],
        "前端": [
            "react",
            "vue",
            "angular",
            "javascript",
            "typescript",
            "html",
            "css",
            "webpack",
            "vite",
        ],
        "AI/LLM": ["llm", "gpt", "ollama", "mcp", "prompt", "rag", "agent", "model", "transformer"],
        "DevOps": ["docker", "kubernetes", "nginx", "linux", "deploy", "ci/cd", "github actions"],
        "数据库": ["sql", "sqlite", "mysql", "postgres", "redis", "mongodb", "wal", "index"],
        "架构设计": [
            "architecture",
            "design",
            "pattern",
            "refactor",
            "microservice",
            "async",
            "concurrent",
        ],
        "通用工程": ["test", "debug", "security", "logging", "refactor", "review", "lint"],
    }
    tech_domain = "通用工程"
    for domain, kws in _DOMAIN_KEYWORDS.items():
        if any(kw in combined for kw in kws):
            tech_domain = domain
            break

    # ── 技能等级推断 ──
    skill_level = "intermediate"
    if any(w in combined for w in ["基础", "入门", "beginner", "新手", "简单", "hello world"]):
        skill_level = "beginner"
    elif any(w in combined for w in ["架构", "高级", "expert", "精通", "深入", "底层原理", "优化"]):
        skill_level = "advanced"

    # ── 紧迫度推断 ──
    urgency = "normal"
    if any(
        w in raw.lower()
        for w in ["紧急", "urgent", "尽快", "马上", "立刻", "急", "critical", "asap"]
    ):
        urgency = "urgent"

    return {
        "input_length": len(raw),
        "has_code_block": has_code_block,
        "has_question_mark": has_question_mark,
        "has_error_keyword": has_error_keyword,
        "has_debug_keyword": has_debug_keyword,
        "has_design_keyword": has_design_keyword,
        "has_optimize_keyword": has_optimize_keyword,
        "has_learn_keyword": has_learn_keyword,
        "language_hints": language_hints[:5],
        "tech_domain": tech_domain,
        "user_skill_level_hint": skill_level,
        "user_urgency": urgency,
        "generated_at": datetime.now().isoformat(),
        "source": "python_behavior_signals",
    }


def normalize_analysis(parsed: dict) -> dict:
    """标准化对话分析结果（v9.11 简化版：4 核心字段）

    user_traits 和 tool_gaps 已从 TASK_CONVERSATION_ANALYSIS 输出中移除
    （分别由 TASK_CONV_USER_PROFILE 和确定性 Python 逻辑处理）。
    此函数现仅处理 conversation_analysis 的简化输出 schema。
    """
    return {
        "summary": parsed.get("summary", ""),
        "skill_domains": parsed.get("skill_domains", []),
        "complexity": parsed.get("complexity", "medium"),
        "user_feedback": parsed.get("user_feedback", {}),
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
        # 自动压缩大文本参数（在 format 之前，避免 HTTP body 过大断开连接）
        budget = max(3000, task.input_truncate - 3000)  # 留 3000 给 prompt 模板
        compressed = {}
        for k, v in kwargs.items():
            if isinstance(v, str) and len(v) > budget // 2:
                compressed[k] = compact_for_llm(v, max(1000, budget // 3))
            else:
                compressed[k] = v
        kwargs = compressed

        # 构造 prompt
        prompt = task.prompt_template.format(**kwargs)

        # 二次截断保护
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
            retries=2,  # 连接断开时最多重试 2 次（总计 3 次）
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
