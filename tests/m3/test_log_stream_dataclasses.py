"""F003 M3 — contracts.log_stream dataclass v1 骨架（spec §三）。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.contracts.enums import (
    ACTION_M3_INGEST_EVENT,
    ACTION_M3_REGISTER_SOURCE,
    ACTION_M3_SCAN_NOW,
    SOURCE_KIND_FILE_TAIL,
    SOURCE_KIND_HTTP_WEBHOOK,
    STATUS_ACTIVE,
    STATUS_PAUSED,
    STATUS_STOPPED,
    TRIGGER_ANOMALY_DENSITY,
    TRIGGER_MANUAL,
    TRIGGER_TIME_WINDOW,
)
from packages.contracts.log_stream import (
    LogStreamEvent,
    LogStreamSource,
    ScanTrigger,
)


class TestLogStreamSourceDataclass:
    def test_file_tail_source_minimal(self) -> None:
        now = datetime.now(UTC)
        src = LogStreamSource(
            id="src-1",
            kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/var/log/app.log", "pos_file": ".pos"},
            repo_id=None,
            ingestion_status=STATUS_ACTIVE,
            created_at=now,
            updated_at=now,
        )
        assert src.kind == SOURCE_KIND_FILE_TAIL
        assert src.ingestion_status == STATUS_ACTIVE

    def test_webhook_source_with_repo(self) -> None:
        now = datetime.now(UTC)
        src = LogStreamSource(
            id="src-2",
            kind=SOURCE_KIND_HTTP_WEBHOOK,
            config={"path": "/ingest/src-2", "auth_token": "tok"},
            repo_id="repo-1",
            ingestion_status=STATUS_PAUSED,
            created_at=now,
            updated_at=now,
        )
        assert src.kind == SOURCE_KIND_HTTP_WEBHOOK
        assert src.repo_id == "repo-1"


class TestLogStreamEventDataclass:
    def test_event_matched_log_point(self) -> None:
        e = LogStreamEvent(
            id="evt-1",
            source_id="src-1",
            raw_text="2026-07-28 INFO User 12345 logged in",
            timestamp=datetime.now(UTC),
            level="INFO",
            log_message_template="User {uid} logged in",
            variables={"uid": "12345"},
            log_point_id="lp-1",  # matched
            ingested_at=datetime.now(UTC),
        )
        assert e.log_point_id == "lp-1"
        assert e.variables["uid"] == "12345"

    def test_event_unmatched_log_point_none(self) -> None:
        e = LogStreamEvent(
            id="evt-2",
            source_id="src-1",
            raw_text="weird log line",
            timestamp=None,
            level=None,
            log_message_template=None,
            variables={},
            log_point_id=None,  # unmatched
            ingested_at=datetime.now(UTC),
        )
        assert e.log_point_id is None


class TestScanTriggerDataclass:
    def test_time_window_trigger(self) -> None:
        now = datetime.now(UTC)
        t = ScanTrigger(
            id="trig-1",
            source_id="src-1",
            trigger_kind=TRIGGER_TIME_WINDOW,
            event_count=1000,
            window_start=now,
            window_end=now,
            triggered_report_id="rpt-1",
            triggered_at=now,
            triggered_by="system",
        )
        assert t.trigger_kind == TRIGGER_TIME_WINDOW
        assert t.triggered_by == "system"

    def test_manual_trigger_by_user(self) -> None:
        now = datetime.now(UTC)
        t = ScanTrigger(
            id="trig-2",
            source_id="src-1",
            trigger_kind=TRIGGER_MANUAL,
            event_count=42,
            window_start=now,
            window_end=now,
            triggered_report_id=None,  # not yet filled
            triggered_at=now,
            triggered_by="user-alice",
        )
        assert t.trigger_kind == TRIGGER_MANUAL
        assert t.triggered_report_id is None


class TestEnumsM3:
    """spec §三 枚举常量（M3 新增）。"""

    def test_source_kind_constants(self) -> None:
        assert SOURCE_KIND_FILE_TAIL == "file_tail"
        assert SOURCE_KIND_HTTP_WEBHOOK == "http_webhook"

    def test_status_constants(self) -> None:
        assert STATUS_ACTIVE == "active"
        assert STATUS_PAUSED == "paused"
        assert STATUS_STOPPED == "stopped"

    def test_trigger_kind_constants(self) -> None:
        assert TRIGGER_TIME_WINDOW == "time_window"
        assert TRIGGER_ANOMALY_DENSITY == "anomaly_density"
        assert TRIGGER_MANUAL == "manual"

    def test_action_m3_constants(self) -> None:
        assert ACTION_M3_REGISTER_SOURCE == "m3_register_source"
        assert ACTION_M3_INGEST_EVENT == "m3_ingest_event"
        assert ACTION_M3_SCAN_NOW == "m3_scan_now"
