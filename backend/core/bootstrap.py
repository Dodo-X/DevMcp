"""
系统启动与初始化
================
从 server.py 提取的核心启动逻辑：
  - anyio MemoryObjectSendStream ClosedResourceError 补丁
  - ensure_ready() 核心初始化（含 Ollama 自启动）
"""

import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_core_initialized = False
_ollama_started = False
_ollama_logs: list = []  # 启动日志缓冲区，供 Dashboard 消费
_MAX_OLLAMA_LOGS = 200


def _ollama_log(msg: str, level: str = "INFO"):
    """记录 Ollama 操作日志到缓冲区"""
    ts = time.strftime("%H:%M:%S")
    _ollama_logs.append({"time": ts, "level": level, "msg": msg})
    if len(_ollama_logs) > _MAX_OLLAMA_LOGS:
        _ollama_logs.pop(0)
    if level == "ERROR":
        logger.error(msg)
    elif level == "WARN":
        logger.warning(msg)
    else:
        logger.info(msg)


def get_ollama_logs() -> list:
    """获取 Ollama 操作日志（供 API 和 Dashboard 消费）"""
    return list(_ollama_logs)


def reset_ollama_state():
    """重置 Ollama 状态，允许重新尝试连接"""
    global _ollama_started
    _ollama_started = False
    _ollama_logs.clear()
    _ollama_log("Ollama 状态已重置，准备重新连接...", "INFO")


def start_ollama_service(timeout: int = 30) -> dict:
    """手动启动 Ollama 服务并连接（供 Dashboard 调用）

    Returns:
        {"success": bool, "logs": [...], "error": str|None}
    """
    reset_ollama_state()
    ok = _ensure_ollama_running(timeout=timeout)
    if ok:
        _ollama_log("Ollama 服务已就绪，LLM 引擎可用", "INFO")
        return {"success": True, "logs": get_ollama_logs(), "error": None}
    else:
        _ollama_log("Ollama 启动失败，请检查安装和配置", "ERROR")
        return {
            "success": False,
            "logs": get_ollama_logs(),
            "error": "Ollama 启动超时或命令不可用，请确认已安装 Ollama",
        }


