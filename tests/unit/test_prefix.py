"""Prefix 哈希与亲和测试（§5 P1-16、§7 P1-27）—— 创新点 B 的基础。"""

from __future__ import annotations

from app.backend.model import Backend
from app.cache.prefix import MIN_PREFIX_CHARS, affinity_bonus, compute_prefix_hash
from app.core.config import BackendConfig
from app.core.context import Message, RequestContext


def _ctx(system_prompt: str, user: str = "问题") -> RequestContext:
    messages = []
    if system_prompt:
        messages.append(Message(role="system", content=system_prompt))
    messages.append(Message(role="user", content=user))
    return RequestContext(model="qwen2.5", messages=messages)


LONG_PROMPT = "你是一个专业的技术助手。" * 20


def test_short_system_prompt_gets_no_hash():
    """短 system prompt 区分度低，做前缀亲和没有收益，应返回空串。"""
    assert compute_prefix_hash(_ctx("You are helpful.")) == ""
    assert len("You are helpful.") < MIN_PREFIX_CHARS


def test_long_system_prompt_hashes_stably():
    """同一前缀必须得到同一个 hash —— 否则亲和路由完全失效。"""
    a = compute_prefix_hash(_ctx(LONG_PROMPT, user="问题一"))
    b = compute_prefix_hash(_ctx(LONG_PROMPT, user="完全不同的问题二"))
    assert a == b != ""


def test_different_prompts_hash_differently():
    other = "你是一个法律顾问。" * 20
    assert compute_prefix_hash(_ctx(LONG_PROMPT)) != compute_prefix_hash(_ctx(other))


def test_hash_ignores_user_message():
    """前缀哈希只看 system prompt，不应被用户问题污染。"""
    base = compute_prefix_hash(_ctx(LONG_PROMPT, user="aaa"))
    assert compute_prefix_hash(_ctx(LONG_PROMPT, user="bbb")) == base


def test_no_system_prompt_gets_no_hash():
    assert compute_prefix_hash(_ctx("")) == ""


def test_affinity_decays_over_time():
    """刚处理过该前缀的实例亲和分接近 1，未处理过的是 0。"""
    backend = Backend(
        BackendConfig(id="a", model="qwen2.5", base_url="http://a:8000")
    )
    assert affinity_bonus(backend, "deadbeef") == 0.0

    backend.record_prefix("deadbeef")
    assert affinity_bonus(backend, "deadbeef") > 0.9

    # 另一个前缀不受影响
    assert affinity_bonus(backend, "cafebabe") == 0.0


def test_empty_prefix_has_no_affinity():
    backend = Backend(
        BackendConfig(id="a", model="qwen2.5", base_url="http://a:8000")
    )
    assert affinity_bonus(backend, "") == 0.0


def test_affinity_table_is_bounded():
    """亲和表必须有容量上限，否则长跑会内存泄漏。"""
    backend = Backend(
        BackendConfig(id="a", model="qwen2.5", base_url="http://a:8000")
    )
    for i in range(Backend.MAX_PREFIX_ENTRIES + 200):
        backend.record_prefix(f"prefix-{i}")

    assert len(backend._prefix_affinity) <= Backend.MAX_PREFIX_ENTRIES
    # 最近写入的还在
    assert affinity_bonus(backend, f"prefix-{Backend.MAX_PREFIX_ENTRIES + 199}") > 0
