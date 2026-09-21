"""最小连接数策略（§5 P0-13）。

【待实现 —— 负责人：B】

算法：选 `active_requests` 最小的实例。平手时按 `weight` 归一化后再比，
即比较 `active_requests / weight`，否则高权重的实例拿不到应有的份额。

与 Round Robin 的差别：RR 只看"轮到谁"，LeastConn 看"谁现在最闲"。
在请求耗时方差大的场景（长上下文 + 短问答混合）下 LeastConn 应明显更好，
这个对比是 §10.2 C 组实验的一部分。

实现要点：
- 未收到任何响应时所有实例 `active_requests` 都是 0，此时应退化为轮询，
  否则会把所有冷启动流量全压到列表里的第一个实例。
- 不要在这里改 `active_requests` —— 占用/释放由接入层调用
  `Backend.acquire()/release()` 负责（见 `backend/model.py` 的并发安全说明）。
"""

from __future__ import annotations

from app.backend.model import Backend
from app.core.context import RequestContext
from app.router.base import NoAvailableBackendError, Scheduler


class LeastConnectionsScheduler(Scheduler):
    name = "least_conn"

    async def select(
        self, request_ctx: RequestContext, backends: list[Backend]
    ) -> Backend:
        if not backends:
            raise NoAvailableBackendError(request_ctx.model)
        raise NotImplementedError("P0-13 最小连接数策略：待 B 实现")
