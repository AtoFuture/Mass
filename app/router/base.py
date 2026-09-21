"""调度器抽象基类（§15 Scheduler 接口）。

契约（三人必须共同遵守）：
- `select()` 只做**选择**，不发请求、不记指标、不改 `Backend` 的运行时状态；
- 选择依据全部从 `Backend` 的只读属性上读（§4 P1-11）；
- 候选列表由调用方（接入层）用 `registry.list_healthy(model)` 预先过滤好，
  调度器**可以**再过滤，但**不得**假设列表非空 —— 空列表要抛
  `NoAvailableBackendError`，由接入层翻译成 503。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.backend.model import Backend
from app.core.context import RequestContext


class NoAvailableBackendError(RuntimeError):
    """没有任何可用的后端实例能接这个请求。"""

    def __init__(self, model: str) -> None:
        super().__init__(f"模型 {model!r} 当前没有可用后端实例")
        self.model = model


class Scheduler(ABC):
    """所有调度策略的基类。新增策略只需继承并实现 `select()`。"""

    #: 与 `config.yaml` 里 `routing.strategy` 对应的注册名
    name: str = "base"

    @abstractmethod
    async def select(
        self, request_ctx: RequestContext, backends: list[Backend]
    ) -> Backend:
        """从候选实例中选一个返回。

        Args:
            request_ctx: 当前请求上下文，含 model / 输入长度估计 / prefix_hash。
            backends: 已过滤的候选实例；`select` 内部不得修改这个列表。

        Raises:
            NoAvailableBackendError: `backends` 为空或全部不可用。
        """
        raise NotImplementedError
