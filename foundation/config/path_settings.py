"""全局路径设置：统一项目根目录与数据目录推导。

放在 foundation 层，供全后端复用，避免各处用脆弱的
os.path.dirname(__file__) 链条推导根目录。
"""

import os
from pathlib import Path

# foundation/config/path_settings.py -> foundation -> <PROJECT_ROOT>
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DATA_DIR = PROJECT_ROOT / "data"
DATABASES_DIR = DATA_DIR / "databases"
LOGS_DIR = DATA_DIR / "logs"
VAULT_DIR = DATA_DIR / "Knowledge Library"


def ensure_data_dirs() -> None:
    for d in (DATA_DIR, DATABASES_DIR, LOGS_DIR):
        os.makedirs(d, exist_ok=True)
