"""日志（§8 P0-31）。

每次请求至少记录：request_id / model / selected_backend / cache_status /
status_code / total_latency / error_type。

硬规则：**禁止记录明文 API Key、密码、Token**（§8 P0-31、§13.3）。
本模块提供 `redact_headers()` 供接入层打印请求头前调用。
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

_SENSITIVE_HEADERS = frozenset(
    {"authorization", "proxy-authorization", "x-api-key", "api-key", "cookie"}
)
_REDACTED = "***REDACTED***"


def redact_headers(headers: Any) -> dict[str, str]:
    """返回脱敏后的请求头副本，Authorization / Cookie 等一律替换为占位符。

    只用于日志。转发给后端时必须用原始 headers。
    """
    return {
        str(k): (_REDACTED if str(k).lower() in _SENSITIVE_HEADERS else str(v))
        for k, v in dict(headers).items()
    }


class _KeyValueFormatter(logging.Formatter):
    """把 extra 里的结构化字段附在消息尾部，便于 grep 和后续接入解析。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in _STD_LOG_ATTRS and not k.startswith("_")
        }
        if not extras:
            return base
        return f"{base} | {json.dumps(extras, ensure_ascii=False, default=str)}"


_STD_LOG_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "taskName"}


def setup_logging(level: str = "INFO") -> None:
    """初始化根 logger。应用启动时调用一次。"""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _KeyValueFormatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def log_request(
    *,
    request_id: str,
    model: str,
    selected_backend: str | None,
    cache_status: str,
    status_code: int,
    total_latency_ms: float,
    error_type: str | None = None,
    **extra: Any,
) -> None:
    """按 §8 P0-31 的字段集记录一次请求。"""
    logging.getLogger("smartmaas.access").info(
        "request",
        extra={
            "request_id": request_id,
            "model": model,
            "selected_backend": selected_backend,
            "cache_status": cache_status,
            "status_code": status_code,
            "total_latency_ms": round(total_latency_ms, 2),
            "error_type": error_type,
            **extra,
        },
    )
