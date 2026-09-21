"""语义缓存（§7 P1-26）。

【待实现 —— 负责人：B，优先级 P1】

流程：
1. 对用户输入生成 Embedding
2. 检索候选历史问题
3. 计算余弦相似度
4. 超过阈值（`config.cache.semantic.threshold`，默认 0.92）才返回缓存
5. 记录语义命中与**误命中**测试

必须硬编码的"不可缓存"场景（§7 P1-26 原文）：
- 涉及实时数据
- 调用工具 / 联网
- 用户私有上下文
- 随机性要求高（temperature 偏高）
- 跨权限 / 跨租户

这些判断应该在**生成 CacheContext 时**完成（把 `cacheable` 置 False），
而不是在本模块里再判断一次 —— 因为 L1/L2 同样不该缓存这些请求。

【重要】优先级是 P1 不是 P0。§22 已把"语义缓存误命中"列入风险清单，
§10 的对照实验中语义缓存也不是必需项。**先把 P0 做完再碰这个**，
一个会返回错误答案的语义缓存会拉低整体评分，而不是加分。
"""

from __future__ import annotations

from app.cache.base import CachedResponse, CacheLayer
from app.core.context import CacheContext


class SemanticCache(CacheLayer):
    layer_name = "semantic"

    def __init__(self, threshold: float = 0.92) -> None:
        self.threshold = threshold
        self.hits = 0
        self.misses = 0

    async def embed(self, text: str) -> list[float]:
        """生成文本向量。

        初赛建议先用轻量本地方案（例如 `sentence-transformers` 的小模型），
        不要为了这一步去调外部 Embedding API —— 那会给网关引入一个外部依赖，
        压测时它自己就成了瓶颈，实验数据会失真。
        """
        raise NotImplementedError("P1-26 语义缓存：待 B 实现")

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """余弦相似度。纯函数，可以脱离缓存单独测试。"""
        raise NotImplementedError("P1-26 语义缓存：待 B 实现")

    async def get(self, cache_ctx: CacheContext) -> CachedResponse | None:
        raise NotImplementedError("P1-26 语义缓存：待 B 实现")

    async def set(
        self, cache_ctx: CacheContext, response: CachedResponse, ttl_s: int
    ) -> None:
        raise NotImplementedError("P1-26 语义缓存：待 B 实现")

    async def invalidate(self, key: str) -> None:
        raise NotImplementedError("P1-26 语义缓存：待 B 实现")
