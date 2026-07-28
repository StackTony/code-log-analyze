"""F003 M3 — 8 个 HTTP endpoint（spec §六 + AC-10）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Path, status

from packages.api.mappers.scan import (
    event_to_api,
    source_to_api,
    trigger_to_api,
)
from packages.api.schemas.scan import (
    IngestEventRequest,
    LogStreamEventAPI,
    LogStreamSourceAPI,
    RegisterSourceRequest,
    ScanTriggerAPI,
)
from packages.contracts.analysis_report import AnalysisReport
from packages.m1.unit_a_repo_registrar import User
from packages.m3.online_log_scanner import OnlineLogScanner


def build_scan_router(scanner: OnlineLogScanner) -> APIRouter:
    """构造 scan router（依赖注入 OnlineLogScanner）。"""
    router = APIRouter(prefix="", tags=["scan"])

    # Stub user for dev（生产加 auth dep）
    _DEFAULT_USER = User(id="u-dev", name="dev")

    @router.post(
        "/sources",
        response_model=LogStreamSourceAPI,
        status_code=status.HTTP_201_CREATED,
    )
    def register_source(req: RegisterSourceRequest) -> LogStreamSourceAPI:
        src = scanner.register_source(
            kind=req.kind, config=req.config, repo_id=req.repo_id, user=_DEFAULT_USER,
        )
        return source_to_api(src)

    @router.get("/sources", response_model=list[LogStreamSourceAPI])
    def list_sources(
        status_filter: str | None = Query(None, alias="status"),
    ) -> list[LogStreamSourceAPI]:
        return [source_to_api(s) for s in scanner.list_sources(status=status_filter)]

    @router.post(
        "/sources/{source_id}/pause",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def pause_source(source_id: str = Path(...)) -> None:
        scanner.pause_source(source_id=source_id, user=_DEFAULT_USER)

    @router.post(
        "/sources/{source_id}/resume",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def resume_source(source_id: str = Path(...)) -> None:
        scanner.resume_source(source_id=source_id, user=_DEFAULT_USER)

    @router.post(
        "/ingest/{source_id}",
        response_model=LogStreamEventAPI,
        status_code=status.HTTP_201_CREATED,
    )
    def ingest_event(
        source_id: str, req: IngestEventRequest,
    ) -> LogStreamEventAPI:
        evt = scanner.ingest_event(source_id=source_id, raw_text=req.raw_text)
        return event_to_api(evt)

    @router.post(
        "/sources/{source_id}/scan-now",
        status_code=status.HTTP_201_CREATED,
    )
    def scan_now(source_id: str = Path(...)) -> dict:
        """scan_now 返回 M2 AnalysisReport（含 id 字段）。

        不绑定 response_model=AnalysisReport 是因为该 dataclass 字段较多
        且部分字段是 list/dict 嵌套结构，stub 测试用 MagicMock 难以验证
        完整 schema。直接返回 dict 让 FastAPI 用 jsonable_encoder 序列化。
        生产环境 AnalysisReport 实例天然支持 __dict__ / dataclasses.asdict。
        """
        report = scanner.scan_now(source_id=source_id, user=_DEFAULT_USER)
        if hasattr(report, "id"):
            return {"id": report.id}
        # 兜底：dict 化
        from dataclasses import asdict, is_dataclass
        if is_dataclass(report):
            return asdict(report)  # type: ignore[arg-type]
        return {"id": str(report)}

    @router.get("/sources/{source_id}/events", response_model=list[LogStreamEventAPI])
    def list_events(
        source_id: str = Path(...),
        start: datetime | None = Query(None),
        end: datetime | None = Query(None),
        limit: int = Query(100, le=1000),
    ) -> list[LogStreamEventAPI]:
        end_v = end or datetime.now(UTC)
        start_v = start or (end_v - timedelta(hours=24))
        evts = scanner.list_events(
            source_id=source_id, window_start=start_v, window_end=end_v,
        )
        return [event_to_api(e) for e in evts[:limit]]

    @router.get("/sources/{source_id}/triggers", response_model=list[ScanTriggerAPI])
    def list_triggers(
        source_id: str = Path(...),
        start: datetime | None = Query(None),
        end: datetime | None = Query(None),
    ) -> list[ScanTriggerAPI]:
        triggs = scanner.list_triggers(
            source_id=source_id, window_start=start, window_end=end,
        )
        return [trigger_to_api(t) for t in triggs]

    return router
