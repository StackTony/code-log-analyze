"""F003 M3 — Storage 三张表 schema 验证（spec §五 + AC-14）。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.m3.storage.models import (
    Base as M3Base,
    LogStreamEventModel,
    LogStreamSourceModel,
    ScanTriggerModel,
)


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


class TestLogStreamSourceModel:
    def test_create_minimal(self, session: Session) -> None:
        now = datetime.now(UTC)
        row = LogStreamSourceModel(
            id="src-1",
            kind="file_tail",
            config_json='{"path": "/var/log/app.log"}',
            repo_id=None,
            ingestion_status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
        got = session.get(LogStreamSourceModel, "src-1")
        assert got is not None
        assert got.kind == "file_tail"
        assert got.ingestion_status == "active"


class TestLogStreamEventModel:
    def test_create_matched(self, session: Session) -> None:
        now = datetime.now(UTC)
        # 先建 source（外键约束）
        session.add(LogStreamSourceModel(
            id="src-1", kind="file_tail", config_json="{}",
            repo_id=None, ingestion_status="active",
            created_at=now, updated_at=now,
        ))
        session.commit()
        evt = LogStreamEventModel(
            id="evt-1",
            source_id="src-1",
            raw_text="some log",
            timestamp=now,
            level="INFO",
            log_message_template="some template",
            variables_json='{"uid": "12345"}',
            log_point_id="lp-1",
            ingested_at=now,
        )
        session.add(evt)
        session.commit()
        got = session.get(LogStreamEventModel, "evt-1")
        assert got is not None
        assert got.log_point_id == "lp-1"


class TestScanTriggerModel:
    def test_create_time_window(self, session: Session) -> None:
        now = datetime.now(UTC)
        session.add(LogStreamSourceModel(
            id="src-1", kind="file_tail", config_json="{}",
            repo_id=None, ingestion_status="active",
            created_at=now, updated_at=now,
        ))
        session.commit()
        trig = ScanTriggerModel(
            id="trig-1",
            source_id="src-1",
            trigger_kind="time_window",
            event_count=1000,
            window_start=now,
            window_end=now,
            triggered_report_id="rpt-1",
            triggered_at=now,
            triggered_by="system",
        )
        session.add(trig)
        session.commit()
        got = session.get(ScanTriggerModel, "trig-1")
        assert got is not None
        assert got.trigger_kind == "time_window"
        assert got.triggered_by == "system"