def _ensure_ollama_running(timeout: int = 30) -> bool:
    """确保 Ollama 服务正在运行，如果未运行则尝试自动启动

    Args:
        timeout: 等待 Ollama 就绪的最大秒数

    Returns:
        True 如果 Ollama 已就绪，False 如果启动失败
    """
    global _ollama_started
    if _ollama_started:
        _ollama_log("Ollama 已标记为就绪，跳过启动检查", "INFO")
        return True

    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    _ollama_log(f"Ollama 地址: {ollama_url}", "INFO")

    def _check_ollama() -> bool:
        try:
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except urllib.error.URLError as e:
            _ollama_log(f"连接 Ollama 失败: {e.reason}", "WARN")
            return False
        except Exception as e:
            logger.warning(
                "_ensure_ollama_running: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
            )
            _ollama_log(f"检查 Ollama 异常: {e}", "WARN")
            return False

    if _check_ollama():
        _ollama_started = True
        _ollama_log("Ollama 服务已在运行", "INFO")
        return True

    _ollama_log("Ollama 未运行，检查 ollama 命令...", "INFO")

    try:
        result = subprocess.run(["ollama", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            _ollama_log(
                "ollama 命令不可用，请确保已安装 Ollama: https://ollama.com/download", "ERROR"
            )
            return False
        _ollama_log(f"ollama 版本: {result.stdout.strip()}", "INFO")
    except FileNotFoundError:
        _ollama_log("ollama 命令未找到，请确保已安装 Ollama: https://ollama.com/download", "ERROR")
        return False
    except Exception as e:
        logger.warning("_ensure_ollama_running: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        _ollama_log(f"检查 ollama 命令失败: {e}", "ERROR")
        return False

    _ollama_log("正在启动 ollama serve...", "INFO")
    try:
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(["ollama", "serve"], **kwargs)
        _ollama_log(f"ollama serve 已启动 (PID: {proc.pid})", "INFO")

        import threading

        def _read_ollama_output():
            try:
                stdout, stderr = proc.communicate(timeout=5)
                if stdout:
                    for line in stdout.decode("utf-8", errors="replace").split("\n")[:5]:
                        if line.strip():
                            _ollama_log(f"[ollama] {line.strip()}", "INFO")
                if stderr:
                    for line in stderr.decode("utf-8", errors="replace").split("\n")[:5]:
                        if line.strip():
                            _ollama_log(f"[ollama ERR] {line.strip()}", "WARN")
            except Exception:
                logger.warning(
                    "_ensure_ollama_running: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                )
                pass

        t = threading.Thread(target=_read_ollama_output, daemon=True)
        t.start()
    except Exception as e:
        logger.warning("_ensure_ollama_running: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        _ollama_log(f"启动 Ollama 失败: {e}", "ERROR")
        return False

    _ollama_log(f"等待 Ollama 就绪 (最长 {timeout}s)...", "INFO")
    start = time.time()
    last_log = start
    while time.time() - start < timeout:
        if _check_ollama():
            elapsed = time.time() - start
            _ollama_log(f"Ollama 已就绪 (耗时 {elapsed:.1f}s)", "INFO")
            _ollama_started = True
            return True
        if time.time() - last_log >= 5:
            _ollama_log(f"等待中... ({time.time() - start:.0f}s/{timeout}s)", "INFO")
            last_log = time.time()
        time.sleep(2)

    _ollama_log(f"Ollama 启动超时 ({timeout}s)，将以降级模式运行", "ERROR")
    _ollama_started = False
    return False


def apply_patches():
    """应用 anyio 底层补丁（必须在 import mcp 之前调用）

    Streamable HTTP 传输层内部仅部分 .send() 调用被 try/except 包裹，
    此补丁在 anyio 底层拦截 ClosedResourceError，防止未捕获的异常导致服务崩溃。
    """
    try:
        import functools

        from anyio.streams.memory import ClosedResourceError, MemoryObjectSendStream

        _original_send = MemoryObjectSendStream.send

        @functools.wraps(_original_send)
        async def _safe_send(self, item):
            try:
                return await _original_send(self, item)
            except ClosedResourceError:
                return None

        MemoryObjectSendStream.send = _safe_send
        logger.info("MemoryObjectSendStream.send ClosedResourceError 保护已注入")

    except ImportError:
        logger.warning("无法导入 anyio，跳过 MemoryObjectSendStream 补丁")
    except Exception as e:
        logger.warning(f"MemoryObjectSendStream 补丁应用失败: {e}")


def ensure_ready():
    """确保核心模块已初始化（懒加载）"""
    global _core_initialized
    if _core_initialized:
        return True

    try:
        from foundation.config.app_settings import get_config

        from backend.core.database.base_conn import get_db

        cfg = get_config()
        db_path = str(Path(cfg.data.databases_dir) / "devpartner.db")
        get_db().init_local(db_path)

        try:
            db = get_db()
            db.query_local(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique "
                "ON conversations(conversation_id)"
            )
        except Exception:
            logger.warning("ensure_ready: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
            pass

        # v9.11: 数据治理 — 存量数据归一化 + 孤儿步骤修复
        try:
            from backend.business.data_governance.normalizer import (
                fix_existing_data,
                fix_orphan_steps,
            )

            db = get_db()
            norm_result = fix_existing_data(db)
            if any(v > 0 for v in norm_result.values()):
                logger.info(f"数���归一化完成: {norm_result}")
            orphan_result = fix_orphan_steps(db)
            if orphan_result["orphaned_count"] > 0:
                logger.warning(f"孤儿步骤已隔离: {orphan_result}")
        except Exception:
            logger.warning("数据治理初始化失败", exc_info=True)

        try:
            from backend.business.data_cleanup.cleanup_service import get_cleanup_scheduler

            scheduler = get_cleanup_scheduler()
            cleanup_interval = (
                cfg.data_lifecycle.auto_cleanup_interval_hours
                if hasattr(cfg.data_lifecycle, "auto_cleanup_interval_hours")
                else 24
            )
            if cfg.data_lifecycle.auto_cleanup:
                scheduler.start(interval_hours=cleanup_interval)
                logger.info(f"自动清理调度器已启动，间隔 {cleanup_interval} 小时")
        except Exception as e:
            logger.warning(f"自动清理调度器启动失败: {e}")

        try:
            from backend.business.data_cleanup.cleanup_service import get_cleanup_service

            get_cleanup_service()
            logger.info("任务数据清理服务已启动 (v7.0)")
        except Exception as e:
            logger.warning(f"任务数据清理服务启动失败: {e}")

        try:
            if cfg.llm.enabled and cfg.llm.preload:
                # 确保 Ollama 在运行（如果未运行则自动启动）
                _ensure_ollama_running(timeout=30)

                from backend.core.llm_kernel.base_client import get_llm_engine

                llm = get_llm_engine()
                if llm.preload():
                    logger.info(f"Ollama LLM 已就绪: {getattr(cfg.llm, 'ollama_model', 'qwen3')}")
                elif llm.is_enabled():
                    status = llm.get_status()
                    logger.warning(
                        f"本地 LLM 预加载跳过: {status.get('load_error') or '模型不可用'}"
                    )
        except Exception as e:
            logger.warning(f"本地 LLM 初始化失败: {e}")

        try:
            from backend.core.task_queue_kernel.queue_client import get_task_queue

            tq = get_task_queue()
            # v9.7.1: 使用延迟恢复（此时 handler 已注册完毕）
            recovery_result = tq.run_startup_recovery()
            recovered = recovery_result.get("recovered", 0)
            pipeline = recovery_result.get("pipeline_stats", {})
            if recovered > 0 or pipeline.get("scanned", 0) > 0:
                logger.info(
                    f"启动恢复: DB加载 {recovered} 个 | 流水线扫描 {pipeline.get('scanned', 0)} → 入队 {pipeline.get('enqueued', 0)}"
                )
        except Exception as e:
            logger.warning(f"任务队列恢复失败: {e}")

        try:
            from backend.core.scheduler import get_timeout_scheduler

            timeout_scheduler = get_timeout_scheduler()
            timeout_scheduler.start()
            logger.info("任务超时巡检调度器已启动 (扫描间隔 300s, 任务超时 10800s/3h)")
        except Exception as e:
            logger.warning(f"任务超时巡检调度器启动失败: {e}")

        try:
            from backend.core.scheduler import get_scheduler

            profile_scheduler = get_scheduler()
            profile_scheduler.start()
            logger.info("每日总结调度器已启动 (每日 17:30 触发)")
        except Exception as e:
            logger.warning(f"每日总结调度器启动失败: {e}")

        _core_initialized = True
        return True
    except Exception as e:
        logger.warning(f"核心模块初始化失败: {e}")
        logger.warning("Agent 将以降级模式运行（仅基础功能可用）")
        return False


def is_initialized() -> bool:
    """检查核心是否已初始化"""
    return _core_initialized
