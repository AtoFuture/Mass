"""L1 进程内缓存（§7 P0-24）。

【待实现 —— 负责人：B】

要求：
- 淘汰策略：LRU 或 LFU（二选一，在报告里说明选择理由）
- TTL 到期失效
- 容量上限：`config.cache.l1.max_items`
- 命中/未命中计数，供 §14.4 `/admin/stats` 的 `cache_hit_rate` 使用

实现提示：`collections.OrderedDict` + `move_to_end()` 就是现成的 LRU，
不需要引入 `cachetools` 依赖。TTL 建议惰性判断（`get` 时检查是否过期）
而不是起后台清理任务，避免多一个需要关闭的资源。

考点：L1 在单进程内存里，所以它只对**同一个网关进程**的重复请求有效。
多副本部署时命中率会被摊薄 —— 这一点在报告里必须说明，
否则压测数据会显得比理论值差，而原因说不清。
"""

from __future__ import annotations

from app.cache.base import CachedResponse, CacheLayer
from app.core.context import CacheContext


class MemoryCache(CacheLayer):
    layer_name = "l1"

    def __init__(self, max_items: int = 1000, ttl_s: int = 300) -> None:
        self.max_items = max_items
        self.ttl_s = ttl_s
        self.hits = 0
        self.misses = 0

    async def get(self, cache_ctx: CacheContext) -> CachedResponse | None:
        raise NotImplementedError("P0-24 L1 本地缓存：待 B 实现")

    async def set(
        self, cache_ctx: CacheContext, response: CachedResponse, ttl_s: int
    ) -> None:
        raise NotImplementedError("P0-24 L1 本地缓存：待 B 实现")

    async def invalidate(self, key: str) -> None:
        raise NotImplementedError("P0-24 L1 本地缓存：待 B 实现")
