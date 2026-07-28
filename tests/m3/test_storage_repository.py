"""F003 M3 — Storage Repository CRUD（spec §五 + AC-14）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    TRIGGER_MANUAL,
    TRIGGER_TIME_WINDOW,
)
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


class TestSourceCrud:
    def test_save_and_get(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        src = LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/var/log/app.log"}, repo_id=None,
            ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        )
        repo.save_source(src)
        got = repo.get_source("src-1")
        assert got is not None
        assert got.kind == SOURCE_KIND_FILE_TAIL
        assert got.config["path"] == "/var/log/app.log"

    def test_list_by_status(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        for i, status in enumerate([STATUS_ACTIVE, STATUS_PAUSED, STATUS_ACTIVE]):
            repo.save_source(LogStreamSource(
                id=f"src-{i}", kind=SOURCE_KIND_FILE_TAIL,
                config={}, repo_id=None, ingestion_status=status,
                created_at=now, updated_at=now,
            ))
        active = repo.list_sources(status=STATUS_ACTIVE)
        assert len(active) == 2

    def test_update_status(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        later = now + timedelta(seconds=1)
        repo.update_source_status("src-1", STATUS_PAUSED, updated_at=later)
        got = repo.get_source("src-1")
        assert got is not None
        assert got.ingestion_status == STATUS_PAUSED


class TestEventCrud:
    def test_save_and_list_window(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        # 三条事件，时间分散
        for i, t_offset in enumerate([0, 100, 200]):
            repo.save_event(LogStreamEvent(
                id=f"evt-{i}", source_id="src-1",
                raw_text=f"log line {i}",
                timestamp=now + timedelta(seconds=t_offset),
                level="INFO" if i % 2 == 0 else "ERROR",
                log_message_template=None, variables={},
                log_point_id=None,
                ingested_at=now + timedelta(seconds=t_offset),
            ))
        # 取 window [50, 250] 应得 2 条
        evts = repo.list_events(
            "src-1",
            window_start=now + timedelta(seconds=50),
            window_end=now + timedelta(seconds=250),
        )
        assert len(evts) == 2

    def test_count_by_level(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        for i, level in enumerate(["INFO", "ERROR", "ERROR", "WARN"]):
            repo.save_event(LogStreamEvent(
                id=f"evt-{level}-{i}-{now.microsecond}",
                source_id="src-1", raw_text="x",
                timestamp=now, level=level,
                log_message_template=None, variables={},
                log_point_id=None, ingested_at=now,
            ))
        counts = repo.count_events_by_level(
            "src-1",
            window_start=now - timedelta(seconds=1),
            window_end=now + timedelta(seconds=1),
        )
        assert counts.get("ERROR", 0) == 2
        assert counts.get("INFO", 0) == 1


class TestTriggerCrud:
    def test_save_and_update_report_id(self, repo: M3Repository) -> None:
        now = datetime.now(UTC)
        repo.save_source(LogStreamSource(
            id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
            repo_id=None, ingestion_status=STATUS_ACTIVE,
            created_at=now, updated_at=now,
        ))
        trig = ScanTrigger(
            id="trig-1", source_id="src-1",
            trigger_kind=TRIGGER_TIME_WINDOW,
            event_count=1000,
            window_start=now, window_end=now,
            triggered_report_id=None,
            triggered_at=now, triggered_by="system",
        )
        repo.save_trigger(trig)
        repo.update_trigger_report_id("trig-1", "rpt-1")
        trigs = repo.list_triggers("src-1", None, None)
        assert len(trigs) == 1
        assert trigs[0].triggered_report_id == "rpt-1"
