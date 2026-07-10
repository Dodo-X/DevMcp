"""
DevPartner Agent 配置管理系统

- YAML 配置文件加载
- 环境变量覆盖
- 单例模式 + 热重载支持
- v6.0: pyproject.toml 作为版本号单一来源
"""

import os
import sys
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field


def get_project_version() -> str:
    """
    从 pyproject.toml 读取版本号（单一来源）
    
    回退策略：
    1. pyproject.toml（项目根目录）
    2. 环境变量 DEVPARTNER_VERSION
    3. 硬编码默认值
    
    版本号变动只需修改 pyproject.toml，所有引用处自动同步。
    """
    # 尝试从环境变量获取
    env_version = os.environ.get("DEVPARTNER_VERSION")
    if env_version:
        return env_version

    # 寻找 pyproject.toml
    try:
        # 从当前文件向上找项目根目录
        current = Path(__file__).resolve().parent.parent.parent
        toml_path = current / "pyproject.toml"
        if toml_path.exists():
            content = toml_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("version"):
                    # version = "x.y.z"
                    version = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return version
    except Exception:
        pass

    return "0.0.0"


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
    """数据存储路径配置 - 所有数据统一在 data/ 目录下
    PONYTATIL: 只保留 root_dir，其余路径动态推导。当需要自定义路径时再添加字段。
    """
    root_dir: str = "./data"

    @property
    def databases_dir(self) -> str:
        return f"{self.root_dir}/databases"

    @property
    def daily_logs_dir(self) -> str:
        return f"{self.root_dir}/daily_logs"

    @property
    def logs_dir(self) -> str:
        return f"{self.root_dir}/logs"

    @property
    def logs_archive_dir(self) -> str:
        return f"{self.root_dir}/logs_archive"

    @property
    def memories_dir(self) -> str:
        return f"{self.root_dir}/memories"

    @property
    def backups_dir(self) -> str:
        return f"{self.root_dir}/backups"

    @property
    def reports_dir(self) -> str:
        return f"{self.root_dir}/reports"

    @property
    def temp_dir(self) -> str:
        return f"{self.root_dir}/temp"


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
    known_mcp_servers: list[str] = field(default_factory=lambda: [
        "@modelcontextprotocol/server-filesystem",
        "@modelcontextprotocol/server-github",
        "@modelcontextprotocol/server-sequential-thinking",
        "@modelcontextprotocol/server-fetch",
        "@modelcontextprotocol/server-memory",
        "@modelcontextprotocol/server-git",
    ])


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
class LLMConfig:
    """
    本地 LLM 配置（v7.3.0 — Ollama 引擎）
    
    通过 Ollama HTTP API（http://localhost:11434）进行推理。
    前提：用户已安装并运行 Ollama，且已拉取所需模型。
    
    特性：
    - 零模型文件管理，模型由 Ollama 管理
    - OpenAI 兼容的 /api/chat 端点
    - 自动 GPU 加速（Ollama 内置）
    """
    # ── 功能开关 ──
    enabled: bool = True                                # LLM 总开关

    # ── Ollama 连接 ──
    ollama_model: str = "qwen3"                        # Ollama 模型名称（ollama list 查看）
    ollama_timeout: int = 120                          # 推理超时（秒）
    
    # ── 生成参数 ──
    max_tokens: int = 2048                             # 最大生成 token 数
    max_input_chars: int = 8000                        # 最大输入字符数
    temperature: float = 0.3                           # 生成温度
    top_p: float = 0.9                                 # Top-P 核采样
    top_k: int = 40                                    # Top-K 候选词限制
    repeat_penalty: float = 1.1                        # 重复惩罚
    
    # ── 启动行为 ──
    preload: bool = True                               # 启动时验证 Ollama 连接
    
    # ── 容错机制 ──
    fallback_to_rules: bool = True                     # 模型不可用时降级到规则引擎
    
    # ── 功能开关 ──
    enhance_analysis: bool = True                      # 对话分析增强 ⭐ 推荐
    enhance_file_parsing: bool = True                  # 文件解析增强
    enhance_daily_summary: bool = True                 # LLM 智能日报生成 ⭐ 强烈推荐
    enhance_self_improvement: bool = True              # LLM 自我改进建议 ⭐ 推荐


@dataclass
class AgentConfig:
    """Agent 总配置"""
    name: str = "devpartner-agent"
    version: str = field(default_factory=get_project_version)
    description: str = "DevPartner 智能管家 - 会话管理 + 异步任务 + 知识图谱 + Web Dashboard"
    server: ServerConfig = field(default_factory=ServerConfig)
    data: DataConfig = field(default_factory=DataConfig)
    log_service: LogServiceConfig = field(default_factory=LogServiceConfig)
    dialogue_service: DialogueServiceConfig = field(default_factory=DialogueServiceConfig)
    evolution: EvolutionServiceConfig = field(default_factory=EvolutionServiceConfig)
    data_lifecycle: DataLifecycleConfig = field(default_factory=DataLifecycleConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


# ═══════════════════════════════════════════════════════════
# 配置管理器
# ═══════════════════════════════════════════════════════════

class ConfigManager:
    """配置管理器：支持热重载"""

    _config: Optional[AgentConfig] = None

    def load(self, config_path: str = "config.yaml") -> AgentConfig:
        """加载配置，优先级：默认值 < YAML文件 < 环境变量"""
        config = AgentConfig()

        # 1. 加载 YAML 文件（依次尝试 cwd 与 devpartner_agent 目录）
        yaml_candidates = [
            Path(config_path),
            Path(__file__).resolve().parent.parent / "config.yaml",
        ]
        for yaml_path in yaml_candidates:
            if yaml_path.exists():
                try:
                    import yaml
                    with open(yaml_path, "r", encoding="utf-8") as f:
                        yaml_data = yaml.safe_load(f) or {}
                    config = self._merge_yaml(config, yaml_data)
                    break
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
            for k in ["root_dir", "databases_dir", "daily_logs_dir",
                       "logs_dir", "logs_archive_dir",
                       "memories_dir", "backups_dir", "reports_dir", "temp_dir"]:
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

        # llm
        if "llm" in data:
            llm = data["llm"]
            for k, v in llm.items():
                if hasattr(config.llm, k):
                    setattr(config.llm, k, v)

        return config

    def _apply_env_overrides(self, config: AgentConfig) -> AgentConfig:
        """环境变量覆盖"""
        env_map = {
            "DEVPARTNER_AGENT_PORT": ("server", "port", int),
            "DEVPARTNER_AGENT_HOST": ("server", "host", str),
            "DEVPARTNER_AGENT_LOG_LEVEL": ("logging", "level", str),
            "DEVPARTNER_LOG_RETENTION_DAYS": ("data_lifecycle", "log_retention_days", int),
            "DEVPARTNER_LLM_ENABLED": ("llm", "enabled", lambda v: v.lower() in ("1", "true", "yes")),
            "DEVPARTNER_LLM_MODEL": ("llm", "ollama_model", str),
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
            config.data.daily_logs_dir,
            config.data.logs_dir,
            config.data.logs_archive_dir,
            config.data.memories_dir,
            config.data.backups_dir,
            config.data.reports_dir,
            config.data.temp_dir,
        ]
        dirs = [d for d in dirs if d]
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
# PONYTATIL: 模块级单例, 当需要多实例时改为依赖注入

_config_manager_instance: Optional[ConfigManager] = None

def get_config_manager() -> ConfigManager:
    """获取全局配置管理器实例"""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance

def get_config() -> AgentConfig:
    """获取全局配置单例"""
    return get_config_manager().config