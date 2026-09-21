"""后端注册中心测试（§4 P0-07 / P0-08 / P0-09）。"""

from __future__ import annotations

import pytest

from app.backend.model import BackendState
from app.backend.registry import (
    BackendNotFoundError,
    BackendRegistry,
    DuplicateBackendError,
)
from app.core.config import BackendConfig


def _cfg(backend_id: str, model: str = "qwen2.5", max_concurrency: int = 16) -> BackendConfig:
    return BackendConfig(
        id=backend_id,
        model=model,
        base_url=f"http://{backend_id}:8000",
        max_concurrency=max_concurrency,
    )


def test_add_and_list_by_model():
    """§4 P0-09：一个逻辑模型对应多个实例。"""
    registry = BackendRegistry([_cfg("a"), _cfg("b"), _cfg("c", model="other")])
    healthy = registry.list_healthy("qwen2.5")
    assert {b.id for b in healthy} == {"a", "b"}
    assert registry.known_models() == {"qwen2.5", "other"}


def test_duplicate_id_is_rejected():
    registry = BackendRegistry([_cfg("a")])
    with pytest.raises(DuplicateBackendError):
        registry.add(_cfg("a"))


def test_remove_unknown_backend_raises():
    registry = BackendRegistry()
    with pytest.raises(BackendNotFoundError):
        registry.remove("ghost")


def test_dynamic_add_then_remove():
    """§4 P0-08：运行期动态上下线。"""
    registry = BackendRegistry()
    registry.add(_cfg("a"))
    assert len(registry) == 1
    registry.remove("a")
    assert len(registry) == 0
    assert registry.list_healthy("qwen2.5") == []


def test_unhealthy_backend_is_excluded():
    """§4 P0-10：判为 unhealthy 后不能再被选中。"""
    registry = BackendRegistry([_cfg("a"), _cfg("b")])
    registry.set_state("a", BackendState.UNHEALTHY)
    assert {b.id for b in registry.list_healthy("qwen2.5")} == {"b"}


def test_saturated_backend_is_excluded():
    """并发占满的实例不能再进候选集，否则会立刻撞上 §6 P0-20 的 429。"""
    registry = BackendRegistry([_cfg("a", max_concurrency=1), _cfg("b")])
    registry.get("a").acquire()
    assert {b.id for b in registry.list_healthy("qwen2.5")} == {"b"}
    # 释放之后重新回到候选集
    registry.get("a").release()
    assert {b.id for b in registry.list_healthy("qwen2.5")} == {"a", "b"}


def test_unknown_model_returns_empty():
    """§3 P0-04：非法模型名要能被接入层识别出来。"""
    registry = BackendRegistry([_cfg("a")])
    assert registry.list_healthy("not-a-model") == []
    assert "not-a-model" not in registry.known_models()
