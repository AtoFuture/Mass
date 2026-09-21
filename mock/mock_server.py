"""Mock 模型服务（§9 P0-35）—— 负责人：C。

一个 OpenAI 兼容的假后端，用来在真机就绪前跑通整条链路，
并**制造**出初赛"仿真测试方案"（10 分）需要的故障场景。

设计要点：把 TTFT 和 TPOT 的成因拆开建模

    TTFT ≈ prefill_ms + 输入长度 × prefill_per_kchar_ms + jitter
    TPOT ≈ per_token_ms + jitter

这不是随便定的。真实推理里首字延迟主要由 prefill（处理整段输入）决定，
之后每个 token 由 decode 决定。拆开建模才能演示清楚：

- **Prefix Cache 有效** → prefill 变短 → TTFT 降。用 `--prefill-ms` 调。
- **长上下文拖慢首字** → `--prefill-per-kchar-ms` 让 prefill 随输入增长，
  这样 §5 P1-15 的"上下文长度感知调度"才有东西可测。
- **TPOT 与输入长度无关** → 只有解码批次大小会影响它。

启动：

    python -m mock.mock_server --name mock-a --port 9001 --prefill-ms 300
    python -m mock.mock_server --name mock-c --port 9003 --prefill-ms 3000 \\
        --error-rate 0.1 --fail-period-s 60 --fail-duration-s 20

运行期改配置（**演示熔断/慢节点剔除就靠这个**，不用重启进程）：

    curl -X POST localhost:9003/mock/config -H 'Content-Type: application/json' \\
         -d '{"prefill_ms": 8000}'
    curl localhost:9003/mock/config
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import time
import uuid
from dataclasses import asdict, dataclass

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

#: 用来拼假回复的词表。输出内容本身无意义，只要能产生
#: 长度可控、逐 token 可数的流即可。
_WORDS = [
    "负载", "均衡", "缓存", "调度", "网关", "推理", "延迟", "吞吐", "并发", "显存",
    "前缀", "命中", "熔断", "降级", "路由", "语义", "向量", "集群", "副本", "队列",
    "超时", "重试", "指标", "观测", "部署", "容器", "扩缩", "预热",
]


@dataclass
class MockConfig:
    """单个 Mock 实例的行为参数。可通过 `POST /mock/config` 热更新。"""

    name: str = "mock-a"
    model: str = "qwen2.5"

    # --- 时延模型 ---
    prefill_ms: float = 120.0
    prefill_per_kchar_ms: float = 0.0
    per_token_ms: float = 18.0
    jitter_ratio: float = 0.15
    queue_delay_ms: float = 0.0

    # --- 输出长度 ---
    min_tokens: int = 16
    max_tokens: int = 64

    # --- 故障注入 ---
    error_rate: float = 0.0
    error_status: int = 500
    fail_period_s: float = 0.0
    fail_duration_s: float = 0.0

    # --- 上报给网关的"显存水位" ---
    gpu_memory_ratio: float = 0.2

    def clamped(self) -> MockConfig:
        self.jitter_ratio = min(max(self.jitter_ratio, 0.0), 1.0)
        self.error_rate = min(max(self.error_rate, 0.0), 1.0)
        self.prefill_ms = max(self.prefill_ms, 0.0)
        self.per_token_ms = max(self.per_token_ms, 0.0)
        self.min_tokens = max(self.min_tokens, 1)
        self.max_tokens = max(self.max_tokens, self.min_tokens)
        return self


class MockRuntime:
    """运行时状态：配置 + 在途计数 + 统计。"""

    def __init__(self, config: MockConfig) -> None:
        self.config = config.clamped()
        self.started_at = time.monotonic()
        self.inflight = 0
        self.total_requests = 0
        self.failed_requests = 0

    def _jitter(self, value_ms: float) -> float:
        if self.config.jitter_ratio <= 0 or value_ms <= 0:
            return value_ms
        spread = value_ms * self.config.jitter_ratio
        return max(0.0, value_ms + random.uniform(-spread, spread))

    def prefill_delay_s(self, input_chars: int) -> float:
        base = self.config.prefill_ms + (
            input_chars / 1000.0
        ) * self.config.prefill_per_kchar_ms
        return self._jitter(base) / 1000.0

    def per_token_delay_s(self) -> float:
        return self._jitter(self.config.per_token_ms) / 1000.0

    def should_fail(self) -> bool:
        """是否注入故障。

        周期性失败优先于随机失败：它给出**可预测**的故障窗口，
        让"网关在 X 秒内把该节点剔除，Y 秒后恢复"这种演示可以复现。
        """
        cfg = self.config
        if cfg.fail_period_s > 0 and cfg.fail_duration_s > 0:
            phase = (time.monotonic() - self.started_at) % cfg.fail_period_s
            if phase < cfg.fail_duration_s:
                return True
        return random.random() < cfg.error_rate

    def output_length(self, requested: int | None) -> int:
        if requested is not None:
            return max(1, min(requested, self.config.max_tokens))
        return random.randint(self.config.min_tokens, self.config.max_tokens)


def _token_text(index: int) -> str:
    return _WORDS[index % len(_WORDS)]


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def create_app(config: MockConfig) -> FastAPI:
    runtime = MockRuntime(config)
    app = FastAPI(title=f"Mock Backend ({runtime.config.name})")
    app.state.runtime = runtime

    def _error_response() -> JSONResponse:
        runtime.failed_requests += 1
        return JSONResponse(
            status_code=runtime.config.error_status,
            content={
                "error": {
                    "message": f"mock backend {runtime.config.name} 注入的故障",
                    "type": "mock_upstream_error",
                }
            },
        )

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "name": runtime.config.name,
            "inflight": runtime.inflight,
        }

    @app.get("/v1/models")
    async def models() -> dict[str, object]:
        return {
            "object": "list",
            "data": [{"id": runtime.config.model, "object": "model"}],
        }

    @app.get("/mock/config")
    async def get_config() -> dict[str, object]:
        """网关侧的指标采集可以读这里拿"显存水位"和当前时延参数。"""
        return {
            "config": asdict(runtime.config),
            "inflight": runtime.inflight,
            "total_requests": runtime.total_requests,
            "failed_requests": runtime.failed_requests,
            "gpu_memory_ratio": runtime.config.gpu_memory_ratio,
        }

    @app.post("/mock/config")
    async def update_config(request: Request) -> dict[str, object]:
        """热更新行为参数。用来在演示中途把节点"变慢"或"变故障"。"""
        patch = await request.json()
        if not isinstance(patch, dict):
            return JSONResponse(status_code=400, content={"error": "body 必须是对象"})
        valid = {f for f in MockConfig.__dataclass_fields__}
        unknown = set(patch) - valid
        if unknown:
            return JSONResponse(
                status_code=400,
                content={"error": f"未知字段：{sorted(unknown)}", "valid": sorted(valid)},
            )
        for key, value in patch.items():
            setattr(runtime.config, key, value)
        runtime.config.clamped()
        return {"updated": sorted(patch), "config": asdict(runtime.config)}

    @app.post("/mock/reset")
    async def reset() -> dict[str, object]:
        runtime.started_at = time.monotonic()
        runtime.total_requests = 0
        runtime.failed_requests = 0
        return {"reset": True}

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        payload = await request.json()
        runtime.total_requests += 1
        runtime.inflight += 1

        input_chars = sum(
            len(str(m.get("content", ""))) for m in payload.get("messages", [])
        )
        stream = bool(payload.get("stream", False))
        length = runtime.output_length(payload.get("max_tokens"))

        async def _finish():
            runtime.inflight = max(0, runtime.inflight - 1)

        async def stream_body():
            try:
                # 排队延迟：模拟请求在实例上等待 GPU
                if runtime.config.queue_delay_ms > 0:
                    await asyncio.sleep(runtime.config.queue_delay_ms / 1000.0)

                if runtime.should_fail():
                    yield _sse(
                        {
                            "error": {
                                "message": f"mock backend {runtime.config.name} 注入的故障",
                                "type": "mock_upstream_error",
                            }
                        }
                    )
                    return

                completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
                created = int(time.time())
                model = payload.get("model", runtime.config.model)
                base = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                }

                # 首块只带 role，与时序无关；真正的 prefill 延迟在它之前
                yield _sse(
                    {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]}
                )

                # ---- prefill：这一段耗时就是 TTFT 的主要来源 ----
                await asyncio.sleep(runtime.prefill_delay_s(input_chars))

                # ---- decode：每 token 一个 chunk，节奏由 per_token_ms 决定 ----
                per_token = runtime.per_token_delay_s()
                for i in range(length):
                    yield _sse(
                        {
                            **base,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": _token_text(i)},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                    if i < length - 1:
                        await asyncio.sleep(per_token)

                yield _sse(
                    {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                )
                yield "data: [DONE]\n\n"
            finally:
                # 客户端中途断开（压测脚本强杀、网关取消请求）也会走到这里
                await _finish()

        if stream:
            return StreamingResponse(
                stream_body(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        # ---- 非流式：等完整内容再一次性返回 ----
        try:
            if runtime.config.queue_delay_ms > 0:
                await asyncio.sleep(runtime.config.queue_delay_ms / 1000.0)
            if runtime.should_fail():
                return _error_response()

            await asyncio.sleep(runtime.prefill_delay_s(input_chars))
            await asyncio.sleep(length * runtime.per_token_delay_s())

            text = "".join(_token_text(i) for i in range(length))
            return {
                "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": payload.get("model", runtime.config.model),
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": max(1, input_chars // 4),
                    "completion_tokens": length,
                    "total_tokens": max(1, input_chars // 4) + length,
                },
            }
        finally:
            await _finish()

    return app


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SmartMaaS Mock 模型服务")
    parser.add_argument("--name", default="mock-a", help="实例名，用于日志")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9001)
    parser.add_argument("--model", default="qwen2.5", help="对外声明的逻辑模型名")
    parser.add_argument("--prefill-ms", type=float, default=120.0)
    parser.add_argument("--prefill-per-kchar-ms", type=float, default=0.0)
    parser.add_argument("--per-token-ms", type=float, default=18.0)
    parser.add_argument("--jitter-ratio", type=float, default=0.15)
    parser.add_argument("--queue-delay-ms", type=float, default=0.0)
    parser.add_argument("--error-rate", type=float, default=0.0)
    parser.add_argument("--error-status", type=int, default=500)
    parser.add_argument("--fail-period-s", type=float, default=0.0)
    parser.add_argument("--fail-duration-s", type=float, default=0.0)
    parser.add_argument("--gpu-memory-ratio", type=float, default=0.2)
    parser.add_argument("--min-tokens", type=int, default=16)
    parser.add_argument("--max-tokens", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    config = MockConfig(
        name=args.name,
        model=args.model,
        prefill_ms=args.prefill_ms,
        prefill_per_kchar_ms=args.prefill_per_kchar_ms,
        per_token_ms=args.per_token_ms,
        jitter_ratio=args.jitter_ratio,
        queue_delay_ms=args.queue_delay_ms,
        error_rate=args.error_rate,
        error_status=args.error_status,
        fail_period_s=args.fail_period_s,
        fail_duration_s=args.fail_duration_s,
        gpu_memory_ratio=args.gpu_memory_ratio,
        min_tokens=args.min_tokens,
        max_tokens=args.max_tokens,
    ).clamped()
    uvicorn.run(create_app(config), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
