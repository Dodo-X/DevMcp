import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from backend.core.llm_kernel.llm_utils import (
    _get_thread_cancel_event,
    _intercept_buffer,
    _intercept_enabled,
    _intercept_lock,
)

logger = logging.getLogger(__name__)

_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")

# v9.5.6: Ollama /api/generate 响应中每行都包含 "context" 字段
# （大型 int64 数组，用于多轮对话状态）。我们不需要多轮对话，
# 使用正则直接提取 response/done 字段，不解析整个 JSON，
# context 数组完全不进入 Python 内存。
_RESPONSE_RE = re.compile(r'"response":"((?:[^"\\]|\\.)*)"')
_DONE_RE = re.compile(r'"done":(true|false)')


def _parse_ollama_response(line: str):
    """解析 Ollama 流式响应行，提取 response 和 done 字段。
    优先使用 json.loads 正确解码转义序列（如 \\\"→\"），
    失败时 fallback 到零依赖正则。
    Returns: (token: str, is_done: bool)
    """
    try:
        obj = json.loads(line)
        return obj.get("response", ""), obj.get("done", False)
    except (json.JSONDecodeError, Exception):
        resp_match = _RESPONSE_RE.search(line)
        done_match = _DONE_RE.search(line)
        token = resp_match.group(1) if resp_match else ""
        is_done = done_match and done_match.group(1) == "true"
        return token, is_done


# ── v9.5.2 模型内存预估（GB）──
# 用于 preload() 时检查系统可用内存是否足够加载模型
_MODEL_MEMORY_ESTIMATE_GB = {
    "7b": 5.5,
    "8b": 6.0,
    "9b": 7.0,
    "13b": 10.0,
    "14b": 11.0,
    "32b": 24.0,
    "70b": 48.0,
}
_MODEL_MEMORY_DEFAULT_GB = 6.0  # 无法匹配时的保守估计


