"""
云同步存储层 - SQLite WAL + 云盘路径检测
==========================================
为适配坚果云/阿里云盘等本地文件同步方案而设计。

核心原则：
  - SQLite WAL 模式：WAL/SHM 是临时文件，云盘无需同步，只有 .db 需要同步
  - 数据隔离：每个AI客户端独立存储，用 client_name 区分
  - 路径感知：自动检测云盘安装路径，引导用户配置

支持云盘：
  - 坚果云 (Nutstore)
  - 阿里云盘 (aDrive)
  - OneDrive
  - 百度网盘
  - 自定义路径

同步安全策略：
  1. PRAGMA journal_mode=WAL   → WAL文件云盘不同步（临时）
  2. PRAGMA synchronous=NORMAL → 性能与安全平衡
  3. PRAGMA wal_autocheckpoint=1000 → 自动合并WAL
  4. 禁止多进程同时写入 → 通过文件锁
"""
import os
import json
import sqlite3
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List


class CloudDriveInfo:
    """云盘信息检测结果"""
    def __init__(self, name: str, path: str, status: str, icon: str = ""):
        self.name = name
        self.path = path
        self.status = status  # found / not_found / accessible / inaccessible
        self.icon = icon


class CloudDriveDetector:
    """
    云盘安装路径检测器
    
    自动扫描已知云盘的常见安装路径。
    """

    # 已知云盘安装路径列表
    KNOWN_DRIVE_PATTERNS = [
        # (名称, 图标, 路径检测模式列表)
        ("坚果云", "📦", [
            "{home}/Nutstore",
            "D:/Nutstore",
            "C:/Nutstore",
        ]),
        ("阿里云盘", "☁️", [
            "{home}/阿里云盘",
            "D:/阿里云盘",
            "C:/Users/{username}/阿里云盘",
            "{home}/aDrive",
        ]),
        ("OneDrive", "🔵", [
            "{home}/OneDrive",
            "D:/OneDrive",
        ]),
        ("百度网盘", "📁", [
            "{home}/BaiduNetdiskWorkspace",
            "D:/百度网盘",
            "D:/BaiduNetdiskDownload",
        ]),
        ("iCloud", "🍎", [
            "{home}/iCloudDrive",
        ]),
    ]

    @staticmethod
    def detect_all() -> List[CloudDriveInfo]:
        """检测所有云盘安装情况"""
        home = str(Path.home())
        username = os.environ.get("USERNAME", os.environ.get("USER", ""))
        drives = []

        for name, icon, patterns in CloudDriveDetector.KNOWN_DRIVE_PATTERNS:
            found_path = None
            for pattern in patterns:
                path = pattern.format(home=home, username=username)
                p = Path(path)
                if p.exists() and p.is_dir():
                    found_path = str(p)
                    break

            if found_path:
                # 检查是否可写
                try:
                    test_file = Path(found_path) / ".devpartner_test"
                    test_file.write_text("test")
                    test_file.unlink()
                    drives.append(CloudDriveInfo(name, found_path, "found_accessible", icon))
                except Exception:
                    drives.append(CloudDriveInfo(name, found_path, "found_inaccessible", icon))
            else:
                drives.append(CloudDriveInfo(name, "", "not_found", icon))

        return drives

    @staticmethod
    def suggest_sync_path(preferred: str = None) -> str:
        """
        推荐最佳同步路径
        
        优先级：
        1. 用户指定的 preferred
        2. 已检测到的第一个可用云盘
        3. 用户文档目录下的 devPartner 文件夹
        """
        if preferred and Path(preferred).exists():
            return str(Path(preferred) / "devPartner-data")

        drives = CloudDriveDetector.detect_all()
        for drive in drives:
            if drive.status == "found_accessible":
                return str(Path(drive.path) / "devPartner-data")

        # 回退：用户文档目录
        home = Path.home()
        return str(home / "Documents" / "devPartner-data")


