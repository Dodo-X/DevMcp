"""
devPartner 配置管理系统
- YAML 配置文件加载
- 环境变量覆盖
- 热重载支持
"""
import os
import yaml
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class DeploymentConfig:
    """部署配置（v3.0 新增 - 支持 ModelScope 等远程部署）"""
    platform: str = "local"  # local / modelscope / custom
    api_url: str = ""  # ModelScope API 地址
    health_check_path: str = "/health"


@dataclass
class DatabaseConfig:
    local_db: str = "data/devpartner.db"
    shared_db: str = "D:/trae-archive/toptown_tracker/work_tracker.db"
    agent_name: str = "devpartner"
    report_dir: str = "D:/trae-archive/toptown_tracker/devpartner-reports"


@dataclass
class LogConfig:
    daily_logs_dir: str = "data/daily_logs"
    log_archive_dir: str = "data/logs_archive"
    tool_archive_dir: str = "data/tool_archive"
    log_retention_days: int = 30


@dataclass
class DialogueConfig:
    dialogue_file: str = "D:/trae-archive/toptown_tracker/agent_dialogue.md"
    state_file: str = "data/.dialogue_state.json"
    pending_file: str = "data/.pending_dialogue.json"


@dataclass
class EvolutionConfig:
    enabled: bool = True
    auto_discover_interval_hours: int = 24
    backup_before_upgrade: bool = True
    max_auto_upgrades_per_day: int = 3
    known_mcp_servers: list = field(default_factory=lambda: [
        "@modelcontextprotocol/server-filesystem",
        "@modelcontextprotocol/server-github",
        "@modelcontextprotocol/server-sequential-thinking",
        "@modelcontextprotocol/server-fetch",
        "@modelcontextprotocol/server-sqlite",
        "@modelcontextprotocol/server-git",
        "@modelcontextprotocol/server-memory",
        "@upstash/context7-mcp",
        "@anthropic/mcp-server-brave-search",
        "@browserbasehq/mcp-server-browserbase",
        "@anthropic/mcp-server-puppeteer",
    ])


@dataclass
class MindMapConfig:
    output_dir: str = "data/mindmaps"
    default_theme: str = "default"
    engine: str = "mermaid"


@dataclass
class CloudSyncConfig:
    enabled: bool = True
    data_root: str = ""  # 空=自动检测，设置后所有数据在此目录下
    sync_drive: str = "auto"  # auto / nutstore / alidrive / onedrive / custom
    wal_enabled: bool = True
    auto_checkpoint_interval: int = 1000  # WAL 自动合并页面数
    db_backup_before_sync: bool = True


@dataclass
class IdentityConfig:
    auto_detect: bool = True
    auto_register: bool = False  # 是否自动注册检测到的客户端
    session_timeout_minutes: int = 120


