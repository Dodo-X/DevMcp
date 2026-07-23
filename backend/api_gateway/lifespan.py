"""服务启动/销毁生命周期钩子。

启动：backend.core.bootstrap.ensure_ready()（DB、调度器、任务恢复）。
销毁：预留优雅关闭（flush 队列 / 关闭连接）。
"""

from foundation.logger_framework.logger_proxy import get_logger

logger = get_logger("api_gateway.lifespan")


def on_startup() -> None:
    from backend.core.bootstrap import ensure_ready

    ensure_ready()
    logger.info("api_gateway startup done")


def on_shutdown() -> None:
    logger.info("api_gateway shutdown")
