"""
系统启动与初始化
================
从 server.py 提取的核心启动逻辑：
  - anyio MemoryObjectSendStream ClosedResourceError 补丁
  - ensure_ready() 核心初始化（含 Ollama 自启动）
"""
import os
import sys
import json
import time
import subprocess
import threading
import logging
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_core_initialized = False
_ollama_started = False


def _ensure_ollama_running(timeout: int = 30) -> bool:
    """确保 Ollama 服务正在运行，如果未运行则尝试自动启动

    Args:
        timeout: 等待 Ollama 就绪的最大秒数

    Returns:
        True 如果 Ollama 已就绪，False 如果启动失败
    """
    global _ollama_started
    if _ollama_started:
        return True

    ollama_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    def _check_ollama() -> bool:
        try:
            req = urllib.request.Request(f"{ollama_url}/api/tags", method="GET")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    # 1. 检查是否已运行
    if _check_ollama():
        _ollama_started = True
        return True

    # 2. 检查 ollama 命令是否可用
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            print("[WARN] ollama 命令不可用，请确保已安装 Ollama: https://ollama.com/download")
            return False
    except FileNotFoundError:
        print("[WARN] ollama 命令未找到，请确保已安装 Ollama: https://ollama.com/download")
        return False
    except Exception as e:
        print(f"[WARN] 检查 ollama 命令失败: {e}")
        return False

    # 3. 尝试自动启动 Ollama
    print("[INFO] Ollama 未运行，正在自动启动...")
    try:
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(["ollama", "serve"], **kwargs)
        print("[INFO] ollama serve 已启动，等待服务就绪...")
    except Exception as e:
        print(f"[WARN] 启动 Ollama 失败: {e}")
        return False

    # 4. 轮询等待 Ollama 就绪
    start = time.time()
    while time.time() - start < timeout:
        if _check_ollama():
            elapsed = time.time() - start
            print(f"[INFO] Ollama 已就绪 (耗时 {elapsed:.1f}s)")
            _ollama_started = True
            return True
        time.sleep(2)

    print(f"[WARN] Ollama 启动超时 ({timeout}s)，将以降级模式运行")
    return False


def apply_patches():
    """应用 anyio 底层补丁（必须在 import mcp 之前调用）

    Streamable HTTP 传输层内部仅部分 .send() 调用被 try/except 包裹，
    此补丁在 anyio 底层拦截 ClosedResourceError，防止未捕获的异常导致服务崩溃。
    """
    try:
        from anyio.streams.memory import ClosedResourceError, MemoryObjectSendStream
        import functools

        _original_send = MemoryObjectSendStream.send

        @functools.wraps(_original_send)
        async def _safe_send(self, item):
            try:
                return await _original_send(self, item)
            except ClosedResourceError:
                return None

        MemoryObjectSendStream.send = _safe_send
        print("[INFO] MemoryObjectSendStream.send ClosedResourceError 保护已注入")

    except ImportError:
        print("[WARN] 无法导入 anyio，跳过 MemoryObjectSendStream 补丁")
    except Exception as e:
        print(f"[WARN] MemoryObjectSendStream 补丁应用失败: {e}")


def ensure_ready():
    """确保核心模块已初始化（懒加载）"""
    global _core_initialized
    if _core_initialized:
        return True

    try:
        from devpartner_agent.core.config import get_config
        from devpartner_agent.core.database import get_db

        cfg = get_config()
        db_path = str(Path(cfg.data.databases_dir) / "devpartner.db")
        get_db().init_local(db_path)

        try:
            db = get_db()
            cursor = db._local_conn.cursor()
            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_conversations_conversation_id_unique 
                ON conversations(conversation_id)
            """)
            db._local_conn.commit()
        except Exception:
            pass

        from devpartner_agent.core.rule_engine import get_engine
        from devpartner_agent.core.identity import get_identity

        try:
            from devpartner_agent.services.cleanup_service import get_cleanup_scheduler
            scheduler = get_cleanup_scheduler()
            cleanup_interval = (
                cfg.data_lifecycle.auto_cleanup_interval_hours
                if hasattr(cfg.data_lifecycle, 'auto_cleanup_interval_hours')
                else 24
            )
            if cfg.data_lifecycle.auto_cleanup:
                scheduler.start(interval_hours=cleanup_interval)
                print(f"[INFO] 自动清理调度器已启动，间隔 {cleanup_interval} 小时")
        except Exception as e:
            print(f"[WARN] 自动清理调度器启动失败: {e}")

        try:
            from devpartner_agent.services.cleanup_service import get_cleanup_service
            cs = get_cleanup_service()
            print("[INFO] 任务数据清理服务已启动 (v7.0)")
        except Exception as e:
            print(f"[WARN] 任务数据清理服务启动失败: {e}")

        try:
            if cfg.llm.enabled and cfg.llm.preload:
                # 确保 Ollama 在运行（如果未运行则自动启动）
                _ensure_ollama_running(timeout=30)

                from devpartner_agent.core.llm_engine import get_llm_engine
                llm = get_llm_engine()
                if llm.preload():
                    print(f"[INFO] Ollama LLM 已就绪: {getattr(cfg.llm, 'ollama_model', 'qwen3')}")
                elif llm.is_enabled():
                    status = llm.get_status()
                    print(f"[WARN] 本地 LLM 预加载跳过: {status.get('load_error') or '模型不可用'}")
        except Exception as e:
            print(f"[WARN] 本地 LLM 初始化失败: {e}")

        try:
            from devpartner_agent.core.scheduler import get_timeout_scheduler
            timeout_scheduler = get_timeout_scheduler()
            timeout_scheduler.start()
            print("[INFO] 任务超时巡检调度器已启动 (间隔 300s)")
        except Exception as e:
            print(f"[WARN] 任务超时巡检调度器启动失败: {e}")

        try:
            from devpartner_agent.core.scheduler import get_scheduler
            profile_scheduler = get_scheduler()
            profile_scheduler.start()
            print("[INFO] 每日总结调度器已启动 (每日 17:30 触发)")
        except Exception as e:
            print(f"[WARN] 每日总结调度器启动失败: {e}")

        _core_initialized = True
        return True
    except Exception as e:
        print(f"[WARN] 核心模块初始化失败: {e}")
        print("[WARN] Agent 将以降级模式运行（仅基础功能可用）")
        return False


def is_initialized() -> bool:
    """检查核心是否已初始化"""
    return _core_initialized