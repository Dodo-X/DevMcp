"""
DevPartner Agent 配置管理系统

- YAML 配置文件加载
- 环境变量覆盖
- 单例模式 + 热重载支持
- v6.0: pyproject.toml 作为版本号单一来源
"""

import logging

logger = logging.getLogger(__name__)


import os
from dataclasses import dataclass, field
from pathlib import Path


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
        logger.warning("get_project_version: 未预期的异常被静默捕获（P-17 收口）", exc_info=True)
        pass

    return "0.0.0"


# ═══════════════════════════════════════════════════════════
# 配置数据类
# ═══════════════════════════════════════════════════════════


@dataclass
class ServerConfig:
    """服务器配置"""

    host: str = "0.0.0.0"
    port: int = 7860
    transport: str = "streamable-http"


@dataclass
class DataConfig:
    """数据存储路径配置 - 所有数据统一在 data/ 目录下
    NOTE: 只保留 root_dir，其余路径动态推导。当需要自定义路径时再添加字段。
    """

    root_dir: str = "./data"

    @property
    def databases_dir(self) -> str:
        return f"{self.root_dir}/databases"

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
class DataLifecycleConfig:
    """数据生命周期管理（v8.0 增强：分层归档策略）"""

    log_retention_days: int = 90
    db_cleanup_days: int = 90
    auto_cleanup: bool = True
    auto_cleanup_interval_hours: int = 24
    backup_before_cleanup: bool = True
    conversation_hot_days: int = 30  # 热数据：最近30天，完整保留
    conversation_warm_days: int = 180  # 温数据：30-180天，保留摘要+信号，清理steps详情
    conversation_cold_days: int = 365  # 冷数据：180-365天，标记 archive_tier='archived'
    archive_before_cleanup: bool = True  # 清理前先标记 archive_tier='archived'
    ensure_md_exported_before_archive: bool = True  # 归档前确保MD已导出
    pending_analyses_max_retry: int = 10  # pending_analyses 最大重试次数，超过则标记failed


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
    enabled: bool = True  # LLM 总开关

    # ── Ollama 连接 ──
    ollama_model: str = "qwen2.5:7b-instruct-q4_K_M"  # Ollama 模型名称（ollama list 查看）
    ollama_timeout: int = 300  # 单次 LLM 推理超时（秒），任务级别超时 10800s (3h)
    ollama_num_parallel: int = 1  # Ollama 并行请求数（v9.5.3: CPU 推理默认 1）

    # ── 生成参数 ──
    max_tokens: int = 2048  # 最大生成 token 数
    max_input_chars: int = 8000  # 最大输入字符数
    temperature: float = 0.3  # 生成温度
    top_p: float = 0.9  # Top-P 核采样
    top_k: int = 40  # Top-K 候选词限制
    repeat_penalty: float = 1.1  # 重复惩罚

    # ── 启动行为 ──
    preload: bool = True  # 启动时验证 Ollama 连接

    # ── 功能开关 ──
    enhance_analysis: bool = True  # 对话分析增强 ⭐ 推荐
    enhance_file_parsing: bool = True  # 文件解析增强
    enhance_daily_summary: bool = True  # LLM 智能日报生成 ⭐ 强烈推荐
    enhance_self_improvement: bool = True  # LLM 自我改进建议 ⭐ 推荐
    enhance_profile_merge: bool = True  # 每日用户画像合并 ⭐ v8.0
    enhance_system_merge: bool = True  # 每日系统认知合并 ⭐ v8.0
    enhance_weekly_report: bool = True  # 周报 LLM 生成 ⭐ v8.5.4
    enhance_monthly_report: bool = True  # 月报 LLM 生成 ⭐ v8.5.4
    enhance_annual_report: bool = True  # 年报 LLM 生成 ⭐ v8.5.4


@dataclass
class AgentConfig:
    """Agent 总配置"""

    name: str = "devpartner-agent"
    version: str = field(default_factory=get_project_version)
    description: str = "DevPartner 智能管家 - 会话管理 + 异步任务 + 知识图谱"
    server: ServerConfig = field(default_factory=ServerConfig)
    data: DataConfig = field(default_factory=DataConfig)
    data_lifecycle: DataLifecycleConfig = field(default_factory=DataLifecycleConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


# ═══════════════════════════════════════════════════════════
# 配置管理器
# ═══════════════════════════════════════════════════════════


class ConfigManager:
    """配置管理器：支持热重载"""

    _config: AgentConfig | None = None

    def load(self, config_path: str = "config.yaml") -> AgentConfig:
        """加载配置，优先级：默认值 < YAML文件 < 环境变量"""
        config = AgentConfig()

        # 1. 加载 YAML 文件（依次尝试 cwd 与 foundation/config 目录）
        yaml_candidates = [
            Path(config_path),
            Path(__file__).resolve().parent / "config.yaml",
        ]
        for yaml_path in yaml_candidates:
            if yaml_path.exists():
                try:
                    import yaml

                    with open(yaml_path, encoding="utf-8") as f:
                        yaml_data = yaml.safe_load(f) or {}
                    config = self._merge_yaml(config, yaml_data)
                    break
                except Exception:
                    logger.warning(
                        "ConfigManager.load: 未预期的异常被静默捕获（P-17 收口）", exc_info=True
                    )
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
            for k in [
                "root_dir",
                "databases_dir",
                "logs_dir",
                "logs_archive_dir",
                "memories_dir",
                "backups_dir",
                "reports_dir",
                "temp_dir",
            ]:
                if k in d:
                    setattr(config.data, k, d[k])

        # data_lifecycle
        if "data_lifecycle" in data:
            dl = data["data_lifecycle"]
            for k, v in dl.items():
                if hasattr(config.data_lifecycle, k):
                    setattr(config.data_lifecycle, k, v)

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
            "DEVPARTNER_LLM_ENABLED": (
                "llm",
                "enabled",
                lambda v: v.lower() in ("1", "true", "yes"),
            ),
            "DEVPARTNER_LLM_MODEL": ("llm", "ollama_model", str),
            "DEVPARTNER_LLM_NUM_PARALLEL": ("llm", "ollama_num_parallel", int),
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
# NOTE: 模块级单例，当需要多实例时改为依赖注入

_config_manager_instance: ConfigManager | None = None


def get_config() -> AgentConfig:
    """获取全局配置单例"""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance.config
