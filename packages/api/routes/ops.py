"""运维 endpoint — /health + /ready + /metrics（spec §三）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.api.deps import get_session
from packages.api.schemas.common import HealthResponse, ReadyResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — 进程存活。"""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready(session: Session = Depends(get_session)) -> ReadyResponse:  # noqa: B008 — FastAPI Depends pattern
    """Readiness probe — DB 连接 + 就绪接收流量。"""
    try:
        session.execute(text("SELECT 1"))
    except Exception as e:
        return ReadyResponse(status="not_ready", reason=f"db_unavailable: {e}")
    return ReadyResponse(status="ready")


@router.get("/metrics")
def metrics() -> str:
    """FastAPI 内嵌 /metrics（实际 metrics 在 9100 独立进程）。

    注：家规铁律要求 metrics 9100 独立端口，本路由仅用于
    TestClient 测试 + 兜底（如有反向代理合并端口）。
    """
    from prometheus_client import generate_latest
    return generate_latest().decode("utf-8")
