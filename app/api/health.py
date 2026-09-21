"""健康检查接口（§14.2、§26 当日任务"A 写 /health"）。"""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


async def _redis_status(request: Request) -> str:
    """探测 Redis 状态。

    Redis 未实现时会抛 NotImplementedError，这里按 "not_implemented" 上报
    而不是让 /health 整个失败 —— 健康检查本身不能依赖被测组件，
    否则 Redis 一挂，监控就瞎了。
    """
    settings = request.app.state.settings
    if not settings.cache.redis.enabled:
        return "disabled"
    cache = getattr(request.app.state, "redis_cache", None)
    if cache is None:
        return "not_initialized"
    try:
        await cache.connect()
    except NotImplementedError:
        return "not_implemented"
    except Exception as exc:  # noqa: BLE001 — 健康检查要吞掉所有异常
        return f"error: {type(exc).__name__}"
    return "ok"


@router.get("/health")
async def health(request: Request) -> dict[str, object]:
    registry = request.app.state.registry
    backends = registry.all()
    healthy = sum(1 for b in backends if b.state.value == "healthy")

    return {
        "status": "ok",
        "redis": await _redis_status(request),
        "healthy_backends": healthy,
        "total_backends": len(backends),
    }
