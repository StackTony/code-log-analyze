"""F003 M3 — OnlineLogScanner 7 API 方法编排层（spec §四 + AC-7/8/9/13/17）。"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    SOURCE_KIND_HTTP_WEBHOOK,
    STATUS_ACTIVE,
    TRIGGER_MANUAL,
)
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import Base as M1Base
from packages.m1.unit_a_repo_registrar import User
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m3.event_ingestor import EventIngestor
from packages.m3.online_log_scanner import OnlineLogScanner
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator


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
def ingestor(repo: M3Repository, audit: AuditLogger) -> EventIngestor:
    return EventIngestor(
        repository=repo, log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(NullLogPointIndex()),
        audit=audit,
    )


@pytest.fixture()
def m2_service() -> MagicMock:
    """M2 LogAnalysisService mock（依赖注入）。"""
    m = MagicMock()
    # analyze_logs 返回 AnalysisReport stub
    m.analyze_logs.return_value = MagicMock(id="rpt-mock")
    return m


@pytest.fixture()
def scanner(
    repo: M3Repository, audit: AuditLogger, ingestor: EventIngestor,
    m2_service: MagicMock,
) -> OnlineLogScanner:
    return OnlineLogScanner(
        repository=repo,
        ingestor=ingestor,
        trigger_evaluator=TriggerEvaluator(repository=repo),
        m2_service=m2_service,
        audit=audit,
        # file_tailer_factory 留 Task 8 / routes 里 wire
    )


class TestRegisterSource:
    def test_register_file_tail(self, scanner: OnlineLogScanner) -> None:
        src = scanner.register_source(
            kind=SOURCE_KIND_FILE_TAIL,
            config={"path": "/var/log/app.log"},
            repo_id=None,
            user=User(id="u-1", name="alice"),
        )
        assert src.kind == SOURCE_KIND_FILE_TAIL
        assert src.ingestion_status == STATUS_ACTIVE

    def test_register_webhook_with_repo(self, scanner: OnlineLogScanner) -> None:
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK,
            config={"path": "/ingest/src-x"},
            repo_id="repo-1",
            user=User(id="u-1", name="alice"),
        )
        assert src.kind == SOURCE_KIND_HTTP_WEBHOOK
        assert src.repo_id == "repo-1"


class TestPauseResumeSource:
    def test_pause_keeps_events(self, scanner: OnlineLogScanner, ingestor: EventIngestor) -> None:
        """pause_source 不丢累积事件（AC-9）。"""
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK, config={},
            repo_id=None, user=User(id="u-1", name="alice"),
        )
        # ingest 2 events
        ingestor.ingest(src.id, "2026-07-28 INFO first")
        ingestor.ingest(src.id, "2026-07-28 INFO second")

        scanner.pause_source(src.id, user=User(id="u-1", name="alice"))
        # 事件仍在 DB
        now = datetime.now(UTC)
        evts = scanner._repo.list_events(src.id, now.replace(microsecond=0), now)
        assert len(evts) >= 2


class TestScanNow:
    def test_manual_trigger_calls_m2_analyze_logs(self, scanner: OnlineLogScanner, ingestor: EventIngestor, m2_service: MagicMock) -> None:
        """scan_now 手动触发 M2 analyze_logs（AC-7）。"""
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK, config={},
            repo_id="repo-1", user=User(id="u-1", name="alice"),
        )
        ingestor.ingest(src.id, "2026-07-28 INFO something")

        report = scanner.scan_now(src.id, user=User(id="u-1", name="alice"))
        assert report.id == "rpt-mock"
        m2_service.analyze_logs.assert_called_once()
        # 验证传给 M2 的参数
        call_kwargs = m2_service.analyze_logs.call_args.kwargs
        assert call_kwargs["repo_id"] == "repo-1"


class TestTriggerRecorded:
    def test_scan_now_writes_scan_trigger(self, scanner: OnlineLogScanner, ingestor: EventIngestor, repo: M3Repository) -> None:
        """ScanTrigger 记录持久化（AC-8）。"""
        src = scanner.register_source(
            kind=SOURCE_KIND_HTTP_WEBHOOK, config={},
            repo_id=None, user=User(id="u-1", name="alice"),
        )
        ingestor.ingest(src.id, "2026-07-28 INFO something")

        scanner.scan_now(src.id, user=User(id="u-1", name="alice"))

        triggs = repo.list_triggers(src.id, None, None)
        assert len(triggs) == 1
        assert triggs[0].trigger_kind == TRIGGER_MANUAL
        assert triggs[0].triggered_report_id == "rpt-mock"