@dataclass
class AppConfig:
    name: str = "devPartner"
    version: str = "1.0.0"
    host: str = "0.0.0.0"
    port: int = 8080
    transport: str = "sse"
    project_root: str = "."
    deployment: DeploymentConfig = field(default_factory=DeploymentConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    log: LogConfig = field(default_factory=LogConfig)
    dialogue: DialogueConfig = field(default_factory=DialogueConfig)
    evolution: EvolutionConfig = field(default_factory=EvolutionConfig)
    mindmap: MindMapConfig = field(default_factory=MindMapConfig)
    cloud_sync: CloudSyncConfig = field(default_factory=CloudSyncConfig)
    identity: IdentityConfig = field(default_factory=IdentityConfig)


class ConfigManager:
    """配置管理器：单例模式，支持热重载"""

    _instance: Optional["ConfigManager"] = None
    _config: Optional[AppConfig] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, config_path: str = "config.yaml") -> AppConfig:
        """加载配置，优先级：默认值 < YAML文件 < 环境变量"""
        config = AppConfig()

        # 1. 尝试加载 YAML 文件
        yaml_path = Path(config_path)
        if yaml_path.exists():
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
            config = self._merge_yaml(config, yaml_data)

        # 2. 环境变量覆盖
        config = self._apply_env_overrides(config)

        # 3. 确保必要目录存在
        self._ensure_dirs(config)

        self._config = config
        return config

    def _merge_yaml(self, config: AppConfig, data: dict) -> AppConfig:
        """将 YAML 数据合并到配置对象"""
        if "app" in data:
            a = data["app"]
            for k in ["name", "version", "host", "port", "transport", "project_root"]:
                if k in a:
                    setattr(config, k, a[k])

        if "deployment" in data:
            dp = data["deployment"]
            for k in ["platform", "api_url", "health_check_path"]:
                if k in dp:
                    setattr(config.deployment, k, dp[k])

        if "database" in data:
            d = data["database"]
            for k in ["local_db", "shared_db", "agent_name", "report_dir"]:
                if k in d:
                    setattr(config.database, k, d[k])

        if "log" in data:
            l = data["log"]
            for k in ["daily_logs_dir", "log_archive_dir", "tool_archive_dir", "log_retention_days"]:
                if k in l:
                    setattr(config.log, k, l[k])

        if "dialogue" in data:
            dl = data["dialogue"]
            for k in ["dialogue_file", "state_file", "pending_file"]:
                if k in dl:
                    setattr(config.dialogue, k, dl[k])

        if "evolution" in data:
            e = data["evolution"]
            for k in ["enabled", "auto_discover_interval_hours", "backup_before_upgrade", "max_auto_upgrades_per_day"]:
                if k in e:
                    setattr(config.evolution, k, e[k])
            if "known_mcp_servers" in e:
                config.evolution.known_mcp_servers = e["known_mcp_servers"]

        if "mindmap" in data:
            m = data["mindmap"]
            for k in ["output_dir", "default_theme", "engine"]:
                if k in m:
                    setattr(config.mindmap, k, m[k])

        if "cloud_sync" in data:
            c = data["cloud_sync"]
            for k in ["enabled", "data_root", "sync_drive", "wal_enabled",
                       "auto_checkpoint_interval", "db_backup_before_sync"]:
                if k in c:
                    setattr(config.cloud_sync, k, c[k])

        if "identity" in data:
            i = data["identity"]
            for k in ["auto_detect", "auto_register", "session_timeout_minutes"]:
                if k in i:
                    setattr(config.identity, k, i[k])

        return config

    def _apply_env_overrides(self, config: AppConfig) -> AppConfig:
        """环境变量覆盖配置"""
        env_map = {
            "DEVPARTNER_HOST": ("host", str),
            "DEVPARTNER_PORT": ("port", int),
            "DEVPARTNER_TRANSPORT": ("transport", str),
            "DEVPARTNER_DATA_ROOT": ("cloud_sync", "data_root", str),
            "DEVPARTNER_SHARED_DB": ("database", "shared_db", str),
            "DEVPARTNER_REPORT_DIR": ("database", "report_dir", str),
            "GITHUB_TOKEN": ("github_token", str),
        }

        for env_key, target in env_map.items():
            value = os.environ.get(env_key)
            if value:
                if len(target) == 2:  # Simple attribute
                    attr, typ = target
                    setattr(config, attr, typ(value))
                else:  # Nested attribute
                    parent_attr, child_attr, typ = target
                    setattr(getattr(config, parent_attr), child_attr, typ(value))

        return config

    def _ensure_dirs(self, config: AppConfig):
        """确保必要目录存在"""
        # 如果配置了 cloud_sync.data_root，优先使用
        data_root = config.cloud_sync.data_root
        dirs = [
            Path(config.database.local_db).parent,
            Path(config.database.shared_db).parent,
            Path(config.database.report_dir),
            Path(config.log.daily_logs_dir),
            Path(config.log.log_archive_dir),
            Path(config.log.tool_archive_dir),
            Path(config.mindmap.output_dir),
        ]
        if data_root:
            dirs.append(Path(data_root))

        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def config(self) -> AppConfig:
        if self._config is None:
            return self.load()
        return self._config

    def reload(self) -> AppConfig:
        """热重载配置"""
        return self.load()


# 全局便捷访问
def get_config() -> AppConfig:
    return ConfigManager().config
