#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DevPartner v7.3 - Ollama 服务检查脚本

功能：
  1. 检查 Ollama 服务是否在线
  2. 验证配置的模型是否可用
  3. 提供安装/拉取指引（如果模型不存在）
  4. 输出环境信息（本地/Docker/云端）

使用方式：
  python scripts/check_model.py          # 检查并输出结果
  python scripts/check_model.py --strict # 严格模式（失败时退出码1）

适用场景：
  - 启动前预检
  - Docker容器启动检查
  - ModelScope部署验证
  - CI/CD流水线集成

作者：DevPartner Team
版本：v7.3 | 更新：2026-07-10
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

# ============================================================
# 配置常量
# ============================================================

# Ollama 服务地址
_OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# 默认模型名（与 config.yaml 一致）
_DEFAULT_MODEL = "qwen3"

# 项目根目录（自动检测）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def detect_environment():
    """
    检测当前运行环境

    返回:
      str: "local" | "docker" | "modelscope" | "unknown"
    """
    if Path("/.dockerenv").exists():
        return "docker"

    if os.environ.get("MODELSCOPE_ENVIRONMENT") == "true":
        return "modelscope"

    return "local"


def check_ollama_available() -> dict:
    """
    检查 Ollama 服务是否在线。

    返回:
      dict: {"online": bool, "version": str, "error": str}
    """
    try:
        req = urllib.request.Request(f"{_OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return {
                "online": True,
                "models": models,
                "model_count": len(models),
                "error": None,
            }
    except urllib.error.URLError as e:
        return {
            "online": False,
            "models": [],
            "model_count": 0,
            "error": f"Ollama 服务不可达 ({_OLLAMA_BASE_URL}): {e.reason}",
        }
    except Exception as e:
        return {
            "online": False,
            "models": [],
            "model_count": 0,
            "error": f"检查失败: {str(e)}",
        }


def check_model_available(ollama_status: dict, model_name: str) -> dict:
    """
    检查指定模型是否已拉取。

    参数:
      ollama_status: check_ollama_available() 的返回
      model_name: 模型名称（如 "qwen3" 或 "qwen3:latest"）

    返回:
      dict: {"found": bool, "exact_match": str, "similar": list}
    """
    if not ollama_status["online"]:
        return {"found": False, "exact_match": None, "similar": []}

    models = ollama_status["models"]
    base_name = model_name.split(":")[0]

    # 精确匹配
    for m in models:
        if m == model_name or m.startswith(model_name + ":"):
            return {"found": True, "exact_match": m, "similar": []}

    # 模糊匹配（同名不同tag）
    similar = [m for m in models if m.startswith(base_name)]

    return {"found": False, "exact_match": None, "similar": similar}


def print_install_guide():
    """输出 Ollama 安装和模型拉取指南"""
    print("""
📥 Ollama 安装与模型拉取指南
═══════════════════════════════════════

方式一：安装 Ollama
───────────────────
  1. 访问 https://ollama.com 下载安装包
  2. 安装后启动服务:
     ollama serve

方式二：拉取模型
────────────────
  ollama pull qwen3:latest      # 推荐（~4.7GB）
  ollama pull qwen2.5:7b        # 备选（~4.4GB）
  ollama pull qwen2.5:14b       # 高性能（~8.5GB）

方式三：查看已安装模型
─────────────────────
  ollama list

方式四：Docker 内安装 Ollama
────────────────────────────
  docker run -d --name ollama -p 11434:11434 ollama/ollama
  docker exec -it ollama ollama pull qwen3:latest

详细说明请查看: models/README.md
""")


def main(strict_mode: bool = False):
    """
    主函数

    参数:
      strict_mode: bool - 严格模式，失败时返回非零退出码

    返回:
      int: 0=成功, 1=失败(仅strict模式), 2=错误
    """
    print("=" * 60)
    print("  DevPartner v7.3 · Ollama 服务检查工具")
    print("=" * 60)
    print()

    # 1. 检测运行环境
    env = detect_environment()
    env_names = {
        "local": "🖥️ 本地开发环境",
        "docker": "🐳 Docker 容器",
        "modelscope": "☁️ ModelScope 云端"
    }
    print(f"  运行环境: {env_names.get(env, '❓ 未知环境')}")
    print(f"  项目目录: {PROJECT_ROOT}")
    print(f"  Ollama URL: {_OLLAMA_BASE_URL}")
    print()

    # 2. 读取配置中的模型名
    model_name = _DEFAULT_MODEL
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from devpartner_agent.core.config import get_config
        cfg = get_config()
        model_name = getattr(cfg.llm, 'ollama_model', _DEFAULT_MODEL)
    except Exception:
        pass
    print(f"  配置模型: {model_name}")
    print()

    # 3. 检查 Ollama 服务
    ollama_status = check_ollama_available()

    if not ollama_status["online"]:
        print(f"  ❌ {ollama_status['error']}")
        print()
        print("  ⚠️ LLM 推理功能将不可用")
        print("  （系统可降级到规则模式）")
        print()
        print_install_guide()

        if strict_mode:
            print("  🔴 严格模式：检查未通过")
            return 1
        else:
            print("  🟡 非严格模式：继续启动（LLM功能受限）")
            return 0

    print(f"  ✅ Ollama 服务在线 ({_OLLAMA_BASE_URL})")
    print(f"  已安装模型: {ollama_status['model_count']} 个")
    for m in ollama_status["models"]:
        print(f"    - {m}")
    print()

    # 4. 检查目标模型
    model_status = check_model_available(ollama_status, model_name)

    if model_status["found"]:
        print(f"  ✅ 模型 '{model_status['exact_match']}' 已就绪")
        print()
        print("  🎉 Ollama 服务检查通过！可以正常使用 LLM 推理功能。")
        print()
        print("  下一步操作:")
        print("    python server.py 7860            # 启动服务（本地）")
        print("    docker-compose up -d             # 启动服务（Docker）")
        return 0

    elif model_status["similar"]:
        print(f"  ⚠️ 未找到模型 '{model_name}'，但发现相似模型:")
        for s in model_status["similar"]:
            print(f"    → {s}")
        print(f"  可在 config.yaml 中修改 ollama_model 为以上任一名称。")
        print()
        if strict_mode:
            print("  🔴 严格模式：检查未通过")
            return 1
        else:
            print("  🟡 非严格模式：继续启动（将尝试自动拉取）")
            return 0

    else:
        print(f"  ⚠️ 模型 '{model_name}' 未找到，且无其他模型可用。")
        print()
        print_install_guide()

        if strict_mode:
            print("  🔴 严格模式：检查未通过")
            return 1
        else:
            print("  🟡 非严格模式：继续启动（LLM功能受限）")
            return 0


if __name__ == "__main__":
    strict = "--strict" in sys.argv or "-s" in sys.argv

    try:
        exit_code = main(strict_mode=strict)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
