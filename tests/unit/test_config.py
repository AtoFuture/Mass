"""配置解析测试（§27 DoD 要求每个功能有正常 + 异常测试）。"""

from __future__ import annotations

import pytest

from app.core.config import BackendConfig, parse_settings


def test_empty_config_yields_defaults():
    """空配置必须能解析出一套可用默认值（§27 DoD 第 6 条）。"""
    settings = parse_settings({})
    assert settings.server.port == 8000
    assert settings.routing.strategy == "round_robin"
    assert settings.cache.l1.max_items == 1000
    assert settings.backends == []


def test_full_config_is_parsed():
    settings = parse_settings(
        {
            "server": {"port": 9000, "max_concurrency": 42},
            "routing": {
                "strategy": "dynamic",
                "weights": {"concurrency": 0.5, "prefix_affinity": 0.4},
            },
            "cache": {
                "l1": {"max_items": 10},
                "redis": {"url": "redis://example:6379/1"},
                "semantic": {"enabled": True, "threshold": 0.88},
            },
            "backends": [
                {"id": "a", "model": "qwen2.5", "base_url": "http://a:8000"},
                {"id": "b", "model": "qwen2.5", "base_url": "http://b:8000", "weight": 3},
            ],
        }
    )
    assert settings.server.port == 9000
    assert settings.server.max_concurrency == 42
    assert settings.routing.strategy == "dynamic"
    assert settings.routing.weights.concurrency == 0.5
    assert settings.routing.weights.prefix_affinity == 0.4
    # 未指定的权重项保留默认值，而不是被清零
    assert settings.routing.weights.latency == 0.30
    assert settings.cache.l1.max_items == 10
    assert settings.cache.redis.url == "redis://example:6379/1"
    assert settings.cache.semantic.enabled is True
    assert settings.cache.semantic.threshold == 0.88
    assert len(settings.backends) == 2
    assert settings.backends[1].weight == 3
    # 未指定的后端字段落回默认值
    assert settings.backends[0].timeout_s == 120.0
    assert settings.backends[0].max_concurrency == 16


def test_unknown_keys_are_ignored(caplog):
    """YAML 里多写的键只警告不报错，避免手滑打不开服务。"""
    settings = parse_settings({"server": {"port": 8000, "typo_field": 1}})
    assert settings.server.port == 8000


def test_backends_must_be_a_list():
    with pytest.raises(ValueError, match="backends"):
        parse_settings({"backends": {"id": "a"}})


def test_malformed_section_is_rejected():
    with pytest.raises(ValueError, match="server"):
        parse_settings({"server": "not-a-mapping"})


def test_backend_config_is_immutable_dataclass():
    """BackendConfig 是纯数据，没有隐藏的运行时状态。"""
    cfg = BackendConfig(id="a", model="m", base_url="http://a:8000")
    assert cfg.weight == 1
    assert not hasattr(cfg, "active_requests")
