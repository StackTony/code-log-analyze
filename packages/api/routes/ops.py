"""运维 endpoint — /health + /ready + /metrics（spec §三）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.api.deps import SessionLocal, get_session
from packages.api.schemas.common import HealthResponse, ReadyResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness probe — 进程存活。"""
    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadyResponse)
def ready(session: Session = Depends(get_session)) -> ReadyResponse:  # noqa: B008 — FastAPI Depends pattern
    """Readiness probe — DB 连接 + 就绪接收流量。

    v1.1 B-6 修订：DB 未配置（SessionLocal None）时返回 503 而非 500。
    原 deps.get_session 在 SessionLocal None 时 raise RuntimeError → 500 INTERNAL_ERROR，
    违反 K8s readiness 语义（DB 不可达应 503 让 LB 剔除，不是 500 表示代码 bug）。
    DB 配置了但连接失败仍返回 200 + not_ready（spec §三 原行为，body 状态由 probe 判断）。
    """
    if SessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "GENERIC_NOT_READY",
                "message": "Database not configured (postgres_dsn missing)",
                "details": {"reason": "SessionLocal not initialized"},
            },
        )
    try:
        session.execute(text("SELECT 1"))
    except Exception as e:
        return ReadyResponse(status="not_ready", reason=f"db_unavailable: {e}")
    return ReadyResponse(status="ready")


@router.get("/metrics")
def metrics() -> str:
    """FastAPI 内嵌 /metrics（v1.1 注：实际 metrics 在 9464 独立进程）。

    v1.1 B-2 修订：保留此路由用于 TestClient 测试 + debug 兜底。
    生产 Prometheus 抓取应配置为抓 9464 独立进程端口，**不**抓主进程 8000/metrics，
    避免主进程 REGISTRY 与 9464 进程 REGISTRY 数值不一致导致指标重复。
    详见 README "Metrics 抓取配置"。
    """
    from prometheus_client import generate_latest
    return generate_latest().decode("utf-8")
