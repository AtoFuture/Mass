"""轮询基线测试（§5 P0-12）。

这些用例同时也是加权轮询的回归测试 —— B 之后重构调度器时不能破坏它们。
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.backend.model import Backend
from app.backend.registry import BackendRegistry
from app.core.config import BackendConfig
from app.core.context import Message, RequestContext
from app.router.base import NoAvailableBackendError
from app.router.round_robin import RoundRobinScheduler


def _backend(backend_id: str, weight: int = 1) -> Backend:
    return Backend(
        BackendConfig(
            id=backend_id,
            model="qwen2.5",
            base_url=f"http://{backend_id}:8000",
            weight=weight,
        )
    )


def _ctx() -> RequestContext:
    return RequestContext(
        model="qwen2.5",
        messages=[Message(role="user", content="hi")],
    )


async def test_empty_candidates_raise():
    """§15：候选为空必须抛错，由接入层翻译成 503，不能返回 None。"""
    with pytest.raises(NoAvailableBackendError):
        await RoundRobinScheduler().select(_ctx(), [])


async def test_equal_weights_are_evenly_distributed():
    scheduler = RoundRobinScheduler()
    backends = [_backend("a"), _backend("b"), _backend("c")]

    counts: Counter[str] = Counter()
    for _ in range(30):
        counts[(await scheduler.select(_ctx(), backends)).id] += 1

    assert counts == {"a": 10, "b": 10, "c": 10}


async def test_weights_are_respected():
    """权重 3:1 时，8 次选择应给出 6:2。"""
    scheduler = RoundRobinScheduler()
    backends = [_backend("heavy", weight=3), _backend("light", weight=1)]

    counts: Counter[str] = Counter()
    for _ in range(8):
        counts[(await scheduler.select(_ctx(), backends)).id] += 1

    assert counts == {"heavy": 6, "light": 2}


async def test_any_window_gets_proportional_share():
    """平滑加权轮询的意义：没有任何长度为 Σweight 的窗口被饿死。

    3:1 时，任意连续 4 次选择都必须是 3 次 heavy + 1 次 light。
    朴素加权轮询会给出 h,h,h,l,h,h,h,l —— 前三次全压在一个实例上，
    瞬时并发集中；平滑版本不会出现这种窗口。
    """
    scheduler = RoundRobinScheduler()
    backends = [_backend("heavy", weight=3), _backend("light", weight=1)]

    picked = [(await scheduler.select(_ctx(), backends)).id for _ in range(8)]

    assert picked.count("heavy") == 6
    assert picked.count("light") == 2

    for start in range(len(picked) - 3):
        window = picked[start : start + 4]
        assert window.count("heavy") == 3, f"窗口 {start} 分布失衡：{window}"
        assert window.count("light") == 1, f"窗口 {start} 分布失衡：{window}"


async def test_zero_weights_degrade_to_equal_round_robin():
    """全部权重配成 0 时不应除零，等价于等权轮询。"""
    scheduler = RoundRobinScheduler()
    backends = [_backend("a", weight=0), _backend("b", weight=0)]

    counts: Counter[str] = Counter()
    for _ in range(10):
        counts[(await scheduler.select(_ctx(), backends)).id] += 1

    assert counts == {"a": 5, "b": 5}


async def test_new_backend_joins_routing():
    """新注册的实例应立即参与调度（§4 P0-08）。"""
    registry = BackendRegistry([_backend("a").config])
    scheduler = RoundRobinScheduler()

    await scheduler.select(_ctx(), registry.list_healthy("qwen2.5"))

    registry.add(_backend("b").config)
    candidates = registry.list_healthy("qwen2.5")
    assert {b.id for b in candidates} == {"a", "b"}

    # 新实例确实会被选中，而不只是出现在候选列表里
    picked = {(await scheduler.select(_ctx(), candidates)).id for _ in range(10)}
    assert picked == {"a", "b"}
