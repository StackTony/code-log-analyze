"""F003 M3 — Storage Repository（dataclass ↔ Model 转换 + CRUD）。

模式复用 M2 storage/repository.py（to_model / from_model 转换方法）。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)
from packages.m3.storage.models import (
    LogStreamEventModel,
    LogStreamSourceModel,
    ScanTriggerModel,
)


def _source_to_model(source: LogStreamSource) -> LogStreamSourceModel:
    return LogStreamSourceModel(
        id=source.id,
        kind=source.kind,
        config_json=json.dumps(source.config),
        repo_id=source.repo_id,
        ingestion_status=source.ingestion_status,
        created_at=source.created_at,
        updated_at=source.updated_at,
    )


def _source_from_model(row: LogStreamSourceModel) -> LogStreamSource:
    return LogStreamSource(
        id=row.id,
        kind=row.kind,
        config=json.loads(row.config_json),
        repo_id=row.repo_id,
        ingestion_status=row.ingestion_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _event_to_model(event: LogStreamEvent) -> LogStreamEventModel:
    return LogStreamEventModel(
        id=event.id,
        source_id=event.source_id,
        raw_text=event.raw_text,
        timestamp=event.timestamp,
        level=event.level,
        log_message_template=event.log_message_template,
        variables_json=json.dumps(event.variables),
        log_point_id=event.log_point_id,
        ingested_at=event.ingested_at,
    )


def _event_from_model(row: LogStreamEventModel) -> LogStreamEvent:
    return LogStreamEvent(
        id=row.id,
        source_id=row.source_id,
        raw_text=row.raw_text,
        timestamp=row.timestamp,
        level=row.level,
        log_message_template=row.log_message_template,
        variables=json.loads(row.variables_json),
        log_point_id=row.log_point_id,
        ingested_at=row.ingested_at,
    )


def _trigger_to_model(trig: ScanTrigger) -> ScanTriggerModel:
    return ScanTriggerModel(
        id=trig.id,
        source_id=trig.source_id,
        trigger_kind=trig.trigger_kind,
        event_count=trig.event_count,
        window_start=trig.window_start,
        window_end=trig.window_end,
        triggered_report_id=trig.triggered_report_id,
        triggered_at=trig.triggered_at,
        triggered_by=trig.triggered_by,
    )


def _trigger_from_model(row: ScanTriggerModel) -> ScanTrigger:
    return ScanTrigger(
        id=row.id,
        source_id=row.source_id,
        trigger_kind=row.trigger_kind,
        event_count=row.event_count,
        window_start=row.window_start,
        window_end=row.window_end,
        triggered_report_id=row.triggered_report_id,
        triggered_at=row.triggered_at,
        triggered_by=row.triggered_by,
    )


class M3Repository:
    """M3 dataclass ↔ Model 转换 + CRUD。"""

    def __init__(self, session: Session) -> None:
        self._s = session

    def save_source(self, source: LogStreamSource) -> None:
        self._s.add(_source_to_model(source))
        self._s.commit()

    def get_source(self, source_id: str) -> LogStreamSource | None:
        row = self._s.get(LogStreamSourceModel, source_id)
        return _source_from_model(row) if row else None

    def list_sources(self, status: str | None = None) -> list[LogStreamSource]:
        stmt = select(LogStreamSourceModel)
        if status is not None:
            stmt = stmt.where(LogStreamSourceModel.ingestion_status == status)
        rows = self._s.execute(stmt).scalars().all()
        return [_source_from_model(r) for r in rows]

    def update_source_status(
        self, source_id: str, status: str, updated_at: datetime,
    ) -> None:
        row = self._s.get(LogStreamSourceModel, source_id)
        if row is None:
            raise ValueError(f"source {source_id} not found")
        row.ingestion_status = status
        row.updated_at = updated_at
        self._s.commit()

    def save_event(self, event: LogStreamEvent) -> None:
        self._s.add(_event_to_model(event))
        self._s.commit()

    def list_events(
        self, source_id: str,
        window_start: datetime, window_end: datetime,
    ) -> list[LogStreamEvent]:
        stmt = select(LogStreamEventModel).where(
            LogStreamEventModel.source_id == source_id,
            LogStreamEventModel.ingested_at >= window_start,
            LogStreamEventModel.ingested_at <= window_end,
        ).order_by(LogStreamEventModel.ingested_at)
        rows = self._s.execute(stmt).scalars().all()
        return [_event_from_model(r) for r in rows]

    def count_events_by_level(
        self, source_id: str,
        window_start: datetime, window_end: datetime,
    ) -> dict[str, int]:
        stmt = select(LogStreamEventModel).where(
            LogStreamEventModel.source_id == source_id,
            LogStreamEventModel.ingested_at >= window_start,
            LogStreamEventModel.ingested_at <= window_end,
        )
        rows = self._s.execute(stmt).scalars().all()
        counts: dict[str, int] = {}
        for r in rows:
            lvl = r.level or "UNKNOWN"
            counts[lvl] = counts.get(lvl, 0) + 1
        return counts

    def save_trigger(self, trigger: ScanTrigger) -> None:
        self._s.add(_trigger_to_model(trigger))
        self._s.commit()

    def update_trigger_report_id(
        self, trigger_id: str, report_id: str,
    ) -> None:
        row = self._s.get(ScanTriggerModel, trigger_id)
        if row is None:
            raise ValueError(f"trigger {trigger_id} not found")
        row.triggered_report_id = report_id
        self._s.commit()

    def list_triggers(
        self, source_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[ScanTrigger]:
        stmt = select(ScanTriggerModel).where(
            ScanTriggerModel.source_id == source_id,
        )
        if window_start is not None:
            stmt = stmt.where(ScanTriggerModel.triggered_at >= window_start)
        if window_end is not None:
            stmt = stmt.where(ScanTriggerModel.triggered_at <= window_end)
        stmt = stmt.order_by(ScanTriggerModel.triggered_at.desc())
        rows = self._s.execute(stmt).scalars().all()
        return [_trigger_from_model(r) for r in rows]
