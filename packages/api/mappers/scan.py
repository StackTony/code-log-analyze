"""F003 M3 — dataclass → Pydantic 转换（复用 M2 mappers 模式）。"""
from __future__ import annotations

from packages.api.schemas.scan import (
    LogStreamEventAPI,
    LogStreamSourceAPI,
    ScanTriggerAPI,
)
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)


def source_to_api(src: LogStreamSource) -> LogStreamSourceAPI:
    return LogStreamSourceAPI(
        id=src.id, kind=src.kind, config=src.config,
        repo_id=src.repo_id, ingestion_status=src.ingestion_status,
        created_at=src.created_at, updated_at=src.updated_at,
    )


def event_to_api(evt: LogStreamEvent) -> LogStreamEventAPI:
    return LogStreamEventAPI(
        id=evt.id, source_id=evt.source_id, raw_text=evt.raw_text,
        timestamp=evt.timestamp, level=evt.level,
        log_message_template=evt.log_message_template,
        variables=evt.variables, log_point_id=evt.log_point_id,
        ingested_at=evt.ingested_at if evt.ingested_at is not None else datetime_sentinel(),
    )


def trigger_to_api(trig: ScanTrigger) -> ScanTriggerAPI:
    return ScanTriggerAPI(
        id=trig.id, source_id=trig.source_id,
        trigger_kind=trig.trigger_kind, event_count=trig.event_count,
        window_start=trig.window_start, window_end=trig.window_end,
        triggered_report_id=trig.triggered_report_id,
        triggered_at=trig.triggered_at, triggered_by=trig.triggered_by,
    )


# Helper to avoid importing datetime at top of mapper functions
def datetime_sentinel() -> "datetime":  # type: ignore[name-defined]
    """Fallback ingested_at（仅 stub 路径，生产路径必有值）。"""
    from datetime import UTC, datetime
    return datetime.now(UTC)