def _get_free_memory_gb() -> float:
    """获取系统当前可用物理内存（GB）"""
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.ullAvailPhys / (1024**3)
    except Exception:
        logger.warning("_get_free_memory_gb: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        return -1.0  # 无法获取时跳过检查


def _estimate_model_memory_gb(model_name: str) -> float:
    """根据模型名估算所需内存（GB）"""
    lower = model_name.lower()
    for size_key, est_gb in _MODEL_MEMORY_ESTIMATE_GB.items():
        if size_key in lower:
            return est_gb
    return _MODEL_MEMORY_DEFAULT_GB


class LLMEngine:
    """统一 LLM 推理引擎 + 业务方法"""

    def __init__(self):
        self._lock = threading.Lock()
        self._inference_count = 0
        self._total_inference_time = 0.0
        self._last_inference_time = 0.0
        self._avg_tokens_per_second = 0.0
        self._load_error: str | None = None

    def _get_config(self):
        from foundation.config.app_settings import get_config

        return get_config()

    def is_enabled(self) -> bool:
        cfg = self._get_config()
        return getattr(cfg.llm, "enabled", False) if hasattr(cfg, "llm") else False

    def is_available(self, quick: bool = True) -> bool:
        """检查 Ollama 是否可用。

        quick=True（默认）: 只检查 /api/tags（轻量，不加载模型）。
        quick=False: 发一个短 prompt ping /api/generate，验证推理引擎是否真的能工作。
                     用于 Dashboard "重新检查" 按钮和 preload() 之后的二次验证。
        """
        if not self.is_enabled():
            return False
        try:
            req = urllib.request.Request(f"{_OLLAMA_BASE_URL}/api/tags", method="GET")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    return False
        except Exception:
            logger.warning(
                "LLMEngine.is_available: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            return False

        # 快速模式到此为止
        if quick:
            return True

        # ── 深度健康检查：ping /api/generate ──
        try:
            cfg = self._get_config()
            model_name = getattr(cfg.llm, "ollama_model", "qwen3")
            payload = json.dumps(
                {
                    "model": model_name,
                    "prompt": "OK",
                    "stream": False,
                    "options": {"num_predict": 1},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{_OLLAMA_BASE_URL}/api/generate",
                data=payload,
                method="POST",
            )
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    result = json.loads(resp.read().decode("utf-8"))
                    if result.get("response"):
                        self._load_error = None  # 推理正常，清除旧错误
                        return True
                    else:
                        self._load_error = "/api/generate 返回空响应"
                        logger.warning("LLM deep health check: empty response from /api/generate")
                        return False
                else:
                    self._load_error = f"/api/generate HTTP {resp.status}"
                    return False
        except Exception as e:
            self._load_error = f"推理引擎不可用: {str(e)[:200]}"
            logger.warning(f"LLM deep health check failed: {e}")
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
        """v9.5.2: 增强预加载 — 内存检查 + 模型验证 + 推理健康检查。

        1. 检查系统可用内存是否足够加载模型
        2. 调用 Ollama /api/show 验证模型是否存在
        3. 发短 prompt ping /api/generate 验证推理引擎正常
        任一失败则返回 False 并设置 _load_error。
        """
        if not self.is_enabled():
            self._load_error = "Ollama not enabled"
            return False

        cfg = self._get_config()
        model_name = getattr(cfg.llm, "ollama_model", "qwen3")

        # ── 步骤 1: 内存检查 ──
        free_gb = _get_free_memory_gb()
        est_gb = _estimate_model_memory_gb(model_name)
        if free_gb > 0 and free_gb < est_gb * 0.8:
            self._load_error = (
                f"系统可用内存不足: {free_gb:.1f}GB 可用, "
                f"模型预估需要 ~{est_gb:.1f}GB "
                f"(模型: {model_name})"
            )
            logger.warning(
                f"LLM preload: 内存不足 — {free_gb:.1f}GB 可用, "
                f"模型需 ~{est_gb:.1f}GB\n"
                f"  → 建议: 1) 关闭其他应用释放内存\n"
                f"  →       2) 或换更小的模型 (如 3b/1.5b)"
            )
            return False
        elif free_gb > 0:
            logger.info(
                f"LLM preload: 内存检查通过 ({free_gb:.1f}GB 可用, 模型预估 ~{est_gb:.1f}GB)"
            )

        # ── 步骤 2: 模型存在性验证 ──
        try:
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

        # ── 步骤 3: 推理健康检查（ping /api/generate）──
        if not self.is_available(quick=False):
            logger.warning(
                f"LLM preload: 模型 '{model_name}' 存在但推理引擎不可用\n"
                f"  → 错误: {self._load_error}\n"
                f"  → 可能原因: 1) 内存不足导致模型加载卡死\n"
                f"  →          2) 之前的推理请求未正常结束\n"
                f"  → 建议: 重启 Ollama 服务后重试"
            )
            return False

        self._load_error = None
        logger.info(f"LLM preload: 全部检查通过 — 模型 '{model_name}' 就绪")
        return True

    def recheck(self) -> dict:
        """v9.5.2: 清除陈旧的 load_error 并重新验证模型可用性。

        先调用 preload()（内存+模型名+推理三步检查），
        如果 preload() 通过但之前有 load_error，再跑一次深度健康检查确认。
        返回当前真实状态供 Dashboard 展示。
        """
        self._load_error = None
        ok = self.preload()
        status = self.get_status()
        return {"success": ok, **status}

    def infer(
        self,
        prompt: str,
        max_tokens: int = 2048,
        timeout: int = None,
        retries: int = 1,
        on_progress: callable = None,
        cancel_event: threading.Event = None,
    ) -> str | None:
        """
        LLM 推理，支持自动重试和进度回调（v9.5.3 优化）。

        v9.5.3 变更：不再做翻倍重试。CPU 推理本就慢，翻倍重试只会
        把已经超时的请求重新排队再跑一次，浪费 Ollama 资源。
        改为：固定 HTTP 超时 + 最多 1 次重试，外部可通过 cancel_event
        主动取消（用于 task_queue 超时后真正中断 worker）。
        同时自动检测线程局部的取消事件（_cancel_event_per_thread）。

        Args:
            prompt: 推理 prompt
            max_tokens: 最大输出 token 数
            timeout: 超时秒数（None=使用配置值，0=不设超时）
            retries: 最大重试次数（默认1次，即总共最多2次尝试）
            on_progress: 进度回调 callable(partial_text, progress_pct)
            cancel_event: 外部取消信号，set() 后立即中断推理
        """
        if not self.is_enabled():
            return None

        # 合并取消事件：优先用显式传入的，其次用线程局部的
        _effective_cancel = cancel_event or _get_thread_cancel_event()

        cfg = self._get_config()
        model_name = getattr(cfg.llm, "ollama_model", "qwen3")
        start_time = time.time()

        # 长任务模式：撤销 HTTP 超时，由 cancel_event 主动控制生命周期
        # Ollama stream 模式下 3 小时连续生成不超时，依赖心跳机制确认活性
        http_timeout = None  # 无限制 — 长报告可达 3 小时

        # 统一走 stream 模式：强制 Ollama 持续推送，天然心跳 + 不超时
        use_stream = True

        for attempt in range(retries + 1):
            # 检查取消信号
            if _effective_cancel and _effective_cancel.is_set():
                logger.warning(f"Ollama inference cancelled (attempt {attempt + 1})")
                return None

            if attempt > 0:
                logger.warning(
                    f"Ollama inference retry {attempt}/{retries} "
                    f"(timeout={http_timeout}s, prompt_len={len(prompt)}, "
                    f"max_tokens={max_tokens}, stream={use_stream})"
                )

            try:
                if use_stream:
                    text = self._infer_stream(
                        model_name, prompt, max_tokens, http_timeout, on_progress, start_time
                    )
                else:
                    text = self._infer_sync(model_name, prompt, max_tokens, http_timeout)

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
                        f"{elapsed:.1f}s, attempt {attempt + 1}/{retries + 1}"
                    )
                    return text

            except urllib.error.URLError as e:
                logger.error(f"Ollama connection failed (attempt {attempt + 1}/{retries + 1}): {e}")
                if attempt < retries and not (_effective_cancel and _effective_cancel.is_set()):
                    time.sleep(3 * (attempt + 1))  # 指数退避: 3s, 6s, 9s
                else:
                    return None

            except (ConnectionResetError, ConnectionAbortedError, ConnectionError) as e:
                logger.error(
                    f"Ollama connection reset (attempt {attempt + 1}/{retries + 1}): {e}"
                    f" — prompt_len={len(prompt)}"
                )
                if attempt < retries and not (_effective_cancel and _effective_cancel.is_set()):
                    time.sleep(5 * (attempt + 1))
                else:
                    return None

            except TimeoutError:
                logger.error(
                    f"Ollama inference timed out after {http_timeout}s "
                    f"(attempt {attempt + 1}/{retries + 1}, prompt_len={len(prompt)})"
                )
                if attempt < retries and not (_effective_cancel and _effective_cancel.is_set()):
                    time.sleep(5)
                else:
                    return None

            except Exception as e:
                logger.error(
                    f"Ollama inference failed (attempt {attempt + 1}/{retries + 1}): {e}",
                    exc_info=True,
                )
                if attempt < retries and not (_effective_cancel and _effective_cancel.is_set()):
                    time.sleep(3)
                else:
                    return None

        return None

    def _intercept_log(
        self,
        model_name: str,
        prompt: str,
        max_tokens: int,
        stream: bool,
        status: str,
        error: str = "",
        elapsed: float = 0.0,
        result_len: int = 0,
        request_json: dict = None,
    ):
        """记录 Ollama 请求到拦截 buffer（仅当开关打开时）"""
        if not _intercept_enabled:
            return
        # 如果没有传入 request_json，从参数构建
        if request_json is None:
            request_json = {
                "model": model_name,
                "prompt": prompt[:5000] + ("..." if len(prompt) > 5000 else ""),
                "stream": stream,
                "options": {"num_predict": max_tokens},
            }
        entry = {
            "timestamp": time.strftime("%H:%M:%S"),
            "model": model_name,
            "stream": stream,
            "max_tokens": max_tokens,
            "prompt_len": len(prompt),
            "prompt_preview": prompt[:200] + ("..." if len(prompt) > 200 else ""),
            "request_json": request_json,
            "status": status,
        }
        if error:
            entry["error"] = str(error)[:500]
        if elapsed > 0:
            entry["elapsed"] = round(elapsed, 2)
            entry["result_len"] = result_len
        with _intercept_lock:
            _intercept_buffer.appendleft(entry)

    def _infer_sync(
        self, model_name: str, prompt: str, max_tokens: int, timeout: int
    ) -> str | None:
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
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        http_timeout = timeout if timeout > 0 else None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                if resp.status != 200:
                    self._intercept_log(
                        model_name,
                        prompt,
                        max_tokens,
                        False,
                        f"HTTP {resp.status}",
                        error=body[:500],
                        elapsed=time.time() - t0,
                        request_json=payload,
                    )
                    logger.error(
                        f"Ollama /api/generate 返回 {resp.status}: {body[:300]}\n"
                        f"  → 请求模型: '{model_name}', prompt_len={len(prompt)}\n"
                        f"  → 提示: 检查 'ollama list' 确认模型名是否匹配 config.yaml 中的 ollama_model"
                    )
                    raise urllib.error.HTTPError(
                        f"{_OLLAMA_BASE_URL}/api/generate",
                        resp.status,
                        f"HTTP {resp.status}",
                        resp.headers,
                        None,
                    )
                text, _ = _parse_ollama_response(body)
                self._intercept_log(
                    model_name,
                    prompt,
                    max_tokens,
                    False,
                    "200 OK",
                    elapsed=time.time() - t0,
                    result_len=len(text),
                    request_json=payload,
                )
                return text
        except Exception as e:
            self._intercept_log(
                model_name,
                prompt,
                max_tokens,
                False,
                "ERROR",
                error=str(e),
                elapsed=time.time() - t0,
                request_json=payload,
            )
            raise

    def _infer_stream(
        self,
        model_name: str,
        prompt: str,
        max_tokens: int,
        timeout: int,
        on_progress: callable,
        start_time: float,
    ) -> str | None:
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
            "options": {
                "num_predict": max_tokens,
                "num_ctx": 32768,  # 模型最大上下文窗口
            },
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{_OLLAMA_BASE_URL}/api/generate",
            data=data,
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Connection", "keep-alive")
        req.add_header("Keep-Alive", "timeout=600")  # 10 分钟保活

        full_text = []
        token_count = 0
        last_callback_at = 0
        _heartbeat_stop = threading.Event()
        _heartbeat_last_full = [""]
        _heartbeat_last_count = [0]
        _heartbeat_warn_count = [0]  # 连续无 token 检测次数

        def _heartbeat():
            """心跳线程：分级告警，区分 prefill 阶段 vs 真正卡死"""
            while not _heartbeat_stop.is_set():
                _heartbeat_stop.wait(60)
                if _heartbeat_stop.is_set():
                    break
                partial = "".join(full_text)
                if partial != _heartbeat_last_full[0] or token_count > _heartbeat_last_count[0]:
                    _heartbeat_last_full[0] = partial
                    _heartbeat_last_count[0] = token_count
                    _heartbeat_warn_count[0] = 0  # 有产出，重置
                    progress = min(token_count / max(1, max_tokens), 0.99)
                    try:
                        if on_progress:
                            on_progress(partial, progress)
                    except Exception:
                        pass
                else:
                    _heartbeat_warn_count[0] += 1
                    wc = _heartbeat_warn_count[0]
                    if token_count == 0 and wc <= 3:
                        logger.info(
                            f"⏳ Ollama prefill 中: 已等待 {wc * 60}s, prompt 较大概率需更多时间"
                        )
                    elif token_count == 0 and wc > 3:
                        logger.warning(
                            f"⚠️ Ollama 可能卡死: {wc * 60}s 无任何 token 产出, 请检查 Ollama 进程"
                        )
                    elif token_count > 0:
                        logger.info(
                            f"💭 Ollama 正在处理: 已产出 {token_count} tokens, 过去 60s 无新 token (可能大型推理)"
                        )

        _heartbeat_thread = threading.Thread(target=_heartbeat, daemon=True, name="ollama_heartbeat")
        _heartbeat_thread.start()

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                # v9.5.1: 检查 HTTP 状态码
                if resp.status != 200:
                    body = resp.read().decode("utf-8")[:500]
                    self._intercept_log(
                        model_name,
                        prompt,
                        max_tokens,
                        True,
                        f"HTTP {resp.status}",
                        error=body,
                        elapsed=time.time() - t0,
                        request_json=payload,
                    )
                    logger.error(
                        f"Ollama /api/generate (stream) 返回 {resp.status}: {body[:300]}\n"
                        f"  → 请求模型: '{model_name}', prompt_len={len(prompt)}\n"
                        f"  → 提示: 检查 'ollama list' 确认模型名是否匹配 config.yaml 中的 ollama_model"
                    )
                    raise urllib.error.HTTPError(
                        f"{_OLLAMA_BASE_URL}/api/generate",
                        resp.status,
                        f"HTTP {resp.status}",
                        resp.headers,
                        None,
                    )

                # 逐行读取流式响应
                for line in resp:
                    if line is None:
                        break  # 连接已关闭
                    line = line.decode("utf-8").strip()
                    if not line:
                        continue
                    try:
                        token, is_done = _parse_ollama_response(line)
                        full_text.append(token)
                        token_count += 1

                        # 每 10 个 token 回调一次进度
                        if on_progress and token_count - last_callback_at >= 10:
                            partial = "".join(full_text)
                            progress = min(token_count / max(1, max_tokens), 0.99)
                            try:
                                on_progress(partial, progress)
                            except Exception:
                                logger.warning(
                                    "LLMEngine._infer_stream: 未预期的异常被静默捕获（P-17 收口）",
                                    exc_info=True,
                                )
                                pass  # 回调失败不中断推理
                            last_callback_at = token_count

                        # 检查是否完成（v9.5.5 技术审查修复: 原代码引用未定义的 chunk 变量，
                        # 且 _parse_ollama_response 返回 (token, is_done:bool)，done 检测形同虚设）
                        if is_done:
                            break
                    except json.JSONDecodeError:
                        continue

            _heartbeat_stop.set()  # 停止心跳线程
            full = "".join(full_text)
            self._intercept_log(
                model_name,
                prompt,
                max_tokens,
                True,
                "200 OK",
                elapsed=time.time() - t0,
                result_len=len(full),
                request_json=payload,
            )
            # 最终回调
            try:
                if on_progress:
                    on_progress(full, 1.0)
            except Exception:
                logger.warning(
                    "LLMEngine._infer_stream: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass
            return full

        except Exception as e:
            _heartbeat_stop.set()
            self._intercept_log(
                model_name,
                prompt,
                max_tokens,
                True,
                "ERROR",
                error=str(e),
                elapsed=time.time() - t0,
                request_json=payload,
            )
            raise

    # ===== Analysis methods (delegate to llm_prompts.run_analysis) =====

    def analyze_conversation(
        self, content: str, source: str = "unknown", client: str = "unknown"
    ) -> dict | None:
        from backend.templates.llm_prompt import TASK_CONVERSATION_ANALYSIS, run_analysis

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        return run_analysis(
            TASK_CONVERSATION_ANALYSIS,
            content=content[: TASK_CONVERSATION_ANALYSIS.input_truncate],
            source=source,
            client=client,
        )

    def analyze_step_content(
        self,
        step_name: str,
        step_type: str,
        content: str,
        symptom: str = "",
        root_cause: str = "",
        solution: str = "",
        user_requirement: str = "",
        commands_executed: str = "",
        on_progress: callable = None,
    ) -> dict | None:
        from backend.templates.llm_prompt import TASK_STEP_ANALYSIS, run_analysis

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        return run_analysis(
            TASK_STEP_ANALYSIS,
            on_progress=on_progress,
            step_name=step_name or "unknown",
            step_type=step_type or "general",
            symptom=symptom or "none",
            root_cause=root_cause or "none",
            solution=solution or "none",
            user_requirement=user_requirement or "none",
            commands_executed=commands_executed or "none",
            content=content[: TASK_STEP_ANALYSIS.input_truncate],
        )

    # ═══════════════════════════════════════════════════════════
    # v9.8.0: 拆分的三个独立深度分析方法
    # ═══════════════════════════════════════════════════════════

    def _prepare_business_tech_kwargs(
        self, topic, system_id, project_context, user_raw_input, summary, key_decisions, ai_analysis
    ):
        """v9.11: 模块一专用参数 — 精简版（合并 summary+key_decisions 为 compact_context，
        各字段截断收紧：project_context[:1500], user_raw_input[:3000], ai_analysis[:5000])"""
        from backend.templates.llm_prompt._common import compact_json

        # summary 和 key_decisions 合并为 compact_context，减少重复输入
        summary_part = (summary or "")[:500]
        decisions_part = compact_json(key_decisions or [], max_chars=1000)
        compact_context = f"摘要: {summary_part}\n关键决策: {decisions_part}"

        return {
            "topic": topic or "未知主题",
            "system_id": system_id or "default",
            "project_context": project_context[:1500]
            if project_context
            else "（无项目上下文信息）",
            "user_raw_input": user_raw_input[:3000] if user_raw_input else "（无用户原始输入）",
            "compact_context": compact_context,
            "ai_analysis": ai_analysis[:5000] if ai_analysis else "（无AI意图分析）",
        }

    def _prepare_user_profile_kwargs(self, user_raw_input, ai_analysis):
        """v9.11: 模块二专用参数 — 截断收紧（user_raw_input[:3000], ai_analysis[:5000])"""
        return {
            "user_raw_input": user_raw_input[:3000] if user_raw_input else "（无用户原始输入）",
            "ai_analysis": ai_analysis[:5000] if ai_analysis else "（无AI意图分析）",
        }

    def analyze_business_tech(
        self,
        topic: str = "",
        system_id: str = "default",
        project_context: str = "",
        user_raw_input: str = "",
        summary: str = "",
        key_decisions: list = None,
        ai_analysis: str = "",
        on_progress: callable = None,
    ) -> dict | None:
        """v9.8.1: 业务知识 + 技术决策 + 整体评估
        输入: 项目上下文 + 用户原始输入 + 对话摘要 + 关键决策 + AI意图分析"""
        from backend.templates.llm_prompt import TASK_BUSINESS_TECH_ASSESSMENT, run_analysis

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        kwargs = self._prepare_business_tech_kwargs(
            topic,
            system_id,
            project_context,
            user_raw_input,
            summary,
            key_decisions or [],
            ai_analysis,
        )
        return run_analysis(TASK_BUSINESS_TECH_ASSESSMENT, on_progress=on_progress, **kwargs)

    def analyze_user_profile(
        self, user_raw_input: str = "", ai_analysis: str = "", on_progress: callable = None
    ) -> dict | None:
        """v9.8.1: 用户画像深度分析
        输入: 用户原始输入 + AI意图分析"""
        from backend.templates.llm_prompt import TASK_CONV_USER_PROFILE, run_analysis

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None
        kwargs = self._prepare_user_profile_kwargs(user_raw_input, ai_analysis)
        return run_analysis(TASK_CONV_USER_PROFILE, on_progress=on_progress, **kwargs)

    def review_project_description(
        self, current_description: str, topic: str = "", summary: str = "", ai_summary: str = ""
    ) -> dict | None:
        """v9.8.4: LLM 评审当前 project_description 是否需要优化。
        返回 {{"need_update": bool, "new_description": str}} 或 None。"""
        from backend.templates.llm_prompt import TASK_REVIEW_PROJECT_DESC, run_analysis

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_analysis", True):
            return None

        return run_analysis(
            TASK_REVIEW_PROJECT_DESC,
            current_description=current_description.strip()
            if current_description
            else "（暂无描述）",
            topic=topic[:200] if topic else "（无）",
            summary=(summary or "")[:1500],
            ai_summary=(ai_summary or "")[:1000],
        )

    # ═══════════════════════════════════════════════════════════
    # v9.12: analytics 上下文格式化（供日报 prompt 使用）
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _format_profile_for_prompt(profile: list) -> str:
        if not profile:
            return "暂无用户画像数据"
        lines = []
        for p in profile:
            lines.append(
                f"- {p['dimension']}: {p['value']} "
                f"(置信度={p['confidence']:.0%}, 趋势={p['trend']})"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_knowledge_for_prompt(knowledge: dict) -> str:
        if not knowledge:
            return ""
        parts = [f"知识库总量: {knowledge.get('total', 0)} 条知识点"]
        parts.append(f"今日新增: {knowledge.get('new_today', 0)} 条")
        parts.append(f"已被使用: {knowledge.get('used', 0)} 条 (usage_count > 0)")
        if knowledge.get("domains"):
            domain_lines = []
            for d, cnt in knowledge.get("by_domain", {}).items():
                domain_lines.append(f"  {d}: {cnt}")
            parts.append("领域分布:\n" + "\n".join(domain_lines))
        return "\n".join(parts)

    @staticmethod
    def _format_metrics_trend_for_prompt(trends: list) -> str:
        if not trends:
            return ""
        lines = ["近7日指标趋势:"]
        for t in trends:
            p = t.get("productivity") or "-"
            l = t.get("learning") or "-"
            f = t.get("focus") or "-"
            fr = t.get("frustration") or "-"
            lines.append(
                f"  {t['date']}: 生产力={p}/10, 学习={l}/10, 专注={f}/10, 挫败={fr}/5"
            )
        return "\n".join(lines)

    @staticmethod
    def _format_skills_for_prompt(skills: dict) -> str:
        if not skills:
            return ""
        parts = [f"技能树: {skills.get('total_skills', 0)} 项技能, 覆盖 {len(skills.get('domains', []))} 个领域"]
        for domain, items in skills.get("detail", {}).items():
            names = [f"{s['name']}({s['level']})" for s in items[:5]]
            parts.append(f"  {domain}: {', '.join(names)}")
        return "\n".join(parts)

    @staticmethod
    def _format_learning_plan_for_prompt(plan: dict) -> str:
        if not plan:
            return ""
        parts = [
            f"学习计划: {plan.get('total', 0)} 项, 进行中 {plan.get('active', 0)}, 已完成 {plan.get('completed', 0)}"
        ]
        for item in plan.get("active_items", [])[:3]:
            parts.append(f"  [{item['domain']}] {item['goal']} → 目标: {item['target']}")
        return "\n".join(parts)

    @staticmethod
    def _build_analytics_context(
        knowledge_ctx: str,
        metrics_ctx: str,
        skill_ctx: str,
        plan_ctx: str,
    ) -> str:
        """组装 analytics context 文本，注入 prompt。"""
        parts = []
        if knowledge_ctx:
            parts.append(f"## 知识库统计\n{knowledge_ctx}")
        if skill_ctx:
            parts.append(f"## 技能树\n{skill_ctx}")
        if plan_ctx:
            parts.append(f"## 学习计划\n{plan_ctx}")
        if metrics_ctx:
            parts.append(f"## 历史指标趋势\n{metrics_ctx}")
        if not parts:
            return "暂无历史分析数据"
        return "\n\n".join(parts)

    # ═══════════════════════════════════════════════════════════

    def generate_daily_summary(self, target_date: str, data: dict) -> dict | None:
        """v9.12: 增强版 — 注入 analytics 数据到 prompt context"""
        from backend.templates.llm_prompt import TASK_DAILY_SUMMARY, run_analysis
        from backend.templates.llm_prompt._common import compact_json

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_daily_summary", False):
            return None
        conversations_json = compact_json(
            data.get("conversations", [])[:15], max_chars=TASK_DAILY_SUMMARY.input_truncate
        )

        systems = data.get("systems", [])
        project_hint = ", ".join(systems) if systems else "（无系统标识，按对话主题分组）"

        stats = data.get("stats", {})
        task_types_str = (
            ", ".join(list(stats.get("by_type", {}).keys())[:5]) if stats.get("by_type") else ""
        )

        # v9.12: 真实画像快照（来自 DB，不再是空占位符）
        analytics = data.get("analytics", {})
        profile_snapshot = self._format_profile_for_prompt(analytics.get("user_profile_snapshot"))
        knowledge_context = self._format_knowledge_for_prompt(analytics.get("knowledge_stats"))
        metrics_context = self._format_metrics_trend_for_prompt(analytics.get("metrics_trends"))
        skill_context = self._format_skills_for_prompt(analytics.get("skill_summary"))
        plan_context = self._format_learning_plan_for_prompt(analytics.get("learning_plan"))

        result = run_analysis(
            TASK_DAILY_SUMMARY,
            date=target_date,
            total_conversations=len(data.get("conversations", [])),
            systems_active=project_hint,
            task_types=task_types_str,
            conversations=conversations_json,
            user_profile_snapshot=profile_snapshot,
            project_profile_snapshot=data.get("project_profile_snapshot", "暂无项目画像数据"),
            analytics_context=self._build_analytics_context(
                knowledge_context, metrics_context, skill_context, plan_context
            ),
        )
        if result:
            result["data_source"] = data.get("data_source", "db")
            # v9.12: 注入结构化分析数据到日报输出，供 MD 模板渲染
            result["analytics"] = analytics
        return result

    def generate_self_improvement_suggestions(
        self, system_data: dict, improvement_history: list = None
    ) -> list | None:
        from backend.templates.llm_prompt import TASK_SELF_IMPROVEMENT, run_analysis
        from backend.templates.llm_prompt._common import compact_json

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_self_improvement", False):
            return None
        history_json = compact_json(improvement_history or [], max_chars=3000)
        system_json = compact_json(system_data, max_chars=5000)
        return run_analysis(
            TASK_SELF_IMPROVEMENT,
            system_data=system_json,
            improvement_history=history_json,
        )

    def parse_file_conversations(self, content: str, filename: str = "unknown") -> dict | None:
        from backend.templates.llm_prompt import TASK_FILE_PARSE, run_analysis

        if not self.is_available():
            return None
        cfg = self._get_config()
        if not getattr(cfg.llm, "enhance_file_parsing", True):
            return None
        return run_analysis(
            TASK_FILE_PARSE,
            content=content[: TASK_FILE_PARSE.input_truncate],
            filename=filename,
        )

    # ===== Business logic methods (from LLMUnifiedAnalyzer) =====

    def apply_user_traits(
        self, traits: dict, source: str = "unified_analyzer", conversations_id: int = None
    ) -> dict:
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

        from backend.core.database.base_conn import get_db

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
                from backend.core.skill_domain_standard import normalize_domain

                skill_domain = normalize_domain(skill_domain)

                # v9.11: estimated_hours 和 growth_trend 改为 Python 确定性计算，不再依赖 LLM
                # estimated_hours = 已出现次数 × 0.3h（每出现一次估 0.3h 学习时间）
                # growth_trend = 最近出现次数 > 1 → growing，否则 stable
                estimated_hours = 0.3  # 首次出现默认值
                growth_trend = "growing"  # 首次出现默认 growing

                # ★ 增量合并逻辑
                merge_result = self._merge_skill_incremental(
                    db=db,
                    skill_name=skill_name,
                    skill_domain=skill_domain,
                    context={
                        "skill_domain": skill_domain,
                        "skill_level": processed.get("skill_level", "intermediate"),
                        "sub_skills": processed.get("related_skills", []),
                        "evidence_text": processed.get(
                            "evidence_text", f"从对话中观察到 {skill_name} 技能"
                        ),
                        "estimated_hours": estimated_hours,
                        "growth_trend": growth_trend,
                        "source_conversation_id": conversations_id,
                        "source_timestamp": datetime.now().isoformat(),
                        "extraction_method": source,
                    },
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
            behavior_items.append(
                (
                    "user_communication_profile",
                    f"沟通风格: {communication_style} | 决策: {decision_pattern or '未观察'}",
                    "low",
                )
            )

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
                db.insert_optimization_feedback(
                    {
                        "source": source,
                        "feedback_type": "emotional_state",
                        "description": f"用户情绪: {emotional_state}",
                        "suggestion": "关注用户情绪变化，调整交互策略",
                        "priority": "low",
                        "conversations_id": conversations_id,
                    }
                )
            except Exception:
                logger.warning(
                    "LLMEngine.apply_user_traits: 未预期的异常被静默捕获（P-17 收口）",
                    exc_info=True,
                )
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

    def _process_user_traits_with_llm(self, traits: dict) -> dict:
        """使用 LLM 智能处理和丰富用户特征（v9.8.4: 使用 prompts/ 外部 Prompt）"""
        if not self.is_available:
            return traits

        try:
            from backend.templates.llm_prompt import TASK_USER_TRAITS_ENRICH, run_analysis

            enhanced = run_analysis(
                TASK_USER_TRAITS_ENRICH,
                traits_json=json.dumps(traits, ensure_ascii=False),
            )
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
        from backend.core.skill_domain_standard import normalize_domain

        result = []
        for skill in skills:
            if isinstance(skill, dict):
                result.append(skill)
                continue

            skill_str = str(skill).strip()
            if not skill_str:
                continue

            result.append(
                {
                    "skill_name": skill_str,
                    "skill_domain": normalize_domain(skill_str),
                }
            )

        return result

    def _merge_skill_incremental(
        self, db, skill_name: str, context: dict, skill_domain: str = ""
    ) -> dict:
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
                old_sub_skills = (
                    set(existing.get("sub_skills", "").split(", "))
                    if existing.get("sub_skills")
                    else set()
                )
                new_sub_skills = set(context.get("sub_skills", []))
                merged_sub_skills = list(old_sub_skills | new_sub_skills)[:10]  # 最多保留10个

                # 更新记录
                update_data = {
                    "skill_domain": domain,
                    "skill_name": skill_name,
                    "skill_level": context.get(
                        "skill_level", existing.get("skill_level", "intermediate")
                    ),
                    "sub_skills": ", ".join(merged_sub_skills) if merged_sub_skills else "",
                    "evidence": f"{context.get('extraction_method', 'unknown')}: {context.get('evidence_text', '')}",
                    "confidence": new_confidence,
                    "last_seen": context.get("source_timestamp", datetime.now().isoformat()),
                    "evidence_count": (existing.get("evidence_count", 1) or 1) + 1,
                    "hours_spent": (existing.get("hours_spent", 0) or 0)
                    + context.get("estimated_hours", 0),
                    "growth_trend": context.get("growth_trend", "growing"),
                }

                db.update_user_skill(skill_name, update_data, skill_domain=domain)

                logger.debug(
                    f"技能增量更新 [{domain}/{skill_name}] confidence: {old_confidence:.2f} → {new_confidence:.2f}"
                )

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
                    "sub_skills": ", ".join(context.get("sub_skills", []))
                    if context.get("sub_skills")
                    else "",
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
                db.upsert_user_skills(
                    domain,
                    {
                        "skill_name": skill_name,
                        "skill_level": context.get("skill_level", "intermediate"),
                        "sub_skills": ", ".join(context.get("sub_skills", []))
                        if context.get("sub_skills")
                        else "",
                        "evidence": f"{context.get('extraction_method', 'unknown')}: {context.get('evidence_text', '')}",
                        "conversation_ids": str(context.get("source_conversation_id", "")),
                        "hours_spent": context.get("estimated_hours", 0.3),
                        "growth_trend": context.get("growth_trend", "growing"),
                    },
                )

                return {"action": "fallback_upsert", "skill": skill_name, "error": str(e)}

            except Exception as e2:
                logger.error(f"降级 upsert 也失败 [{skill_name}]: {e2}")
                return {"action": "failed", "skill": skill_name, "error": str(e2)}


_engine_instance: LLMEngine | None = None


def get_llm_engine() -> LLMEngine:
    """获取全局 LLM 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = LLMEngine()
    return _engine_instance
