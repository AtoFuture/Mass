"""管理接口（§4 P0-08、§8 P1-33、§14.3、§14.4）。

全部路由挂在 `require_admin_token` 依赖下（§3 P1-06：管理接口必须使用管理员 Token）。
Token 从 `settings.security.admin_token_env` 指定的**环境变量**读取，不落在 YAML 里。
未配置该环境变量时放行并打警告 —— 仅为方便本地开发，部署前必须设置。

【已完成】GET /admin/backends、GET /admin/stats、POST /admin/backends、DELETE /admin/backends/{id}
【待补 —— 负责人：A】DELETE 目前是硬移除。§4 P0-08 要求支持"优雅下线"：
先把实例置为 DRAINING 停止接新请求，等在途请求跑完再真正摘除。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.backend.model import BackendState
from app.backend.registry import BackendNotFoundError, DuplicateBackendError
from app.core.config import BackendConfig

logger = logging.getLogger(__name__)


async def require_admin_token(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """管理接口的鉴权依赖。"""
    settings = request.app.state.settings
    expected = settings.security.admin_token()
    if not expected:
        logger.warning(
            "环境变量 %s 未设置，管理接口当前无鉴权。仅限本地开发使用。",
            settings.security.admin_token_env,
        )
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="管理员 Token 无效")


router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_token)]
)


class BackendCreateRequest(BaseModel):
    """`POST /admin/backends` 的请求体。"""

    id: str
    model: str
    base_url: str
    weight: int = Field(default=1, ge=0)
    timeout_s: float = Field(default=120.0, gt=0)
    max_concurrency: int = Field(default=16, ge=1)


@router.get("/backends")
async def list_backends(request: Request) -> dict[str, object]:
    """列出全部后端实例及其运行时状态（§14.3）。"""
    registry = request.app.state.registry
    return {
        "total": len(registry),
        "backends": [b.snapshot() for b in registry.all()],
    }


@router.post("/backends", status_code=201)
async def create_backend(
    payload: BackendCreateRequest, request: Request
) -> dict[str, object]:
    """动态注册一个后端实例（§4 P0-08）。"""
    registry = request.app.state.registry
    try:
        backend = registry.add(BackendConfig(**payload.model_dump()))
    except DuplicateBackendError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return backend.snapshot()


@router.delete("/backends/{backend_id}")
async def delete_backend(backend_id: str, request: Request) -> dict[str, object]:
    """下线一个后端实例（§4 P0-08）。

    TODO(A)：改为优雅下线 —— 先 `set_state(DRAINING)`，轮询等
    `active_requests` 归零（设一个上限超时），再 `remove()`。
    """
    registry = request.app.state.registry
    try:
        registry.set_state(backend_id, BackendState.DRAINING)
        registry.remove(backend_id)
    except BackendNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"后端 {backend_id!r} 不存在") from exc
    return {"removed": backend_id}


@router.get("/stats")
async def stats(request: Request) -> dict[str, object]:
    """指标快照（§14.4、§8 P1-33）。供答辩展示与压测采集。"""
    return request.app.state.metrics.snapshot(backends=request.app.state.registry.all())
