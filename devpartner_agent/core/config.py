"""
DevPartner Agent 配置管理系统

- YAML 配置文件加载
- 环境变量覆盖
- 单例模式 + 热重载支持
"""

import os
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════
# 配置数据类
# ═══════════════════════════════════════════════════════════

@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = "0.0.0.0"
    port: int = 8082
    transport: str = "stdio"


@dataclass
class DataConfig:
    """数据存储路径配置"""
    root_dir: str = "./data"
    databases_dir: str = "./data/databases"
    logs_dir: str = "./data/logs"
    memories_dir: str = "./data/memories"
    backups_dir: str = "./data/backups"
    temp_dir: str = "./data/temp"


@dataclass
class LogServiceConfig:
    """日志服务配置"""
    enabled: bool = True
    log_retention_days: int = 90
    auto_cleanup: bool = True


@dataclass
class DialogueServiceConfig:
    """跨AI对话服务配置"""
    enabled: bool = True
    max_message_history: int = 500


@dataclass
class EvolutionServiceConfig:
    """进化引擎配置"""
    enabled: bool = True
    max_changes_per_day: int = 3
    require_approval: bool = True
    backup_before_change: bool = True
    auto_discover_interval_hours: int = 24


@dataclass
class DataLifecycleConfig:
    """数据生命周期管理"""
    log_retention_days: int = 90
    db_cleanup_days: int = 90
    auto_cleanup: bool = True
    auto_cleanup_interval_hours: int = 24  # 自动清理间隔（小时）
    backup_before_cleanup: bool = True


@dataclass
class RulesConfig:
    """规则引擎配置"""
    auto_load_builtin: bool = True
    trigger_on_startup: bool = True


@dataclass
class LoggingConfig:
    """日志配置"""
    level: str = "DEBUG"
    format: str = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"
    file: str = "./data/logs/agent.log"


@dataclass
class AgentConfig:
    """Agent 总配置"""
    name: str = "devpartner-agent"
    version: str = "2.0.0"
    description: str = "DevPartner 智能管家 - 有状态、有记忆、自进化"
    server: ServerConfig = field(default_factory=ServerConfig)
    data: DataConfig = field(default_factory=DataConfig)
    log_service: LogServiceConfig = field(default_factory=LogServiceConfig)
    dialogue_service: DialogueServiceConfig = field(default_factory=DialogueServiceConfig)
    evolution: EvolutionServiceConfig = field(default_factory=EvolutionServiceConfig)
    data_lifecycle: DataLifecycleConfig = field(default_factory=DataLifecycleConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ═══════════════════════════════════════════════════════════
# 配置管理器
# ═══════════════════════════════════════════════════════════

class ConfigManager:
    """配置管理器：单例模式，支持热重载"""

    _instance: Optional["ConfigManager"] = None
    _config: Optional[AgentConfig] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, config_path: str = "config.yaml") -> AgentConfig:
        """加载配置，优先级：默认值 < YAML文件 < 环境变量"""
        config = AgentConfig()

        # 1. 加载 YAML 文件
        yaml_path = Path(config_path)
        if yaml_path.exists():
            try:
                import yaml
                with open(yaml_path, "r", encoding="utf-8") as f:
                    yaml_data = yaml.safe_load(f) or {}
                config = self._merge_yaml(config, yaml_data)
            except Exception:
                pass

        # 2. 环境变量覆盖
        config = self._apply_env_overrides(config)

        # 3. 确保必要目录存在
        self._ensure_dirs(config)

        self._config = config
        return config

    def _merge_yaml(self, config: AgentConfig, data: dict) -> AgentConfig:
        """将 YAML 数据合并到配置对象"""
        # agent 元信息
        if "agent" in data:
            a = data["agent"]
            for k in ["name", "version", "description"]:
                if k in a:
                    setattr(config, k, a[k])

        # server
        if "server" in data:
            s = data["server"]
            for k in ["host", "port", "transport"]:
                if k in s:
                    setattr(config.server, k, s[k])

        # data
        if "data" in data:
            d = data["data"]
            for k in ["root_dir", "databases_dir", "logs_dir",
                       "memories_dir", "backups_dir", "temp_dir"]:
                if k in d:
                    setattr(config.data, k, d[k])

        # services
        if "services" in data:
            svc = data["services"]
            for svc_name, svc_data in svc.items():
                if hasattr(config, svc_name):
                    target = getattr(config, svc_name)
                    for k, v in svc_data.items():
                        if hasattr(target, k):
                            setattr(target, k, v)

        # rules
        if "rules" in data:
            r = data["rules"]
            for k in ["auto_load_builtin", "trigger_on_startup"]:
                if k in r:
                    setattr(config.rules, k, r[k])

        # logging
        if "logging" in data:
            l = data["logging"]
            for k in ["level", "format", "file"]:
                if k in l:
                    setattr(config.logging, k, l[k])

        return config

    def _apply_env_overrides(self, config: AgentConfig) -> AgentConfig:
        """环境变量覆盖"""
        env_map = {
            "DEVPARTNER_AGENT_PORT": ("server", "port", int),
            "DEVPARTNER_AGENT_HOST": ("server", "host", str),
            "DEVPARTNER_AGENT_LOG_LEVEL": ("logging", "level", str),
            "DEVPARTNER_LOG_RETENTION_DAYS": ("data_lifecycle", "log_retention_days", int),
        }

        for env_key, target in env_map.items():
            value = os.environ.get(env_key)
            if value:
                parent_attr, child_attr, typ = target
                try:
                    setattr(getattr(config, parent_attr), child_attr, typ(value))
                except (ValueError, AttributeError):
                    pass

        return config

    def _ensure_dirs(self, config: AgentConfig):
        """确保必要目录存在"""
        dirs = [
            config.data.root_dir,
            config.data.databases_dir,
            config.data.logs_dir,
            config.data.memories_dir,
            config.data.backups_dir,
            config.data.temp_dir,
        ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)

    @property
    def config(self) -> AgentConfig:
        if self._config is None:
            return self.load()
        return self._config

    def reload(self) -> AgentConfig:
        """热重载配置"""
        return self.load()


# ═══════════════════════════════════════════════════════════
# 全局便捷访问
# ═══════════════════════════════════════════════════════════

def get_config() -> AgentConfig:
    """获取全局配置单例"""
    return ConfigManager().config
