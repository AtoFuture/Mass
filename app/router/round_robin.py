"""轮询基线策略（§5 P0-12）。

用途：作为最简单的对照组。**不感知负载**，所以在慢节点场景下会明显劣化
—— 这正是后面 Dynamic 策略要证明的东西（§10.2 的 C 组 vs B 组）。

实现用的是 **平滑加权轮询**（smooth weighted round-robin，nginx 同款算法）。
朴素加权轮询会把一个实例的权重连续用完，产生 A,A,A,B 这种突发；
平滑版本保证**任意连续 `Σweight` 次选择中，每个实例被选中的次数恰好等于它的权重**。
以 `[A(w=3), B(w=1)]` 为例，平滑版本给出 A,A,B,A | A,A,B,A ——
任意连续 4 次里 A 恰好 3 次、B 恰好 1 次，不存在被完全饿死的窗口。
当所有 `weight` 都是 1 时，它与朴素轮询行为完全一致。

【本文件是脚手架提供的可运行基线，由 B 负责后续维护与测试】
"""

from __future__ import annotations

from app.backend.model import Backend
from app.core.context import RequestContext
from app.router.base import NoAvailableBackendError, Scheduler


class RoundRobinScheduler(Scheduler):
    name = "round_robin"

    def __init__(self) -> None:
        #: backend_id -> 当前累计权重，算法内部状态
        self._current_weight: dict[str, int] = {}

    async def select(
        self, request_ctx: RequestContext, backends: list[Backend]
    ) -> Backend:
        if not backends:
            raise NoAvailableBackendError(request_ctx.model)

        weights = [max(0, b.weight) for b in backends]
        total = sum(weights)
        if total <= 0:
            # 全部权重配成 0，等价于等权轮询
            weights = [1] * len(backends)
            total = len(backends)

        best: Backend | None = None
        best_weight = -1
        for backend, weight in zip(backends, weights, strict=True):
            current = self._current_weight.get(backend.id, 0) + weight
            self._current_weight[backend.id] = current
            if current > best_weight:
                best, best_weight = backend, current

        assert best is not None  # backends 非空且 total > 0，循环必然命中
        self._current_weight[best.id] -= total
        return best
