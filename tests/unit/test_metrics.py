"""指标采集测试（§8 P0-32、§10.5 公式）。"""

from __future__ import annotations

import pytest

from app.metrics.collector import MetricsCollector


def test_percentile_interpolates():
    """P50/P95/P99 必须对 100 个均匀样本给出合理值。"""
    collector = MetricsCollector()
    for value in range(1, 101):
        collector.record_request(latency_ms=float(value))

    assert collector._percentile(collector._latencies, 0.5) == pytest.approx(50.5)
    assert collector._percentile(collector._latencies, 0.99) == pytest.approx(99.01, abs=0.1)


def test_percentile_of_empty_series_is_none():
    """冷启动时没有样本，不能返回 0 冒充"零延迟"。"""
    assert MetricsCollector._percentile(MetricsCollector()._latencies, 0.99) is None


def test_cache_hit_rate_uses_lookups_as_denominator():
    """§10.5：命中率 = hits / lookups，不可缓存的请求不进分母。"""
    collector = MetricsCollector()
    for _ in range(4):
        collector.record_cache_lookup()
    collector.record_cache_hit("l1")
    collector.record_cache_hit("l2")

    assert collector.cache_hit_rate == pytest.approx(0.5)
    assert collector.cache_hits_by_layer == {"l1": 1, "l2": 1}


def test_cache_hit_rate_is_zero_without_lookups():
    """没有查询时返回 0，不能除零。"""
    assert MetricsCollector().cache_hit_rate == 0.0


def test_failures_are_counted_separately():
    collector = MetricsCollector()
    collector.record_request(backend_id="a", latency_ms=10, ok=True)
    collector.record_request(
        backend_id="a", latency_ms=20, ok=False, error_type="timeout"
    )

    assert collector.requests_total == 2
    assert collector.requests_success == 1
    assert collector.requests_failed == 1
    assert collector.backend_failures["a"] == 1
    assert collector.failure_rate == pytest.approx(0.5)


def test_ttft_and_tpot_are_tracked():
    """TTFT / TPOT 是决赛"效果验证"30 分的核心指标，必须真实采集。"""
    collector = MetricsCollector()
    for i in range(10):
        collector.record_request(
            backend_id="a", latency_ms=500, ttft_ms=100 + i, tpot_ms=20 + i
        )

    snapshot = collector.snapshot()
    assert snapshot["ttft_ms"]["samples"] == 10
    assert snapshot["tpot_ms"]["samples"] == 10
    assert snapshot["ttft_ms"]["p99"] is not None
    assert snapshot["tpot_ms"]["p99"] is not None


def test_requests_without_streaming_do_not_pollute_ttft():
    """非流式请求测不到 TTFT，不能拿 0 混进分位数。"""
    collector = MetricsCollector()
    collector.record_request(backend_id="a", latency_ms=500)
    collector.record_request(backend_id="a", latency_ms=500, ttft_ms=120)

    assert collector.snapshot()["ttft_ms"]["samples"] == 1


def test_snapshot_contains_all_required_fields():
    """§8 P0-32 列出的指标必须一个不少地出现在 /admin/stats 里。"""
    snapshot = MetricsCollector().snapshot()
    for key in (
        "requests_total",
        "requests_success",
        "requests_failed",
        "qps",
        "latency_ms",
        "ttft_ms",
        "tpot_ms",
        "cache_hit_rate",
        "backend_requests",
        "backend_failures",
    ):
        assert key in snapshot, f"缺少指标 {key}"


def test_qps_counts_recent_requests():
    collector = MetricsCollector()
    for _ in range(20):
        collector.record_request(latency_ms=1)

    assert collector.qps(window_s=10.0) == pytest.approx(2.0, rel=0.5)
