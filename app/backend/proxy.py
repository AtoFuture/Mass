"""转发到后端模型实例（§3 P0-01/02/03）—— A 的核心工作。

【待实现 —— 负责人：A】

三个方法对应三条 P0：

- `forward()`        → P0-02 非流式：收完整响应后返回，保留 OpenAI 兼容字段，
                       正确映射后端异常状态码
- `forward_stream()` → P0-03 SSE 流式：`data: {...}\\n\\n` 透传，以
                       `data: [DONE]\\n\\n` 结束
- 两者共用的连接/超时配置来自 `Backend.config.timeout_s`

必须在实现时处理好的几件事：

1. **客户端断开**（§3 P0-03）：客户端关掉连接后要立刻取消对后端的请求，
   并释放 `Backend.active_requests`。用 `try/finally` 包住，
   不要依赖 FastAPI 帮你回收 —— 流式响应中途断开不会抛到你的 handler 里。

2. **响应头**：转发时只透传必要的头，**不要**把客户端的 `Authorization`
   原样转给后端（那是给网关的 Token，不是给模型的），
   后端鉴权用 `Backend` 自己的凭据（从环境变量读，不进 YAML）。

3. **TTFT/TPOT 采集**（§8 P0-32）：TTFT = 从发出请求到收到**第一个** token
   的时间；TPOT = 首 token 之后平均每 token 耗时。流式路径里才能测到，
   必须在这里埋点并调用 `metrics.record_request(ttft_ms=..., tpot_ms=...)`。
   决赛 30 分的"效果验证"就是 P99 TTFT + TPOT，这两个数字不能靠估算。

4. **安全重试**（§6 P1-22）：只在"后端尚未向客户端输出任何内容"时才允许
   重试或换节点；一旦已经开始输出，重试会造成重复内容。判断依据是
   "是否已经写出过第一个 chunk"。

5. **错误分类**：超时、连接失败、后端 5xx、后端 4xx 要分开记，
   因为 §6 P0-19 的慢节点惩罚和 §6 P1-21 的熔断依据不同 ——
   后端返回 400（用户参数问题）不该算作节点故障。
"""

from __future__ import annotations

import httpx

from app.backend.model import Backend
from app.core.context import RequestContext


class UpstreamError(RuntimeError):
    """后端调用失败。携带足够的分类信息供熔断/惩罚逻辑使用。"""

    def __init__(
        self, backend_id: str, error_type: str, status_code: int | None = None
    ) -> None:
        super().__init__(f"后端 {backend_id} 调用失败：{error_type}")
        self.backend_id = backend_id
        self.error_type = error_type
        self.status_code = status_code


class Proxy:
    """把请求转发到选定的后端实例。"""

    def __init__(self, timeout_s: float = 120.0) -> None:
        self.timeout_s = timeout_s
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        """建连接池。应用启动时调用一次。

        复用 `AsyncClient` 很重要：每个请求新建 client 会重新做 TCP 握手，
        网关自身的开销会掩盖掉优化带来的收益，压测数据就不可信了。
        """
        raise NotImplementedError("P0-01 转发：待 A 实现")

    async def close(self) -> None:
        raise NotImplementedError("P0-01 转发：待 A 实现")

    async def forward(
        self, backend: Backend, request_ctx: RequestContext
    ) -> tuple[dict[str, object], float]:
        """非流式转发（P0-02）。

        Returns:
            (OpenAI 兼容响应体, 耗时毫秒)
        """
        raise NotImplementedError("P0-02 非流式转发：待 A 实现")

    async def forward_stream(self, backend: Backend, request_ctx: RequestContext):
        """流式转发（P0-03）。逐步 yield SSE 行。

        调用方负责在生成器结束或异常时释放 `Backend.active_requests`。
        """
        raise NotImplementedError("P0-03 SSE 流式转发：待 A 实现")
        yield  # pragma: no cover — 让它成为异步生成器
