"""Prefix 处理（§7 P1-27、§5 P1-16）—— 本项目的核心创新点 B。

分两件事，难度差别很大：

**1. 应用层 prefix_hash**（本文件已提供可运行实现）
   对 System Prompt / 公共长前缀做稳定哈希。这是纯函数，
   调度器和缓存 Key 都要用，所以脚手架先给出实现。

**2. Prefix-aware Routing**（【待实现 —— 负责人：B】）
   记录"这个前缀最近由哪个实例处理"，在负载差距可接受时优先发回该实例，
   让 vLLM 的 Prefix Cache 有机会命中。见 `affinity_bonus()`。

   §5 P1-16 的关键约束是"**在负载差距可接受时**"——
   不能为了前缀亲和把请求全压到一个实例上。建议做法：
   只在动态评分里作为 `-η·H_i` 一项参与，让 η 控制它的影响力，
   而不是写成"前缀匹配就强制路由"的硬规则。这也是创新点 A 和 B
   能合成一个评分模型、而不是两套互相打架的逻辑的原因。
"""

from __future__ import annotations

import hashlib

from app.backend.model import Backend
from app.core.context import RequestContext

#: 参与 prefix_hash 的最短前缀长度（字符）。
#: 太短的 system prompt（如 "You are helpful."）区分度低，
#: 让它们互相亲和没有收益，反而干扰调度。
MIN_PREFIX_CHARS = 64


def compute_prefix_hash(request_ctx: RequestContext, min_chars: int = MIN_PREFIX_CHARS) -> str:
    """对请求的公共前缀做稳定哈希。

    只取 system prompt：它是同一应用的所有请求里最可能重复的长前缀，
    也是 vLLM Prefix Caching 最容易复用的部分。

    返回空字符串表示"不值得做前缀亲和"，调用方应据此关闭 H_i 项。
    """
    prefix = request_ctx.system_prompt
    if len(prefix) < min_chars:
        return ""
    return hashlib.sha256(prefix.encode("utf-8")).hexdigest()[:16]


def affinity_bonus(backend: Backend, prefix_hash: str) -> float:
    """前缀亲和奖励 H_i，取值 0~1，越大表示越该把请求发回该实例。

    【待实现 —— 负责人：B】当前委托给 `Backend.prefix_affinity()`，
    它已经实现了"按时间衰减"的部分。如果要加更细的策略
    （例如命中次数加权、按前缀长度加权），在这一层扩展，
    不要去改 `Backend` 内部结构。
    """
    return backend.prefix_affinity(prefix_hash)
