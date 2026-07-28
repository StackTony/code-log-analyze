"""F003 M3 — EventIngestor 解析复用 M2 LogParser + LogPointMatcher（spec §十 + AC-3/4）。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import SOURCE_KIND_FILE_TAIL, STATUS_ACTIVE
from packages.contracts.log_stream import LogStreamSource
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import Base as M1Base
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m3.event_ingestor import EventIngestor
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    M1Base.metadata.create_all(eng)  # audit_log 在 M1 Base
    M3Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def repo(session: Session) -> M3Repository:
    return M3Repository(session)


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def source(repo: M3Repository) -> LogStreamSource:
    now = datetime.now(UTC)
    src = LogStreamSource(
        id="src-1", kind=SOURCE_KIND_FILE_TAIL, config={},
        repo_id=None, ingestion_status=STATUS_ACTIVE,
        created_at=now, updated_at=now,
    )
    repo.save_source(src)
    return src


class TestEventIngestorBasic:
    def test_ingest_parses_log_line(self, repo: M3Repository, audit: AuditLogger, source: LogStreamSource) -> None:
        """M3 EventIngestor 调 M2 LogParser 解析日志条目。"""
        ingestor = EventIngestor(
            repository=repo,
            log_parser=LogParser(),
            log_point_matcher=LogPointMatcher(NullLogPointIndex()),
            audit=audit,
        )
        # LogParser 正则要求 timestamp（date+time）+ level + [module]/module: + message
        # 参考 F002 e2e fixture 用同款格式
        evt = ingestor.ingest(
            source_id="src-1",
            raw_text="2026-07-28 08:30:00,123 INFO [auth] User 12345 logged in",
        )
        assert evt.source_id == "src-1"
        assert evt.raw_text == "2026-07-28 08:30:00,123 INFO [auth] User 12345 logged in"
        # 解析后字段（M2 LogParser 提取）
        assert evt.level == "INFO"
        # log_point_id = None（NullLogPointIndex 返回 None）
        assert evt.log_point_id is None

    def test_ingest_no_log_point_match_keeps_event(self, repo: M3Repository, audit: AuditLogger, source: LogStreamSource) -> None:
        """匹配不上 M1 LogPoint 的事件仍入库（spec §十 + AC-4）。"""
        ingestor = EventIngestor(
            repository=repo,
            log_parser=LogParser(),
            log_point_matcher=LogPointMatcher(NullLogPointIndex()),
            audit=audit,
        )
        evt = ingestor.ingest(source_id="src-1", raw_text="weird log line no template")
        assert evt.log_point_id is None  # unmatched but still saved
        # 验证 DB 已持久化
        evts = repo.list_events("src-1", evt.ingested_at, evt.ingested_at) if evt.ingested_at else []
        assert any(e.id == evt.id for e in evts)
