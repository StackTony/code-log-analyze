"""Common Pydantic v2 schemas — error/health/ready response（spec §九 + §八）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ErrorResponse(BaseModel):
    """统一错误响应格式（spec §五 + §八）。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = {}


class HealthResponse(BaseModel):
    """Liveness probe 响应。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    status: str  # "ok"


class ReadyResponse(BaseModel):
    """Readiness probe 响应。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    status: str  # "ready" | "not_ready"
    reason: str | None = None
