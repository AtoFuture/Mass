"""用户推理接口（§3 API 接入层、§14.1）。

【待实现 —— 负责人：A】

`POST /v1/chat/completions` 的完整链路：

    校验模型名 → 生成 RequestContext → 算 prefix_hash → 查多级缓存
      → 命中则直接返回（流式也要按 SSE 重放）
      → 未命中则调 scheduler.select() → proxy.forward() → 写缓存 → 返回

§3 P0-01 的验收标准：**客户端只需要把原来的 `base_url` 改成网关地址就能用**。
所以下面的 Pydantic 模型开了 `extra="allow"`，客户端传 `frequency_penalty`、
`stop`、`seed` 这类本网关不处理的字段时不会 422。这些字段要不要透传给后端，
由 A 决定（建议透传，兼容性更好）。
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.context import Message, RequestContext

router = APIRouter(tags=["chat"])


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


class ChatCompletionRequest(BaseModel):
    """OpenAI 兼容的聊天请求（§14.1）。"""

    # 允许未知字段，保证"改 base_url 就能用"的 drop-in 兼容性
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[ChatMessage] = Field(min_length=1)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, gt=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=1)
    stream: bool = False

    def to_context(self, tenant: str = "default") -> RequestContext:
        return RequestContext(
            model=self.model,
            messages=[Message(role=m.role, content=m.content) for m in self.messages],
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            stream=self.stream,
            tenant=tenant,
        )


@router.post("/v1/chat/completions")
async def chat_completions(
    payload: ChatCompletionRequest, request: Request
) -> dict[str, Any]:
    """§3 P0-01 / P0-02 / P0-03 的统一入口。

    实现时注意：
    - 非法模型名要返回 400 而不是 500（§3 P0-04）；
    - 无可用后端返回 503；
    - 并发超限返回 429（§6 P0-20）；
    - 客户端断开时要释放并发计数（§3 P0-03）。
    """
    registry = request.app.state.registry
    if payload.model not in registry.known_models():
        raise HTTPException(
            status_code=400,
            detail=f"未知模型 {payload.model!r}，可用：{sorted(registry.known_models())}",
        )
    raise HTTPException(
        status_code=501,
        detail="P0-01 聊天接口尚未实现（负责人：A）",
    )
