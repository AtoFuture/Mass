"""Locust 压测脚本（§10）—— 负责人：C。

设计成一套脚本跑完 §10.2 的五组对照实验，只靠环境变量切换：

    # A. Baseline：直连后端（不经网关）
    locust -f benchmark/locustfile.py --host http://localhost:9001 \
           --headless -u 20 -r 5 -t 60s --csv results/A-baseline

    # B. Basic Gateway：只代理，关路由和缓存
    #    （需要在网关侧把 routing.strategy 设为 round_robin、cache.enabled 设为 false）
    locust -f benchmark/locustfile.py --host http://localhost:8000 ...

    # C/D/E 同理，只改网关配置，压测参数保持一致

环境变量（控制变量用，§10.3）：

    SMARTMAAS_REPEAT_RATIO   重复请求占比，默认 0.5
                             （决赛口径就是 50% 重复 + 50% 随机新请求）
    SMARTMAAS_CONTEXT_CHARS  附加在 system prompt 里的填充长度，默认 0
                             （调大即为长上下文场景，用于 §5 P1-15）
    SMARTMAAS_STREAM         1 = 用流式请求（能测 TTFT），0 = 非流式，默认 1
    SMARTMAAS_MAX_TOKENS     每次请求的最大输出 token 数，默认 64

【关键】三组对比实验之间，上面这些变量和 -u/-r/-t 必须完全一致，
否则数据不可比（§10.3 的控制变量要求）。建议把每组实验的命令写进
`benchmark/run_experiments.sh`，不要手敲 —— 手敲迟早会漏一个参数。

实测完记得保存原始 CSV（§10.5：原始数据保存 CSV/JSON，不只保存截图）。
"""

from __future__ import annotations

import json
import os
import random
import time

from locust import HttpUser, between, task

REPEAT_RATIO = float(os.getenv("SMARTMAAS_REPEAT_RATIO", "0.5"))
CONTEXT_CHARS = int(os.getenv("SMARTMAAS_CONTEXT_CHARS", "0"))
STREAM = os.getenv("SMARTMAAS_STREAM", "1") == "1"
MAX_TOKENS = int(os.getenv("SMARTMAAS_MAX_TOKENS", "64"))
MODEL = os.getenv("SMARTMAAS_MODEL", "qwen2.5")

#: 固定问题集 —— 用来制造"重复请求"，保证同一组实验里重复的那部分
#: 每次都是同样的字符串，缓存才有机会命中。
REPEAT_PROMPTS = [
    "解释一下什么是负载均衡，以及它和反向代理的区别。",
    "什么是 KV Cache？它为什么能加速大模型推理？",
    "Prefix Caching 的原理是什么？在什么场景下收益最大？",
    "解释首字延迟 TTFT 和每 token 输出时间 TPOT 的区别。",
    "熔断器模式有哪几种状态？状态之间如何迁移？",
    "LRU 和 LFU 缓存淘汰策略各适合什么场景？",
    "为什么说轮询调度不适合大模型推理服务？",
    "Redis 作为二级缓存时，如何保证网关不因为它挂了而整体不可用？",
]

#: 用于生成"随机新请求"的词表。每个新请求都由随机词拼成，
#: 保证互不重复，从而不会命中缓存。
_NOUNS = [
    "缓存", "路由", "调度", "显存", "并发", "吞吐", "延迟",
    "副本", "队列", "熔断", "降级", "预热", "分片", "共识",
]
_VERBS = ["优化", "降低", "提升", "拆解", "对比", "论证", "模拟", "压测", "观测", "复现"]


class ChatUser(HttpUser):
    """模拟一个调用网关的 AI 应用客户端。"""

    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.filler = "以下是与本问题相关的背景资料。" * (CONTEXT_CHARS // 15) if CONTEXT_CHARS else ""

    def _build_payload(self, prompt: str) -> dict:
        messages = []
        system = f"你是一个专业的技术助手。{self.filler}"
        messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": MODEL,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "temperature": 0.7,
            "stream": STREAM,
        }

    def _new_prompt(self) -> str:
        """拼一个几乎不可能重复出现的问题。"""
        return f"请{random.choice(_VERBS)}{random.choice(_NOUNS)}与{random.choice(_NOUNS)}的关系？#{random.random():.12f}"

    def _prompt(self) -> str:
        return (
            random.choice(REPEAT_PROMPTS)
            if random.random() < REPEAT_RATIO
            else self._new_prompt()
        )

    @task
    def chat(self) -> None:
        payload = self._build_payload(self._prompt())

        if not STREAM:
            with self.client.post(
                "/v1/chat/completions",
                json=payload,
                name="/v1/chat/completions (non-stream)",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                else:
                    response.success()
            return

        # --- 流式：手工计时，才能拿到 TTFT 和 TPOT ---
        start = time.perf_counter()
        first_token_at: float | None = None
        token_count = 0

        try:
            with self.client.post(
                "/v1/chat/completions",
                json=payload,
                stream=True,
                name="/v1/chat/completions (stream)",
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    return

                for raw in response.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        token_count += 1
                        if first_token_at is None:
                            first_token_at = time.perf_counter()

                if first_token_at is None:
                    response.failure("没有收到任何 token")
                    return

                ttft_ms = (first_token_at - start) * 1000
                total_ms = (time.perf_counter() - start) * 1000
                tpot_ms = (total_ms - ttft_ms) / max(1, token_count - 1)

                # 作为独立事件上报，这样 Locust 的统计表里能直接看到 TTFT / TPOT 的
                # 分位数。决赛评分看的就是 **P99 TTFT** 和 **TPOT**。
                self.environment.events.request.fire(
                    request_type="TTFT",
                    name="ttft",
                    response_time=ttft_ms,
                    response_length=0,
                    exception=None,
                    context={},
                )
                self.environment.events.request.fire(
                    request_type="TPOT",
                    name="tpot",
                    response_time=tpot_ms,
                    response_length=0,
                    exception=None,
                    context={},
                )
                response.success()
        except Exception as exc:  # noqa: BLE001 — 压测脚本要把失败记进统计，不能崩
            self.environment.events.request.fire(
                request_type="EXC",
                name="/v1/chat/completions (stream)",
                response_time=(time.perf_counter() - start) * 1000,
                response_length=0,
                exception=exc,
                context={},
            )
