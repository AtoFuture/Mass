"""后端实例的数据模型与运行时状态（§4 P1-11）。

分成两层：
- `BackendConfig`（在 `core/config.py`）：来自 YAML 的静态配置，启动后不变。
- `Backend`（本文件）：静态配置 + 运行时状态，调度器的评分输入全部来自这里。

模块分工（§12）：本文件由 A 维护，B 的调度器**只读**其中的属性，
不得直接改 `_recent_latencies` 等内部结构。需要新指标时找 A 加属性。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import StrEnum

from app.core.config import BackendConfig


class BackendState(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"  # 管理员主动下线，不再接新请求，等在途请求结束


@dataclass(slots=True)
class _Sample:
    at: float
    value: float


class Backend:
    """一个可被调度的模型实例。

    并发安全说明：网关是单事件循环的 asyncio 应用，只要不在持锁状态下
    `await`，普通计数器的自增自减就是原子的。`acquire()` / `release()`
    刻意设计成同步方法，就是为了不引入 `await` 造成计数漂移。
    """

    #: 滑动窗口长度，用于计算平均延迟和错误率（§4 P1-11）
    WINDOW_S = 60.0
    #: prefix 亲和表的容量上限，防止长跑内存泄漏（§5 P1-16）
    MAX_PREFIX_ENTRIES = 512

    def __init__(self, config: BackendConfig) -> None:
        self.config = config
        self.state = BackendState.HEALTHY
        self.active_requests = 0
        self.gpu_memory_ratio: float | None = None
        self.last_seen: float = time.monotonic()
        self.consecutive_failures = 0

        self._latencies: deque[_Sample] = deque()
        self._errors: deque[_Sample] = deque()
        #: prefix_hash -> 最近一次由本实例处理该前缀的时间戳
        self._prefix_affinity: dict[str, float] = {}
        self._total_requests = 0
        self._total_errors = 0

    # ---------- 静态属性透传，方便调度器少写一层 ----------

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def base_url(self) -> str:
        return self.config.base_url

    @property
    def weight(self) -> int:
        return self.config.weight

    @property
    def max_concurrency(self) -> int:
        return self.config.max_concurrency

    # ---------- 生命周期 ----------

    def acquire(self) -> None:
        """占用一个并发槽位。必须在请求开始时调用。"""
        self.active_requests += 1

    def release(self) -> None:
        """释放并发槽位。

        §3 P0-03 明确要求客户端断开时也要释放，否则并发计数会只增不减，
        最终把实例永久踢出候选集。调用方必须在 finally 里调用。
        """
        self.active_requests = max(0, self.active_requests - 1)

    def record_success(self, latency_ms: float) -> None:
        now = time.monotonic()
        self._latencies.append(_Sample(now, latency_ms))
        self._errors.append(_Sample(now, 0.0))
        self._total_requests += 1
        self.consecutive_failures = 0
        self.last_seen = now
        self._trim(now)

    def record_error(self) -> None:
        now = time.monotonic()
        self._errors.append(_Sample(now, 1.0))
        self._total_requests += 1
        self._total_errors += 1
        self.consecutive_failures += 1
        self._trim(now)

    def record_health_check(self, ok: bool) -> None:
        """健康检查结果。与业务请求的成功/失败分开统计（§4 P0-10）。"""
        if ok:
            self.last_seen = time.monotonic()
            if self.state is BackendState.UNHEALTHY:
                self.state = BackendState.HEALTHY
                self.consecutive_failures = 0
        else:
            self.state = BackendState.UNHEALTHY

    def _trim(self, now: float) -> None:
        cutoff = now - self.WINDOW_S
        while self._latencies and self._latencies[0].at < cutoff:
            self._latencies.popleft()
        while self._errors and self._errors[0].at < cutoff:
            self._errors.popleft()

    # ---------- 调度器读取的指标（§4 P1-11） ----------

    @property
    def avg_latency_ms(self) -> float | None:
        """滑动窗口平均延迟。窗口内无样本时返回 None，由调度器决定如何补。"""
        if not self._latencies:
            return None
        return sum(s.value for s in self._latencies) / len(self._latencies)

    @property
    def error_rate(self) -> float:
        if not self._errors:
            return 0.0
        return sum(s.value for s in self._errors) / len(self._errors)

    @property
    def is_available(self) -> bool:
        """能否接新请求：状态健康且未超并发上限。"""
        return (
            self.state is BackendState.HEALTHY
            and self.active_requests < self.max_concurrency
        )

    # ---------- Prefix 亲和（§5 P1-16） ----------

    def record_prefix(self, prefix_hash: str) -> None:
        """记录"本实例刚刚处理过这个前缀"。"""
        if not prefix_hash:
            return
        self._prefix_affinity[prefix_hash] = time.monotonic()
        if len(self._prefix_affinity) > self.MAX_PREFIX_ENTRIES:
            oldest = min(self._prefix_affinity, key=self._prefix_affinity.__getitem__)
            del self._prefix_affinity[oldest]

    def prefix_affinity(self, prefix_hash: str) -> float:
        """返回 0~1 的亲和分。刚处理过接近 1，超出窗口衰减到 0。

        调度器用 `-η·H_i` 的形式奖励亲和（§5 P0-14），所以这里返回的
        是"奖励值"，越大越该选它。
        """
        if not prefix_hash:
            return 0.0
        last = self._prefix_affinity.get(prefix_hash)
        if last is None:
            return 0.0
        age = time.monotonic() - last
        if age >= self.WINDOW_S:
            return 0.0
        return 1.0 - age / self.WINDOW_S

    # ---------- 上报 ----------

    def snapshot(self) -> dict[str, object]:
        """给 /admin/backends 和 /admin/stats 用的只读快照（§14.3、§14.4）。"""
        return {
            "id": self.id,
            "model": self.model,
            "base_url": self.base_url,
            "state": self.state.value,
            "healthy": self.state is BackendState.HEALTHY,
            "weight": self.weight,
            "active": self.active_requests,
            "max_concurrency": self.max_concurrency,
            "avg_latency_ms": (
                round(v, 2) if (v := self.avg_latency_ms) is not None else None
            ),
            "error_rate": round(self.error_rate, 4),
            "gpu_memory_ratio": self.gpu_memory_ratio,
            "total_requests": self._total_requests,
            "total_errors": self._total_errors,
        }
