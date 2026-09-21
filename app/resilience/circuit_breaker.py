"""熔断器（§6 P1-21、P0-19）。

【待实现 —— 负责人：A（骨架） / B（策略）—— 两人需先对齐状态机】

状态机：

    CLOSED ──连续失败达阈值──▶ OPEN
      ▲                         │
      │                    冷却期结束
      │                         ▼
      └──探测成功──────── HALF_OPEN
                                │
                            探测失败
                                ▼
                              OPEN

触发依据可组合：连续失败数（`config.routing.circuit_breaker_failures`，
默认 5）、错误率、P99 延迟（§6 P1-21）。

与其他模块的边界：
- 熔断器本身**只回答"这个实例现在能不能用"**；
- "连续失败计数"由 `Backend.consecutive_failures` 维护（已实现）；
- 评分惩罚（§6 P0-19 的"增加调度惩罚"）由动态调度器读取本模块状态后体现，
  熔断器不直接改分数。

【与正式评分的关系】§6 P0-19 原文指出，这项功能"与正式评分中的
Mock 仿真要求直接相关"—— 初赛"仿真测试方案"10 分要求"验证网关的
超时熔断或慢节点剔除逻辑是否生效"。所以这个模块的**测试**比实现更重要，
必须留下可复现的演示脚本和日志证据。
"""

from __future__ import annotations

import time
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """单个后端实例的熔断器。每个 `Backend` 一个实例。"""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_s: float = 30.0,
        half_open_probes: int = 1,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_s = cooldown_s
        self.half_open_probes = half_open_probes
        self.state = CircuitState.CLOSED
        self.opened_at: float | None = None

    def allow_request(self) -> bool:
        """这个实例现在能否接请求。接入层在选完节点后、发请求前调用。"""
        raise NotImplementedError("P1-21 熔断器：待实现")

    def record_success(self) -> None:
        raise NotImplementedError("P1-21 熔断器：待实现")

    def record_failure(self) -> None:
        raise NotImplementedError("P1-21 熔断器：待实现")

    def _cooldown_elapsed(self) -> bool:
        if self.opened_at is None:
            return True
        return (time.monotonic() - self.opened_at) >= self.cooldown_s
