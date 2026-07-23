"""pytest 全局配置（项目根目录）。

- 将项目根目录加入 sys.path，使 `from backend.xxx` / `from foundation.xxx` 绝对导入在测试环境中可用。
- 注入统一的测试环境变量（对应 tests/README.md 中的约定）。
"""

import sys
from pathlib import Path

# 禁用 beartype claw（自动类型装饰导入钩子）。
# claw 的 source_to_code 变换会对含中文日志字符串的源码产生误导性的 SyntaxError，
# 在隔离测试 venv（fastmcp 依赖链会激活 claw）下会导致 bootstrap.py 等模块导入失败。
# 标准导入即可正常加载，不影响运行时行为；此段仅为测试环境稳定性兜底。
try:
    import beartype.claw as _beartype_claw

    for _f in list(sys.meta_path):
        if "beartype" in (getattr(_f, "__module__", "") or type(_f).__module__):
            sys.meta_path.remove(_f)
    _beartype_claw.install = lambda *a, **k: None  # type: ignore[assignment]
except Exception:
    pass

import pytest

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _test_environment(monkeypatch):
    """为所有测试注入一致的测试环境变量。"""
    monkeypatch.setenv("TEST_ENV", "true")
    monkeypatch.setenv("LLM_TEST_MODE", "mock")
    monkeypatch.setenv("TEST_DB", ":memory:")
    yield
