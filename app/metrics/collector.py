"""指标采集（§8 P0-32、§15 Metrics 接口）。

必须能算出来的量（§8 P0-32 原文）：
请求数、成功/失败、QPS、平均/P95/P99 延迟、TTFT、TPOT、系统吞吐量、
缓存命中率、各后端请求占比、后端故障次数。

**TTFT 和 TPOT 是重点**：决赛"效果验证"单项 30 分，指标就是
P99 TTFT 提升率和 TPOT 提升率（见命题书评分表）。所以这两个字段从
Mock 阶段就必须真实采集，不能等接了真机再补 —— Mock 服务的流式接口
（`mock/mock_server.py`）已经能产生逐 token 时间戳。

实现说明：用滑动窗口 `deque` 存样本，取分位数时排序。样本量在压测下
会很大，窗口时长由 `window_s` 控制；如果后续发现排序成为瓶颈，
再换成 HDR 直方图或 `numpy.percentile`，不要在初赛阶段提前优化。
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass


@dataclass(slots=True)
class _Sample:
    at: float
    value: float


class MetricsCollector:
    """进程内指标聚合器。单事件循环下无需加锁。"""

    def __init__(self, window_s: float = 300.0) -> None:
        self.window_s = window_s
        self.started_at = time.time()

        self._latencies: deque[_Sample] = deque()
        self._ttft: deque[_Sample] = deque()
        self._tpot: deque[_Sample] = deque()
        self._request_times: deque[float] = deque()

        self.requests_total = 0
        self.requests_success = 0
        self.requests_failed = 0
        self.error_types: Counter[str] = Counter()
        self.backend_requests: Counter[str] = Counter()
        self.backend_failures: Counter[str] = Counter()
        self.backend_latency_ms: dict[str, float] = {}

        self.cache_lookups = 0
        self.cache_hits = 0
        self.cache_hits_by_layer: Counter[str] = Counter()

    # ---------- 写入（§15 规定的四个方法） ----------

    def record_request(
        self,
        *,
        backend_id: str | None = None,
        latency_ms: float = 0.0,
        ok: bool = True,
        ttft_ms: float | None = None,
        tpot_ms: float | None = None,
        error_type: str | None = None,
    ) -> None:
        """记录一次已完成的请求。无论成功失败都应调用，否则 QPS 会偏低。"""
        now = time.monotonic()
        self.requests_total += 1
        self._request_times.append(now)
        self._latencies.append(_Sample(now, latency_ms))

        if ttft_ms is not None:
            self._ttft.append(_Sample(now, ttft_ms))
        if tpot_ms is not None:
            self._tpot.append(_Sample(now, tpot_ms))

        if backend_id:
            self.backend_requests[backend_id] += 1

        if ok:
            self.requests_success += 1
        else:
            self.requests_failed += 1
            if error_type:
                self.error_types[error_type] += 1
            if backend_id:
                self.backend_failures[backend_id] += 1

        self._trim(now)

    def record_cache_hit(self, layer: str) -> None:
        """记录一次缓存命中。`layer` 取 "l1" / "l2" / "semantic"。"""
        self.cache_hits += 1
        self.cache_hits_by_layer[layer] += 1

    def record_cache_lookup(self) -> None:
        """记录一次缓存查询。

        命中率的分母是 lookups 而不是请求总数（§10.5 公式），
        因为不可缓存的请求根本不该进入分母。
        """
        self.cache_lookups += 1

    def record_backend_latency(self, backend_id: str, latency_ms: float) -> None:
        self.backend_latency_ms[backend_id] = latency_ms

    def record_error(self, error_type: str, backend_id: str | None = None) -> None:
        """记录一次错误。已经在 `record_request(ok=False)` 里记过的不要重复调用。"""
        self.error_types[error_type] += 1
        if backend_id:
            self.backend_failures[backend_id] += 1

    # ---------- 窗口维护 ----------

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_s
        for series in (self._latencies, self._ttft, self._tpot):
            while series and series[0].at < cutoff:
                series.popleft()
        while self._request_times and self._request_times[0] < cutoff:
            self._request_times.popleft()

    @staticmethod
    def _percentile(samples: deque[_Sample], q: float) -> float | None:
        """线性插值分位数。`q` 取 0~1。空样本返回 None。"""
        if not samples:
            return None
        values = sorted(s.value for s in samples)
        if len(values) == 1:
            return values[0]
        pos = q * (len(values) - 1)
        low = int(pos)
        high = min(low + 1, len(values) - 1)
        frac = pos - low
        return values[low] * (1 - frac) + values[high] * frac

    # ---------- 读取 ----------

    def qps(self, window_s: float = 10.0) -> float:
        """最近 `window_s` 秒的实际 QPS。"""
        now = time.monotonic()
        cutoff = now - window_s
        recent = sum(1 for t in self._request_times if t >= cutoff)
        return recent / window_s

    @property
    def cache_hit_rate(self) -> float:
        if self.cache_lookups == 0:
            return 0.0
        return self.cache_hits / self.cache_lookups

    @property
    def failure_rate(self) -> float:
        if self.requests_total == 0:
            return 0.0
        return self.requests_failed / self.requests_total

    def snapshot(self, backends: list[object] | None = None) -> dict[str, object]:
        """§14.4 `/admin/stats` 的响应体。

        Args:
            backends: `Backend` 列表，用于附上各实例当前状态。
        """
        backend_stats: dict[str, object] = {}
        for backend in backends or []:
            snapshot = getattr(backend, "snapshot", None)
            if callable(snapshot):
                backend_stats[str(getattr(backend, "id", "?"))] = snapshot()

        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "requests_total": self.requests_total,
            "requests_success": self.requests_success,
            "requests_failed": self.requests_failed,
            "failure_rate": round(self.failure_rate, 4),
            "qps": round(self.qps(), 2),
            "latency_ms": {
                "avg": self._round(self._percentile(self._latencies, 0.5)),
                "p95": self._round(self._percentile(self._latencies, 0.95)),
                "p99": self._round(self._percentile(self._latencies, 0.99)),
            },
            "ttft_ms": {
                "avg": self._round(self._percentile(self._ttft, 0.5)),
                "p95": self._round(self._percentile(self._ttft, 0.95)),
                "p99": self._round(self._percentile(self._ttft, 0.99)),
                "samples": len(self._ttft),
            },
            "tpot_ms": {
                "avg": self._round(self._percentile(self._tpot, 0.5)),
                "p95": self._round(self._percentile(self._tpot, 0.95)),
                "p99": self._round(self._percentile(self._tpot, 0.99)),
                "samples": len(self._tpot),
            },
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "cache_lookups": self.cache_lookups,
            "cache_hits": self.cache_hits,
            "cache_hits_by_layer": dict(self.cache_hits_by_layer),
            "error_types": dict(self.error_types),
            "backend_requests": dict(self.backend_requests),
            "backend_failures": dict(self.backend_failures),
            "backends": backend_stats,
        }

    @staticmethod
    def _round(value: float | None) -> float | None:
        return None if value is None else round(value, 2)


#: 全局默认实例。§15 的接口示例是 `metrics.record_request(...)` 这种模块级调用，
#: 但测试里应该直接 `MetricsCollector()` 造新实例，不要依赖这个全局对象。
metrics = MetricsCollector()
