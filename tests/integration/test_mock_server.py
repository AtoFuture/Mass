"""Mock 服务集成测试（§9 P0-35）。

Mock 是三人解耦的基础，也是初赛"仿真测试方案"10 分的证据来源，
所以它本身必须是被测过的。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mock.mock_server import MockConfig, create_app


def _app(**overrides) -> TestClient:
    """造一个零延迟的 Mock，测试跑得快且结果确定。"""
    defaults = dict(
        name="test-mock",
        prefill_ms=0.0,
        per_token_ms=0.0,
        jitter_ratio=0.0,
        min_tokens=4,
        max_tokens=4,
    )
    return TestClient(create_app(MockConfig(**{**defaults, **overrides})))


def _payload(**overrides) -> dict:
    return {
        "model": "qwen2.5",
        "messages": [{"role": "user", "content": "解释一下负载均衡"}],
        **overrides,
    }


def test_health():
    with _app() as client:
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert body["name"] == "test-mock"


def test_models_endpoint_is_openai_compatible():
    with _app() as client:
        body = client.get("/v1/models").json()
        assert body["object"] == "list"
        assert body["data"][0]["id"] == "qwen2.5"


def test_non_streaming_response_shape():
    with _app() as client:
        response = client.post("/v1/chat/completions", json=_payload(max_tokens=4))
        assert response.status_code == 200

        body = response.json()
        assert body["object"] == "chat.completion"
        assert body["choices"][0]["message"]["role"] == "assistant"
        assert body["choices"][0]["finish_reason"] == "stop"
        assert body["choices"][0]["message"]["content"]
        assert body["usage"]["completion_tokens"] == 4


def test_streaming_emits_sse_and_terminates_with_done():
    """§3 P0-03：流式必须是 `data: ...\\n\\n`，并以 `data: [DONE]` 结束。"""
    with _app() as client:
        response = client.post("/v1/chat/completions", json=_payload(stream=True))
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        lines = [ln for ln in response.text.splitlines() if ln.startswith("data: ")]
        assert lines, "没有产生任何 SSE 数据行"
        assert lines[-1] == "data: [DONE]"

        # 除 [DONE] 外每一行都必须是合法 JSON
        chunks = [json.loads(ln.removeprefix("data: ")) for ln in lines[:-1]]
        assert all(c["object"] == "chat.completion.chunk" for c in chunks)


def test_streaming_first_chunk_carries_role():
    """首块带 role，是 OpenAI 流式协议的约定，客户端据此初始化消息。"""
    with _app() as client:
        response = client.post("/v1/chat/completions", json=_payload(stream=True))
        first = json.loads(
            response.text.splitlines()[0].removeprefix("data: ")
        )
        assert first["choices"][0]["delta"]["role"] == "assistant"


def test_streaming_token_count_matches_max_tokens():
    """输出长度取 min(请求的 max_tokens, Mock 实例自身的上限)。"""
    with _app(max_tokens=8) as client:
        response = client.post(
            "/v1/chat/completions", json=_payload(stream=True, max_tokens=6)
        )
        content_chunks = [
            json.loads(ln.removeprefix("data: "))
            for ln in response.text.splitlines()
            if ln.startswith("data: ") and ln != "data: [DONE]"
        ]
        deltas = [c for c in content_chunks if c["choices"][0]["delta"].get("content")]
        assert len(deltas) == 6


def test_error_injection_returns_configured_status():
    """故障注入是演示熔断的依据，必须可控。"""
    with _app(error_rate=1.0, error_status=503) as client:
        response = client.post("/v1/chat/completions", json=_payload())
        assert response.status_code == 503
        assert response.json()["error"]["type"] == "mock_upstream_error"


def test_error_injection_applies_to_streaming_too():
    with _app(error_rate=1.0) as client:
        response = client.post("/v1/chat/completions", json=_payload(stream=True))
        assert "mock_upstream_error" in response.text


def test_config_hot_update_changes_behaviour():
    """演示"让某个节点突然变慢"就靠这个接口，不能需要重启进程。"""
    with _app(prefill_ms=0.0) as client:
        before = client.get("/mock/config").json()["config"]["prefill_ms"]
        assert before == 0.0

        updated = client.post("/mock/config", json={"prefill_ms": 3000})
        assert updated.status_code == 200
        assert client.get("/mock/config").json()["config"]["prefill_ms"] == 3000


def test_config_rejects_unknown_fields():
    with _app() as client:
        response = client.post("/mock/config", json={"nope": 1})
        assert response.status_code == 400


def test_gpu_memory_ratio_is_exposed():
    """网关的调度评分需要读这个值（§4 P1-11）。"""
    with _app(gpu_memory_ratio=0.77) as client:
        body = client.get("/mock/config").json()
        assert body["gpu_memory_ratio"] == 0.77


def test_inflight_counter_returns_to_zero():
    """在途计数必须归零，否则网关会误判实例满载。"""
    with _app() as client:
        for _ in range(3):
            client.post("/v1/chat/completions", json=_payload())
        assert client.get("/mock/config").json()["inflight"] == 0


def test_inflight_returns_to_zero_after_streaming():
    with _app() as client:
        client.post("/v1/chat/completions", json=_payload(stream=True))
        assert client.get("/mock/config").json()["inflight"] == 0
