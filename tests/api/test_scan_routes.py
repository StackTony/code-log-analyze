"""F003 M3 — 8 个 HTTP endpoint（spec §六 + AC-10/11/13）。"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from packages.contracts.enums import SOURCE_KIND_FILE_TAIL, STATUS_ACTIVE
from packages.contracts.log_stream import LogStreamSource


@pytest.fixture()
def client() -> TestClient:
    """构造最小 FastAPI app + 注入 mock OnlineLogScanner。"""
    from fastapi import FastAPI
    from packages.api.routes.scan import build_scan_router

    app = FastAPI()
    scanner = MagicMock()
    # register_source 返回 LogStreamSource stub
    now = datetime.now(UTC)
    fake_src = LogStreamSource(
        id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
        repo_id=None, ingestion_status=STATUS_ACTIVE,
        created_at=now, updated_at=now,
    )
    scanner.register_source.return_value = fake_src
    scanner.list_sources.return_value = [fake_src]
    scanner.pause_source.return_value = None
    scanner.resume_source.return_value = None
    scanner.ingest_event.return_value = MagicMock(
        id="evt-1", source_id="src-1", raw_text="x",
        log_point_id=None, level="INFO", timestamp=None,
        log_message_template=None, variables={}, ingested_at=now,
    )
    scanner.scan_now.return_value = MagicMock(id="rpt-1")
    scanner.list_events.return_value = []
    scanner.list_triggers.return_value = []

    app.include_router(build_scan_router(scanner))
    return TestClient(app)


class TestRegisterSource:
    def test_post_sources_201(self, client: TestClient) -> None:
        resp = client.post("/sources", json={
            "kind": "file_tail", "config": {"path": "/var/log/app.log"},
            "repo_id": None,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "src-1"
        assert data["kind"] == "file_tail"


class TestListSources:
    def test_get_sources_200(self, client: TestClient) -> None:
        resp = client.get("/sources")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestPauseResume:
    def test_post_pause_204(self, client: TestClient) -> None:
        resp = client.post("/sources/src-1/pause")
        assert resp.status_code == 204

    def test_post_resume_204(self, client: TestClient) -> None:
        resp = client.post("/sources/src-1/resume")
        assert resp.status_code == 204


class TestIngestEvent:
    def test_post_ingest_201(self, client: TestClient) -> None:
        resp = client.post("/ingest/src-1", json={"raw_text": "log line"})
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] == "evt-1"


class TestScanNow:
    def test_post_scan_now_201(self, client: TestClient) -> None:
        resp = client.post("/sources/src-1/scan-now")
        assert resp.status_code == 201
        assert resp.json()["id"] == "rpt-1"


class TestListEventsTriggers:
    def test_get_events_200(self, client: TestClient) -> None:
        resp = client.get("/sources/src-1/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_triggers_200(self, client: TestClient) -> None:
        resp = client.get("/sources/src-1/triggers")
        assert resp.status_code == 200
        assert resp.json() == []
