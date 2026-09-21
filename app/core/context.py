"""跨模块共享的请求上下文（§15 模块间接口协议）。

`Scheduler.select()` 收 `request_ctx`，`Cache.get()/set()` 收 `cache_ctx`，
两者的字段都在这里定义，避免模块之间互相 import 内部实现。

【对 §17 目录协议的偏离，需团队确认】
§17 的目录树里没有 `core/context.py`。但 `request_id` / `prefix_hash` /
`tenant_scope` 这类字段同时被接入层、调度器、缓存和日志四条链路使用，
无论放进其中哪一个模块，都会让另外三个反向依赖它。因此单独立一个文件。
如果团队不接受，替代方案是把 RequestContext 放进 `backend/model.py`，
但那样 `cache/` 就要 import `backend/`。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class Message:
    """OpenAI 兼容的单条消息。"""

    role: Role
    content: str


@dataclass(slots=True)
class RequestContext:
    """一次用户推理请求的完整上下文，贯穿接入→调度→缓存→后端→日志。"""

    model: str
    messages: list[Message]
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int | None = None
    stream: bool = False
    tenant: str = "default"

    # 以下字段由接入层填充，下游只读
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    arrived_at: float = field(default_factory=time.monotonic)

    @property
    def system_prompt(self) -> str:
        """拼接所有 system 消息，用于 prefix_hash 和缓存 Key（§7 P0-28）。"""
        return "\n".join(m.content for m in self.messages if m.role == "system")

    @property
    def user_message(self) -> str:
        """最后一条 user 消息，仅用于语义缓存检索，**不得**单独作为缓存 Key。"""
        for m in reversed(self.messages):
            if m.role == "user":
                return m.content
        return ""

    @property
    def conversation_history(self) -> str:
        """除最后一条 user 外的前序对话，参与缓存 Key 计算。"""
        parts: list[str] = []
        for m in self.messages:
            if m.role == "system":
                continue
            parts.append(f"{m.role}:{m.content}")
        return "\n".join(parts[:-1]) if parts else ""

    @property
    def input_tokens_estimate(self) -> int:
        """粗略估算输入长度，供 §5 P1-15 上下文长度感知调度使用。

        这里的 4 字符/token 只是占位经验值。真实实现应使用后端 tokenizer，
        或改用字符数本身作为排序特征（只要单调即可用于比较），
        不要在报告里把这个数字当作精确 token 数。
        """
        total_chars = sum(len(m.content) for m in self.messages)
        return max(1, total_chars // 4)

    def generation_params(self) -> dict[str, Any]:
        """影响输出的生成参数，必须参与缓存 Key（§7 P0-28、P0-29）。"""
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }


@dataclass(slots=True)
class CacheContext:
    """缓存查询上下文。

    `cacheable=False` 的请求必须直接穿透到后端，不允许写入任何一级缓存
    （§7 P1-26 的"不可缓存场景"）。
    """

    key: str
    request: RequestContext
    cacheable: bool = True
    uncacheable_reason: str = ""

    # 由 prefix 模块填充（§7 P1-27）
    prefix_hash: str = ""

    # 由各缓存层填充，用于日志与统计
    hit_layer: str = ""
