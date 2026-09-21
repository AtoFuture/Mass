"""后端注册中心（§4、§15 Backend Registry 接口）。

职责边界：本模块只管"有哪些实例"和"它们现在什么状态"，
**不做选择决策** —— 选谁由 `app/router/` 决定。
"""

from __future__ import annotations

import logging

from app.backend.model import Backend, BackendState
from app.core.config import BackendConfig

logger = logging.getLogger(__name__)


class BackendNotFoundError(KeyError):
    """请求的后端 id 不存在。"""


class DuplicateBackendError(ValueError):
    """尝试注册一个已存在的后端 id。"""


class BackendRegistry:
    """逻辑模型 → 多个物理实例的映射（§4 P0-09）。

    ```text
    qwen2.5 → qwen-a / qwen-b / qwen-c
    ```
    请求里的 `model` 先定位逻辑模型，再由调度器从候选实例中挑一个。
    """

    def __init__(self, backends: list[BackendConfig] | None = None) -> None:
        self._backends: dict[str, Backend] = {}
        for config in backends or []:
            self.add(config)

    # ---------- §15 规定的接口 ----------

    def list_healthy(self, model: str) -> list[Backend]:
        """返回支持 `model` 且当前可接新请求的实例。

        注意这里过滤掉的是 `is_available`（健康 **且** 未超并发），
        而不只是 `state == HEALTHY`。并发已满的实例不该再被选中，
        否则会立刻触发 §6 P0-20 的 429。
        """
        return [
            b for b in self._backends.values() if b.model == model and b.is_available
        ]

    def add(self, config: BackendConfig) -> Backend:
        """注册一个新实例（§4 P0-08 动态注册）。"""
        if config.id in self._backends:
            raise DuplicateBackendError(f"后端 id 已存在：{config.id}")
        backend = Backend(config)
        self._backends[config.id] = backend
        logger.info("注册后端 %s → %s (model=%s)", config.id, config.base_url, config.model)
        return backend

    def remove(self, backend_id: str) -> None:
        """下线一个实例。

        这里做的是**硬移除**（从注册表删除）。如果实例正在处理请求，
        调用方应先把它置为 DRAINING 并等在途请求结束（§4 P0-08）。
        优雅下线的编排属于 A 的 admin 接口，不在本模块。
        """
        if backend_id not in self._backends:
            raise BackendNotFoundError(backend_id)
        del self._backends[backend_id]
        logger.info("下线后端 %s", backend_id)

    # ---------- 查询辅助 ----------

    def get(self, backend_id: str) -> Backend:
        try:
            return self._backends[backend_id]
        except KeyError as exc:
            raise BackendNotFoundError(backend_id) from exc

    def all(self) -> list[Backend]:
        return list(self._backends.values())

    def known_models(self) -> set[str]:
        """当前注册表中出现过的逻辑模型名，用于 §3 P0-04 的非法模型名拒绝。"""
        return {b.model for b in self._backends.values()}

    def set_state(self, backend_id: str, state: BackendState) -> Backend:
        backend = self.get(backend_id)
        backend.state = state
        return backend

    def __len__(self) -> int:
        return len(self._backends)

    def __contains__(self, backend_id: object) -> bool:
        return backend_id in self._backends
