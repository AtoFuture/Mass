"""缓存抽象基类（§15 Cache 接口）。

三层缓存共用一套接口，接入层只跟 `MultiLevelCache` 打交道，
不直接触碰 L1/L2/语义层的内部结构。

契约：
- `get()` 返回 `None` 表示未命中，**不抛异常**；
- 任何一层故障（Redis 挂了、Embedding 服务超时）必须降级为"未命中"，
  绝不能让缓存故障变成网关故障（§7 P0-25、§22 创新点 C）；
- `set()` 只在 `cache_ctx.cacheable` 为真时被调用，实现里不必重复判断，
  但应断言以防误用。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.context import CacheContext


@dataclass(slots=True)
class CachedResponse:
    """缓存里存的一条响应。

    流式请求缓存的是**完整文本**而非 token 流：命中后由接入层按
    §3 P0-03 的 SSE 格式重新分块发出，这样流式和非流式可以共享同一条缓存。
    """

    content: str
    model: str
    created_at: float = field(default_factory=time.time)
    finish_reason: str = "stop"
    backend_id: str = ""
    usage: dict[str, Any] = field(default_factory=dict)

    def to_openai_payload(self, request_id: str) -> dict[str, Any]:
        """还原成 OpenAI 兼容的非流式响应体。"""
        return {
            "id": request_id,
            "object": "chat.completion",
            "created": int(self.created_at),
            "model": self.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": self.content},
                    "finish_reason": self.finish_reason,
                }
            ],
            "usage": self.usage,
        }


class CacheLayer(ABC):
    """单层缓存。L1 / L2 / 语义层都实现这个接口。"""

    #: 用于日志和统计的层名，例如 "l1" / "l2" / "semantic"
    layer_name: str = "base"

    @abstractmethod
    async def get(self, cache_ctx: CacheContext) -> CachedResponse | None:
        """查缓存。未命中或本层故障都返回 None。"""

    @abstractmethod
    async def set(
        self, cache_ctx: CacheContext, response: CachedResponse, ttl_s: int
    ) -> None:
        """写缓存。写失败只记日志，不向上抛。"""

    @abstractmethod
    async def invalidate(self, key: str) -> None:
        """失效单个 Key（§7 P0-29）。"""

    async def clear(self) -> None:
        """清空本层（§7 P0-29 管理员主动清缓存）。默认不实现。"""
        raise NotImplementedError(f"{self.layer_name} 层未实现 clear()")
