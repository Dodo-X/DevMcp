#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DevPartner 健康检查脚本
用于 Docker HEALTHCHECK 指令
"""

import urllib.request
import sys


def check_health():
    """检查服务健康状态"""
    try:
        response = urllib.request.urlopen(
            'http://localhost:7860/dashboard',
            timeout=5
        )
        print('✅ 服务正常运行')
        sys.exit(0)
    except Exception as e:
        print(f'❌ 健康检查失败: {e}')
        sys.exit(1)


if __name__ == '__main__':
    check_health()