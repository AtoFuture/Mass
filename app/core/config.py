"""配置加载（§16 配置协议）。

两条硬规则：
1. **密钥不落盘**：YAML 里只写环境变量名（如 `admin_token_env: SMARTMAAS_ADMIN_TOKEN`），
   真实 Token 从环境读取，永远不写进配置文件（§13.3、§18）。
2. **每一项都有默认值**：`load_settings()` 在找不到配置文件时返回一套可用默认值，
   保证新克隆的仓库能直接起服务（§27 DoD 第 6 条）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/config.yaml")
EXAMPLE_CONFIG_PATH = Path("config/config.example.yaml")


@dataclass(slots=True)
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8000
    max_concurrency: int = 100


@dataclass(slots=True)
class RoutingWeights:
    """§5 P0-14 动态评分权重。

    注意 §5 原文的告诫：这些是初值，最终必须用实验数据调，
    报告中不得把拍脑袋的权重描述成"最优"。
    """

    concurrency: float = 0.35
    latency: float = 0.30
    gpu_memory: float = 0.20
    error: float = 0.10
    prefix_affinity: float = 0.25


@dataclass(slots=True)
class RoutingConfig:
    strategy: str = "round_robin"
    health_check_interval_s: float = 3.0
    circuit_breaker_failures: int = 5
    weights: RoutingWeights = field(default_factory=RoutingWeights)


@dataclass(slots=True)
class L1CacheConfig:
    max_items: int = 1000
    ttl_s: int = 300


@dataclass(slots=True)
class RedisCacheConfig:
    enabled: bool = True
    url: str = "redis://redis:6379/0"
    ttl_s: int = 1800


@dataclass(slots=True)
class SemanticCacheConfig:
    enabled: bool = False
    threshold: float = 0.92


@dataclass(slots=True)
class PrefixCacheConfig:
    enabled: bool = True


@dataclass(slots=True)
class CacheConfig:
    enabled: bool = True
    l1: L1CacheConfig = field(default_factory=L1CacheConfig)
    redis: RedisCacheConfig = field(default_factory=RedisCacheConfig)
    semantic: SemanticCacheConfig = field(default_factory=SemanticCacheConfig)
    prefix: PrefixCacheConfig = field(default_factory=PrefixCacheConfig)


@dataclass(slots=True)
class SecurityConfig:
    admin_token_env: str = "SMARTMAAS_ADMIN_TOKEN"
    require_user_auth: bool = False

    def admin_token(self) -> str | None:
        """从环境读取管理 Token。返回 None 表示未配置。"""
        return os.environ.get(self.admin_token_env)


@dataclass(slots=True)
class BackendConfig:
    id: str
    model: str
    base_url: str
    weight: int = 1
    timeout_s: float = 120.0
    max_concurrency: int = 16


@dataclass(slots=True)
class Settings:
    server: ServerConfig = field(default_factory=ServerConfig)
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    backends: list[BackendConfig] = field(default_factory=list)


def _section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key) or {}
    if not isinstance(value, dict):
        raise ValueError(f"配置项 {key!r} 必须是映射，实际是 {type(value).__name__}")
    return value


def _build(dataclass_type: type, raw: dict[str, Any]) -> Any:
    """只挑 dataclass 认识的字段，忽略 YAML 里的多余键并给出警告。"""
    known = {f.name for f in dataclass_type.__dataclass_fields__.values()}
    unknown = set(raw) - known
    if unknown:
        logger.warning(
            "配置 %s 中存在未知项，已忽略：%s", dataclass_type.__name__, sorted(unknown)
        )
    return dataclass_type(**{k: v for k, v in raw.items() if k in known})


def parse_settings(raw: dict[str, Any]) -> Settings:
    """把 YAML 字典解析成 Settings。抽出来单独测试，不碰文件系统。"""
    routing_raw = dict(_section(raw, "routing"))
    weights_raw = routing_raw.pop("weights", None)
    routing = _build(RoutingConfig, routing_raw)
    if weights_raw:
        routing.weights = _build(RoutingWeights, weights_raw)

    cache_raw = dict(_section(raw, "cache"))
    cache = _build(CacheConfig, {k: v for k, v in cache_raw.items() if k not in {"l1", "redis", "semantic", "prefix"}})
    cache.l1 = _build(L1CacheConfig, cache_raw.get("l1") or {})
    cache.redis = _build(RedisCacheConfig, cache_raw.get("redis") or {})
    cache.semantic = _build(SemanticCacheConfig, cache_raw.get("semantic") or {})
    cache.prefix = _build(PrefixCacheConfig, cache_raw.get("prefix") or {})

    backends_raw = raw.get("backends") or []
    if not isinstance(backends_raw, list):
        raise ValueError("配置项 'backends' 必须是列表")
    backends = [_build(BackendConfig, b) for b in backends_raw]

    return Settings(
        server=_build(ServerConfig, _section(raw, "server")),
        routing=routing,
        cache=cache,
        security=_build(SecurityConfig, _section(raw, "security")),
        backends=backends,
    )


def load_settings(path: str | Path | None = None) -> Settings:
    """加载配置。找不到文件时回退到默认值，只记警告不抛异常。"""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        logger.warning("未找到配置文件 %s，使用内置默认值", config_path)
        return Settings()
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"配置文件 {config_path} 顶层必须是映射")
    return parse_settings(raw)
