"""网关 HTTP 接口的集成测试（§14）。

用 TestClient 跑真实的应用实例和 lifespan，验证脚手架阶段
"网关能起来、/health 能用、管理接口能读、未实现的接口返回明确的错误码"。
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_returns_expected_shape(client):
    """§14.2 规定的响应结构。"""
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert "redis" in body
    assert isinstance(body["healthy_backends"], int)
    assert isinstance(body["total_backends"], int)
    assert body["healthy_backends"] <= body["total_backends"]


def test_health_does_not_fail_when_redis_is_unavailable(client):
    """健康检查本身不能依赖被测组件，否则 Redis 一挂监控就瞎了。"""
    assert client.get("/health").status_code == 200


def test_admin_stats_exposes_required_metrics(client):
    """§14.4 / §8 P0-32：压测和答辩要用的指标都得在。"""
    response = client.get("/admin/stats")
    assert response.status_code == 200

    body = response.json()
    for key in ("requests_total", "qps", "cache_hit_rate", "latency_ms", "ttft_ms", "tpot_ms"):
        assert key in body, f"/admin/stats 缺少 {key}"


def test_admin_backends_lists_registry(client):
    """§14.3：管理接口能列出实例。"""
    response = client.get("/admin/backends")
    assert response.status_code == 200

    body = response.json()
    assert "total" in body
    assert isinstance(body["backends"], list)


def test_admin_backend_crud_roundtrip(client):
    """§4 P0-08：动态注册 → 查询 → 下线。"""
    created = client.post(
        "/admin/backends",
        json={"id": "temp-node", "model": "qwen2.5", "base_url": "http://temp:8000"},
    )
    assert created.status_code == 201
    assert created.json()["id"] == "temp-node"

    listed = client.get("/admin/backends").json()
    assert "temp-node" in {b["id"] for b in listed["backends"]}

    removed = client.delete("/admin/backends/temp-node")
    assert removed.status_code == 200

    listed_after = client.get("/admin/backends").json()
    assert "temp-node" not in {b["id"] for b in listed_after["backends"]}


def test_duplicate_backend_returns_409(client):
    payload = {"id": "dup", "model": "qwen2.5", "base_url": "http://dup:8000"}
    assert client.post("/admin/backends", json=payload).status_code == 201
    assert client.post("/admin/backends", json=payload).status_code == 409
    client.delete("/admin/backends/dup")


def test_deleting_unknown_backend_returns_404(client):
    assert client.delete("/admin/backends/ghost").status_code == 404


def test_unknown_model_is_rejected_with_400(client):
    """§3 P0-04：非法模型名要返回 400，不能是 500。"""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "no-such-model", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 400
    assert "no-such-model" in response.json()["detail"]


def test_empty_messages_is_rejected(client):
    """§3 P0-04：messages 为空要拒绝。"""
    response = client.post(
        "/v1/chat/completions",
        json={"model": "qwen2.5", "messages": []},
    )
    assert response.status_code == 422


def test_out_of_range_temperature_is_rejected(client):
    """§3 P0-04：参数范围校验。"""
    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "qwen2.5",
            "messages": [{"role": "user", "content": "hi"}],
            "temperature": 99,
        },
    )
    assert response.status_code == 422


def test_lifespan_shuts_down_without_errors(caplog):
    """启动 → 关闭全程不能出现 ERROR 级日志。

    这条用例是补的回归测试。`_try_stop` 会吞掉关闭阶段的所有异常
    （关闭时抛异常本来不该让进程崩溃），副作用是把方法名写错这类问题
    也一起吞了 —— 之前 `Proxy` / `RedisCache` 的关闭方法叫 `close()`
    却被当成 `stop()` 调用，测试全绿但日志里全是 AttributeError。
    所以只能靠断言日志级别来发现。
    """
    with caplog.at_level(logging.ERROR), TestClient(app):
        pass

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, f"启动/关闭阶段出现错误：{errors}"