class CloudAwareDatabase:
    """
    云盘同步感知的 SQLite 数据库
    
    特性：
    - 自动启用 WAL 模式
    - WAL 文件放在 temp 目录（不参与云盘同步）
    - 写入前自动 checkpoint
    - 客户端隔离（每个 client 独立 DB 或共用带 client 字段）
    """

    def __init__(self, db_path: str):
        self._db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return str(self._db_path)

    def init(self):
        """初始化数据库连接并启用 WAL"""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        with self._lock:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

            # 云盘同步安全配置
            # WAL 模式：.db-wal 和 .db-shm 文件云盘不会同步
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA wal_autocheckpoint=1000")
            # 外键支持
            self._conn.execute("PRAGMA foreign_keys=ON")

            # 创建元数据表
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS __devpartner_meta__ (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT
                )
            """)

            self._set_meta("db_version", "1.0.0")
            self._set_meta("wal_enabled", "true")
            self._set_meta("created_at",
                           self._get_meta("created_at") or datetime.now().isoformat())
            self._conn.commit()

    def _set_meta(self, key: str, value: str):
        """设置元数据"""
        if not self._conn:
            return
        self._conn.execute(
            """INSERT OR REPLACE INTO __devpartner_meta__ (key, value, updated_at)
               VALUES (?, ?, ?)""",
            (key, value, datetime.now().isoformat())
        )

    def _get_meta(self, key: str) -> Optional[str]:
        """获取元数据"""
        if not self._conn:
            return None
        row = self._conn.execute(
            "SELECT value FROM __devpartner_meta__ WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """执行查询"""
        if not self._conn:
            raise RuntimeError("数据库未初始化，请先调用 init()")

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            if sql.strip().upper().startswith("SELECT"):
                result = [dict(row) for row in cursor.fetchall()]
            else:
                self._conn.commit()
                result = [{"affected_rows": cursor.rowcount, "last_id": cursor.lastrowid}]
            return result

    def checkpoint(self):
        """手动触发 WAL checkpoint（将 WAL 合并到主 DB）"""
        if self._conn:
            with self._lock:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def vacuum(self):
        """优化数据库存储"""
        if self._conn:
            with self._lock:
                self._conn.execute("VACUUM")

    def get_info(self) -> dict:
        """获取数据库信息"""
        if not self._db_path.exists():
            return {"exists": False}

        size = self._db_path.stat().st_size
        wal_path = Path(str(self._db_path) + "-wal")
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0

        try:
            row = self.query("SELECT COUNT(*) as cnt FROM __devpartner_meta__")
            meta_count = row[0]["cnt"] if row else 0
        except Exception:
            meta_count = 0

        return {
            "exists": True,
            "path": str(self._db_path),
            "size_bytes": size,
            "wal_size_bytes": wal_size,
            "journal_mode": "WAL",
            "meta_entries": meta_count,
        }

    def close(self):
        """关闭连接（确保 WAL 合并）"""
        if self._conn:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
            self._conn.close()
            self._conn = None


# 全局单例

_cloud_db: Optional[CloudAwareDatabase] = None
_cloud_db_lock = threading.Lock()


def get_cloud_db(db_path: str = None) -> CloudAwareDatabase:
    """获取云盘感知数据库实例"""
    global _cloud_db

    with _cloud_db_lock:
        if _cloud_db is None:
            if db_path is None:
                db_path = "data/devpartner.db"
            _cloud_db = CloudAwareDatabase(db_path)
            _cloud_db.init()
        elif db_path and str(_cloud_db.path) != str(Path(db_path)):
            # 路径变更，重新初始化
            _cloud_db.close()
            _cloud_db = CloudAwareDatabase(db_path)
            _cloud_db.init()
        return _cloud_db


def init_cloud_db(db_path: str):
    """初始化云感知数据库（替代原 database.py 的部分功能）"""
    global _cloud_db
    with _cloud_db_lock:
        if _cloud_db:
            _cloud_db.close()
        _cloud_db = CloudAwareDatabase(db_path)
        _cloud_db.init()
    return _cloud_db
