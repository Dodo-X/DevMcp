#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DevPartner v6.0 - 模型文件检查脚本

功能：
  1. 检查 models/ 目录下的模型文件是否存在
  2. 验证模型文件完整性（大小、格式）
  3. 提供下载指引（如果模型不存在）
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
版本：v6.0 | 更新：2026-07-03
"""

import os
import sys
from pathlib import Path

# ============================================================
# 配置常量
# ============================================================

# 默认模型文件名
DEFAULT_MODEL_FILE = "Qwen3.5-9B-Q4_1.gguf"

# 最小模型文件大小 (MB) - Qwen3.5-9B Q4_1 约 5.7GB
MIN_MODEL_SIZE_MB = 5000  # 至少 5GB 才算有效

# 支持的模型格式
SUPPORTED_FORMATS = [".gguf", ".bin", ".safetensors"]

# 项目根目录（自动检测）
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def detect_environment():
    """
    检测当前运行环境
    
    返回:
      str: "local" | "docker" | "modelscope" | "unknown"
    """
    # 检查是否在 Docker 容器中
    if Path("/.dockerenv").exists():
        return "docker"
    
    # 检查 ModelScope 环境变量
    if os.environ.get("MODELSCOPE_ENVIRONMENT") == "true":
        return "modelscope"
    
    # 默认为本地环境
    return "local"


def find_model_file(models_dir: Path) -> Path | None:
    """
    在 models/ 目录中查找模型文件
    
    参数:
      models_dir: models 目录路径
      
    返回:
      Path: 找到的模型文件路径，未找到返回 None
    """
    if not models_dir.exists():
        return None
    
    # 优先查找默认模型文件
    default_model = models_dir / DEFAULT_MODEL_FILE
    if default_model.exists() and default_model.is_file():
        return default_model
    
    # 查找其他支持的格式
    for fmt in SUPPORTED_FORMATS:
        for model_file in models_dir.glob(f"*{fmt}"):
            if model_file.is_file() and not model_file.name.startswith("."):
                return model_file
    
    return None


def check_model_integrity(model_path: Path) -> dict:
    """
    验证模型文件完整性
    
    参数:
      model_path: 模型文件路径
      
    返回:
      dict: {
        "valid": bool,           # 是否有效
        "size_mb": float,        # 文件大小(MB)
        "size_ok": bool,         # 大小是否符合要求
        "format_ok": bool,       # 格式是否支持
        "message": str           # 描述信息
      }
    """
    result = {
        "valid": False,
        "size_mb": 0,
        "size_ok": False,
        "format_ok": False,
        "message": ""
    }
    
    try:
        # 获取文件大小
        size_bytes = model_path.stat().st_size
        result["size_mb"] = round(size_bytes / (1024 * 1024), 2)
        
        # 检查文件大小
        result["size_ok"] = result["size_mb"] >= MIN_MODEL_SIZE_MB
        
        # 检查文件格式
        file_ext = model_path.suffix.lower()
        result["format_ok"] = file_ext in SUPPORTED_FORMATS
        
        # 综合判断
        if result["size_ok"] and result["format_ok"]:
            result["valid"] = True
            result["message"] = f"✅ 模型文件完整 ({result['size_mb']} MB)"
        elif not result["format_ok"]:
            result["message"] = f"⚠️ 不支持的格式: {file_ext} (支持: {', '.join(SUPPORTED_FORMATS)})"
        else:
            result["message"] = f"⚠️ 文件过小: {result['size_mb']} MB (预期 > {MIN_MODEL_SIZE_MB} MB)"
            
    except Exception as e:
        result["message"] = f"❌ 检查失败: {str(e)}"
    
    return result


def print_download_guide():
    """输出模型下载指南"""
    print("""
📥 模型文件下载指南
═══════════════════════════════════════

方式一：从 ModelScope 下载（国内推荐）
───────────────────────────────────────
  pip install modelscope
  modelscope download --model Qwen/Qwen3.5-9B-Instruct-GGUF \\
      --local_dir ./models \\
      Qwen3.5-9B-Q4_1.gguf

方式二：从 HuggingFace 下载
────────────────────────────
  pip install huggingface_hub
  huggingface-cli download Qwen/Qwen3.5-9B-Instruct-GGUF \\
      Qwen3.5-9B-Q4_1.gguf \\
      --local-dir ./models

方式三：手动下载
───────────────
  1. 访问 https://modelscope.cn/models/Qwen/Qwen3.5-9B-Instruct-GGUF/files
  2. 下载 Qwen3.5-9B-Q4_1.gguf (~5.7GB)
  3. 将文件放到 ./models/ 目录

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
    print("  DevPartner v6.0 · 模型文件检查工具")
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
    print()
    
    # 2. 定位 models/ 目录
    models_dir = PROJECT_ROOT / "models"
    print(f"  模型目录: {models_dir}")
    print(f"  目录状态: {'✅ 存在' if models_dir.exists() else '❌ 不存在'}")
    print()
    
    # 3. 查找模型文件
    model_file = find_model_file(models_dir)
    
    if model_file is None:
        print("  ❌ 未找到模型文件！")
        print()
        print("  ⚠️ LLM 推理功能将不可用")
        print("  （系统可降级到规则引擎模式）")
        print()
        print_download_guide()
        
        if strict_mode:
            print("  🔴 严格模式：检查未通过")
            return 1
        else:
            print("  🟡 非严格模式：继续启动（LLM功能受限）")
            return 0
    
    # 4. 验证模型文件
    print(f"  模型文件: {model_file.name}")
    integrity = check_model_integrity(model_file)
    
    print(f"  文件大小: {integrity['size_mb']} MB")
    print(f"  格式检查: {'✅ 支持' if integrity['format_ok'] else '❌ 不支持'}")
    print(f"  大小检查: {'✅ 正常' if integrity['size_ok'] else '⚠️ 异常'}")
    print(f"  完整性:   {integrity['message']}")
    print()
    
    if integrity["valid"]:
        print("  🎉 模型文件检查通过！可以正常使用 LLM 推理功能。")
        print()
        print("  下一步操作:")
        print("    python server.py              # 启动服务（本地）")
        print("    docker-compose up -d --build  # 启动服务（Docker）")
        return 0
    else:
        print("  ⚠️ 模型文件可能损坏或不完整！")
        print()
        print_download_guide()
        
        if strict_mode:
            print("  🔴 严格模式：检查未通过")
            return 1
        else:
            print("  🟡 非严格模式：继续启动（可能导致推理异常）")
            return 0


if __name__ == "__main__":
    # 解析命令行参数
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