"""FastAPI 应用入口（§14）。

启动：
    uvicorn app.main:app --reload

【脚手架阶段的临时行为，P0 完成后请删除】
`_try_start` / `_try_stop` 会吞掉 `NotImplementedError` 并打一条日志。
这样在 B/C 的模块还没实现时，网关仍然能启动、`/health` 仍然能用，
三人可以并行开发而互不阻塞。等 §19 第 1 周的 P0 模块全部落地后，
把这些调用改回直接 `await`，不要再吞异常。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import admin, chat, health
from app.backend.health_checker import HealthChecker
from app.backend.proxy import Proxy
from app.backend.registry import BackendRegistry
from app.cache.redis_cache import RedisCache
from app.core.config import load_settings
from app.core.logging import setup_logging
from app.metrics.collector import MetricsCollector
from app.router import build_scheduler

logger = logging.getLogger(__name__)


async def _try_start(name: str, component: object) -> None:
    """启动一个还没实现的组件时不阻断应用启动。见模块 docstring。"""
    try:
        await component.start()  # type: ignore[attr-defined]
    except NotImplementedError:
        logger.warning("组件 %s 尚未实现，跳过启动（脚手架阶段正常）", name)
    except Exception:  # noqa: BLE001 — 启动失败不应拖垮整个网关
        logger.exception("启动组件 %s 失败", name)


async def _try_stop(name: str, component: object, method: str) -> None:
    """按组件各自的生命周期方法名关闭。

    不统一叫 `stop()` 是因为 `Proxy` 包着 `httpx.AsyncClient`、
    `RedisCache` 包着 redis 连接池，它们的关闭方法天然叫 `close()`。
    强行改名反而更别扭，所以这里显式传方法名。
    """
    closer = getattr(component, method, None)
    if closer is None:
        logger.warning("组件 %s 没有 %s() 方法，跳过关闭", name, method)
        return
    try:
        await closer()
    except NotImplementedError:
        logger.warning("组件 %s 的 %s() 尚未实现，跳过", name, method)
    except Exception:  # noqa: BLE001 — 关闭阶段不应再抛异常
        logger.exception("关闭组件 %s 失败", name)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    settings = load_settings()

    app.state.settings = settings
    app.state.registry = BackendRegistry(settings.backends)
    app.state.metrics = MetricsCollector()
    app.state.scheduler = build_scheduler(settings.routing)
    app.state.proxy = Proxy()
    app.state.redis_cache = RedisCache(
        url=settings.cache.redis.url, ttl_s=settings.cache.redis.ttl_s
    )
    app.state.health_checker = HealthChecker(
        registry=app.state.registry,
        interval_s=settings.routing.health_check_interval_s,
    )

    logger.info(
        "SmartMaaS Gateway 启动：%d 个后端，调度策略=%s",
        len(settings.backends),
        settings.routing.strategy,
    )

    await _try_start("Proxy", app.state.proxy)
    await _try_start("HealthChecker", app.state.health_checker)

    yield

    await _try_stop("HealthChecker", app.state.health_checker, "stop")
    await _try_stop("Proxy", app.state.proxy, "close")
    await _try_stop("RedisCache", app.state.redis_cache, "close")


app = FastAPI(
    title="SmartMaaS Gateway",
    description="MaaS 平台的智能路由与多级缓存引擎（中国电子杯赛题七）",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(admin.router)
