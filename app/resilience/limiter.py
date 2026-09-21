"""限流与并发控制（§6 P0-20、P1-23）。

【待实现 —— 负责人：A】

两层，别混在一起：

**1. 并发限制（P0，必须先做）**
   - 网关全局最大并发：`config.server.max_concurrency`
   - 单后端最大并发：`Backend.max_concurrency`（已在 `registry.list_healthy()`
     里通过 `is_available` 体现）
   超过上限时进入短队列或返回 429，避免把 GPU 打挂。

**2. 限流（P1，可以后做）**
   - Token Bucket 或 Sliding Window
   - 按 API Key 的每分钟请求数、全局 QPS、可选按模型

并发控制的正确性关键在**释放时机**：客户端断连、后端超时、流式传输中途
异常，都必须走到释放逻辑，否则并发计数只增不减，最终所有后端都被判定为
"满载"而返回 429（§3 P0-03 专门强调了这一点）。
实现时用 `asyncio.Semaphore` 或 `try/finally` 包住整个请求生命周期，
不要分散在多处 `release()`。

建议先只做并发限制，限流等 §6 P0 全部完成后再补 —— 见 §19 的执行计划，
P1 排在 10/2 之后。
"""

from __future__ import annotations


class ConcurrencyLimiter:
    """全局并发闸门。"""

    def __init__(self, max_concurrency: int = 100) -> None:
        self.max_concurrency = max_concurrency
        self.active = 0

    def try_acquire(self) -> bool:
        """尝试占用一个槽位。返回 False 表示已达上限，调用方应返回 429。"""
        raise NotImplementedError("P0-20 并发限制：待 A 实现")

    def release(self) -> None:
        raise NotImplementedError("P0-20 并发限制：待 A 实现")


class RateLimiter:
    """按 Key 的速率限制。P1，可后做（§6 P1-23）。"""

    def __init__(self, rate_per_minute: int = 60) -> None:
        self.rate_per_minute = rate_per_minute

    def allow(self, key: str) -> bool:
        raise NotImplementedError("P1-23 限流：待 A 实现")
