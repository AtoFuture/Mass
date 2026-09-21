"""动态评分调度（§5 P0-14）—— 本项目的核心创新点 A。

【待实现 —— 负责人：B】

评分模型（原文公式）：

    Score_i = α·C_i + β·L_i + γ·G_i + δ·E_i − η·H_i

    C_i  归一化当前并发        = active_requests / max_concurrency
    L_i  归一化历史延迟        = avg_latency_ms / 候选集中的最大平均延迟
    G_i  GPU 显存压力          = gpu_memory_ratio（采集不到时如何补，见下）
    E_i  近期错误/超时惩罚     = error_rate
    H_i  Prefix 亲和奖励       = backend.prefix_affinity(prefix_hash)
    分数越低越优先

权重初值见 `config.yaml` 的 `routing.weights`（α=0.35, β=0.30, γ=0.20,
δ=0.10, η=0.25）。

必须在实现时处理好的边界情况：
1. **冷启动**：`avg_latency_ms` 为 None（窗口内无样本）。不能当成 0，
   否则新实例会被无限偏爱；建议用一个全局先验延迟填充。
2. **归一化基准**：L_i 的分母取候选集的 max，当所有实例延迟相同时
   全部为 0 或 1，评分退化成只由 C_i 决定 —— 这是可接受的，但要能解释。
3. **`gpu_memory_ratio` 缺失**：Mock 阶段拿不到，应整项按 0 处理并保证
   γ 不参与排序，而不是让 None 参与算术。

【报告要求】§5 原文明确：权重最终必须用实验数据调整，
不得把拍脑袋的初值描述成"最优"。建议做一个权重敏感性分析
（例如固定请求集，扫描 α 和 η 的组合，画热力图）作为 §11.1 创新点分析的支撑。
"""

from __future__ import annotations

from app.backend.model import Backend
from app.core.context import RequestContext
from app.router.base import NoAvailableBackendError, Scheduler


class DynamicScheduler(Scheduler):
    name = "dynamic"

    def __init__(self, weights: object | None = None) -> None:
        #: 由 `core/config.py` 的 `RoutingWeights` 注入
        self.weights = weights

    async def select(
        self, request_ctx: RequestContext, backends: list[Backend]
    ) -> Backend:
        if not backends:
            raise NoAvailableBackendError(request_ctx.model)
        raise NotImplementedError("P0-14 动态评分调度：待 B 实现")
