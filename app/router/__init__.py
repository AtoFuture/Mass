"""调度器注册表与工厂。

新增策略只需在这里登记一行，`config.yaml` 的 `routing.strategy` 就能选到它。
"""

from __future__ import annotations

from app.core.config import RoutingConfig
from app.router.base import NoAvailableBackendError, Scheduler
from app.router.dynamic import DynamicScheduler
from app.router.least_conn import LeastConnectionsScheduler
from app.router.round_robin import RoundRobinScheduler

SCHEDULERS: dict[str, type[Scheduler]] = {
    RoundRobinScheduler.name: RoundRobinScheduler,
    LeastConnectionsScheduler.name: LeastConnectionsScheduler,
    DynamicScheduler.name: DynamicScheduler,
}

__all__ = [
    "SCHEDULERS",
    "DynamicScheduler",
    "LeastConnectionsScheduler",
    "NoAvailableBackendError",
    "RoundRobinScheduler",
    "Scheduler",
    "build_scheduler",
]


def build_scheduler(config: RoutingConfig) -> Scheduler:
    """按 `config.strategy` 造调度器。未知策略名直接报错，不要静默降级。"""
    try:
        scheduler_cls = SCHEDULERS[config.strategy]
    except KeyError:
        known = ", ".join(sorted(SCHEDULERS))
        raise ValueError(
            f"未知的调度策略 {config.strategy!r}，可选：{known}"
        ) from None

    if scheduler_cls is DynamicScheduler:
        return DynamicScheduler(weights=config.weights)
    return scheduler_cls()
