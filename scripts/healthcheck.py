#!/usr/bin/env python3
"""
DevPartner 健康检查脚本 v6.0.2
用于 Docker HEALTHCHECK 指令
支持 ModelScope 创空间和其他 Docker 环境
"""

import sys
import urllib.request


def check_health():
    """检查服务健康状态 — 优先使用轻量 /health 端点"""
    endpoints = [
        "http://localhost:7860/health",  # 快速健康检查（首选）
        "http://localhost:7860/",  # 根路径
    ]

    for i, url in enumerate(endpoints):
        try:
            req = urllib.request.Request(url, method="HEAD")
            response = urllib.request.urlopen(req, timeout=5)
            if response.status == 200:
                print(f"✅ 服务正常运行 ({url})")
                sys.exit(0)
        except urllib.error.HTTPError as e:
            if e.code < 500:
                print(f"✅ 服务正常运行 ({url}, HTTP {e.code})")
                sys.exit(0)
            print(f"⚠️ 端点 {url} 返回 HTTP {e.code}")
        except Exception as e:
            if i == len(endpoints) - 1:  # 最后一个也失败
                print(f"❌ 健康检查失败: {e}")
                sys.exit(1)

    sys.exit(1)


if __name__ == "__main__":
    check_health()
