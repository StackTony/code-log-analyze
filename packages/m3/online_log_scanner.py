"""F003 M3 — OnlineLogScanner 7 API 方法编排层（spec §四）。

依赖注入 M2 LogAnalysisService（M2ServiceProtocol）+ M3 内部组件。
不直接 import M2 service，避免循环依赖。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from packages.contracts.analysis_report import AnalysisReport
from packages.contracts.enums import (
    ACTION_M3_PAUSE_SOURCE,
    ACTION_M3_REGISTER_SOURCE,
    ACTION_M3_RESUME_SOURCE,
    ACTION_M3_SCAN_NOW,
    SOURCE_KIND_FILE_TAIL,
    SOURCE_KIND_HTTP_WEBHOOK,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    TRIGGER_MANUAL,
)
from packages.contracts.log_entry import LogSource
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)
from packages.m1.audit_log import AuditLogger
from packages.m1.unit_a_repo_registrar import User
from packages.m3.event_ingestor import EventIngestor
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator


class M2ServiceProtocol(Protocol):
    """M2 LogAnalysisService 的最小协议（M3 仅用 analyze_logs）。"""

    def analyze_logs(
        self,
        log_source: LogSource,
        analyzer: User,
        repo_id: str | None = None,
        window_hours: int | None = None,
    ) -> AnalysisReport: ...


class OnlineLogScanner:
    """M3 在线日志扫描服务（spec §四 7 个 API 方法）。"""

    def __init__(
        self,
        repository: M3Repository,
        ingestor: EventIngestor,
        trigger_evaluator: TriggerEvaluator,
        m2_service: M2ServiceProtocol,
        audit: AuditLogger,
        # file_tailer factory 留 Task 10 在 deps.py wire（lifespan 管理）
        file_tailers: dict[str, object] | None = None,
    ) -> None:
        self._repo = repository
        self._ingestor = ingestor
        self._evaluator = trigger_evaluator
        self._m2 = m2_service
        self._audit = audit
        self._file_tailers: dict[str, object] = file_tailers or {}

    def register_source(
        self,
        kind: str,
        config: dict,
        repo_id: str | None,
        user: User,
    ) -> LogStreamSource:
        if kind not in (SOURCE_KIND_FILE_TAIL, SOURCE_KIND_HTTP_WEBHOOK):
            raise ValueError(f"unsupported source kind: {kind}")
        now = datetime.now(UTC)
        src = LogStreamSource(
            id=f"src-{uuid.uuid4().hex[:12]}",
            kind=kind,
            config=config,
            repo_id=repo_id,
            ingestion_status=STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self._repo.save_source(src)
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_REGISTER_SOURCE,
            target_repo_id=src.repo_id,
            extra={"source_id": src.id, "kind": kind, "repo_id": repo_id},
        )
        return src

    def list_sources(self, status: str | None = None) -> list[LogStreamSource]:
        return self._repo.list_sources(status=status)

    def pause_source(self, source_id: str, user: User) -> None:
        now = datetime.now(UTC)
        self._repo.update_source_status(source_id, STATUS_PAUSED, updated_at=now)
        # 停 file_tailer（如有）
        tailer = self._file_tailers.pop(source_id, None)
        if tailer is not None:
            tailer.stop()  # type: ignore[attr-defined]
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_PAUSE_SOURCE,
            extra={"source_id": source_id},
        )

    def resume_source(self, source_id: str, user: User) -> None:
        now = datetime.now(UTC)
        self._repo.update_source_status(source_id, STATUS_ACTIVE, updated_at=now)
        # 重启 file_tailer 留 Task 10 lifespan wire
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_RESUME_SOURCE,
            extra={"source_id": source_id},
        )

    def ingest_event(self, source_id: str, raw_text: str) -> LogStreamEvent:
        return self._ingestor.ingest(source_id=source_id, raw_text=raw_text)

    def scan_now(self, source_id: str, user: User) -> AnalysisReport:
        """手动触发 M2 analyze_logs（AC-7）。"""
        src = self._repo.get_source(source_id)
        if src is None:
            raise ValueError(f"source {source_id} not found")

        # 取当前累积事件窗口
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=24)  # 默认 24h 窗口
        events = self._repo.list_events(source_id, window_start, now)

        # 构造 LogSource（M2 LogSource 支持 text 模式）
        log_text = "\n".join(e.raw_text for e in events)
        log_source = LogSource(text=log_text)

        # 调 M2
        report = self._m2.analyze_logs(
            log_source=log_source,
            analyzer=user,
            repo_id=src.repo_id,
        )

        # 写 ScanTrigger
        trigger = ScanTrigger(
            id=f"trig-{uuid.uuid4().hex[:12]}",
            source_id=source_id,
            trigger_kind=TRIGGER_MANUAL,
            event_count=len(events),
            window_start=window_start,
            window_end=now,
            triggered_report_id=report.id,
            triggered_at=now,
            triggered_by=user.id,
        )
        self._repo.save_trigger(trigger)
        self._audit.log(
            actor=user.id,
            action=ACTION_M3_SCAN_NOW,
            target_repo_id=src.repo_id,
            extra={"source_id": source_id, "trigger_id": trigger.id, "report_id": report.id},
        )
        return report

    def list_events(
        self, source_id: str, window_start: datetime, window_end: datetime,
    ) -> list[LogStreamEvent]:
        return self._repo.list_events(source_id, window_start, window_end)

    def list_triggers(
        self,
        source_id: str,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> list[ScanTrigger]:
        return self._repo.list_triggers(source_id, window_start, window_end)
