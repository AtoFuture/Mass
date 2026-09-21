"""L2 Redis 缓存（§7 P0-25）。

【待实现 —— 负责人：B】

要求：
- 跨网关进程共享
- TTL 由 `config.cache.redis.ttl_s` 控制
- **Redis 异常必须自动降级**：连不上、超时、序列化失败，一律按未命中处理，
  只记 warning 日志，不能让推理请求失败（§22 创新点 C 的核心卖点）
- Key 带命名空间和版本前缀，形如 `smartmaas:v1:{cache_key}`，
  这样 §7 P0-29 的"模型版本变更导致失效"可以整段前缀废弃

序列化用 `json` 即可（`CachedResponse` 是扁平结构）。
不要用 `pickle` —— 反序列化不可信数据有安全风险，而且跨 Python 版本不稳。

验收（§27 DoD）：必须有 1 个正常测试 + 1 个异常测试，
异常测试建议用 `fakeredis` 或直接把 client 换成会抛异常的 mock，
断言"Redis 挂了但请求仍然成功返回"。
"""

from __future__ import annotations

from app.cache.base import CachedResponse, CacheLayer
from app.core.context import CacheContext

KEY_NAMESPACE = "smartmaas:v1"


class RedisCache(CacheLayer):
    layer_name = "l2"

    def __init__(self, url: str = "redis://redis:6379/0", ttl_s: int = 1800) -> None:
        self.url = url
        self.ttl_s = ttl_s
        self.hits = 0
        self.misses = 0
        self._client = None

    async def connect(self) -> None:
        """建立连接池。应在应用启动时调用，失败只记日志不阻断启动。"""
        raise NotImplementedError("P0-25 Redis L2：待 B 实现")

    async def close(self) -> None:
        raise NotImplementedError("P0-25 Redis L2：待 B 实现")

    async def get(self, cache_ctx: CacheContext) -> CachedResponse | None:
        raise NotImplementedError("P0-25 Redis L2：待 B 实现")

    async def set(
        self, cache_ctx: CacheContext, response: CachedResponse, ttl_s: int
    ) -> None:
        raise NotImplementedError("P0-25 Redis L2：待 B 实现")

    async def invalidate(self, key: str) -> None:
        raise NotImplementedError("P0-25 Redis L2：待 B 实现")
