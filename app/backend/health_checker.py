"""后端健康检查（§4 P0-10）。

【待实现 —— 负责人：A】

行为要求：
- 后台任务，周期 `config.routing.health_check_interval_s`（默认 3 秒）
- 正常 → `BackendState.HEALTHY`
- 连续失败 → `BackendState.UNHEALTHY`
- 恢复 → 重新加入候选集合（`Backend.record_health_check(ok=True)` 已实现这个跃迁）

实现提示：
- 探针打到后端的 OpenAI 兼容端点即可（vLLM 有 `/health`，Mock 服务也有）。
  探针要**轻**：不要真的跑一次推理，那会把健康检查变成负载。
- 用 `asyncio.TaskGroup` 或 `gather` 并发探所有实例，别串行 ——
  3 个实例串行探测，每个超时 2 秒，最坏情况 6 秒才轮到第一个实例更新状态。
- 任务必须在应用关闭时被取消并 `await`，否则 uvicorn 会报
  "Task was destroyed but it is pending"。

注意与 §6 P0-19 的分工：健康检查管**通断**，慢节点惩罚和熔断管**性能劣化**。
一个实例可能 HTTP 探针正常但推理已经慢到不可用，那种情况归熔断器管，
不要在健康检查里加延迟阈值判断 —— 两套机制的判据混在一起会很难调。
"""

from __future__ import annotations

import asyncio

from app.backend.registry import BackendRegistry


class HealthChecker:
    """周期性探测所有已注册后端。"""

    def __init__(self, registry: BackendRegistry, interval_s: float = 3.0) -> None:
        self.registry = registry
        self.interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """启动后台探测任务。应用启动时调用。"""
        raise NotImplementedError("P0-10 健康检查：待 A 实现")

    async def stop(self) -> None:
        """取消后台任务并等待其真正结束。"""
        raise NotImplementedError("P0-10 健康检查：待 A 实现")

    async def probe_once(self) -> None:
        """跑一轮探测。单独暴露出来是为了让测试能直接调它，不必等定时器。"""
        raise NotImplementedError("P0-10 健康检查：待 A 实现")
