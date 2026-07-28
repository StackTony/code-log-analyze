"""F003 M3 — TriggerEvaluator 三种触发判定（spec §二 + AC-5/6）。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    SOURCE_KIND_FILE_TAIL,
    STATUS_ACTIVE,
    TRIGGER_ANOMALY_DENSITY,
    TRIGGER_TIME_WINDOW,
)
from packages.contracts.log_stream import LogStreamEvent, LogStreamSource
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository
from packages.m3.trigger_evaluator import TriggerEvaluator


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


def _add_event(repo: M3Repository, source_id: str, level: str, ingested_at: datetime) -> None:
    repo.save_event(LogStreamEvent(
        id=f"evt-{level}-{ingested_at.microsecond}-{ingested_at.second}",
        source_id=source_id, raw_text="x",
        timestamp=ingested_at, level=level,
        log_message_template=None, variables={},
        log_point_id=None, ingested_at=ingested_at,
    ))


class TestTimeWindowTrigger:
    def test_triggers_on_count_threshold(self, repo: M3Repository, source: LogStreamSource) -> None:
        """累积事件数达到阈值 → time_window 触发（AC-5）。"""
        now = datetime.now(UTC)
        # 1000 条事件（默认阈值），不同 microsecond 避免主键冲突
        for i in range(1000):
            _add_event(repo, "src-1", "INFO", now + timedelta(microseconds=i))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert decision.should_trigger
        assert decision.trigger_kind == TRIGGER_TIME_WINDOW

    def test_no_trigger_below_threshold(self, repo: M3Repository, source: LogStreamSource) -> None:
        now = datetime.now(UTC)
        for i in range(500):  # < 1000 阈值
            _add_event(repo, "src-1", "INFO", now + timedelta(microseconds=i))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert not decision.should_trigger


class TestAnomalyDensityTrigger:
    def test_triggers_on_error_density(self, repo: M3Repository, source: LogStreamSource) -> None:
        """error 占比 > 30% 阈值 → anomaly_density 触发（AC-6）。"""
        now = datetime.now(UTC)
        # 40 条 ERROR + 60 条 INFO = 40% > 30%
        for i in range(40):
            _add_event(repo, "src-1", "ERROR", now + timedelta(microseconds=i))
        for i in range(60):
            _add_event(repo, "src-1", "INFO", now + timedelta(microseconds=i + 1000))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,  # not yet hit count threshold
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert decision.should_trigger
        assert decision.trigger_kind == TRIGGER_ANOMALY_DENSITY

    def test_no_trigger_low_error_density(self, repo: M3Repository, source: LogStreamSource) -> None:
        now = datetime.now(UTC)
        # 10 ERROR + 90 INFO = 10% < 30%
        for i in range(10):
            _add_event(repo, "src-1", "ERROR", now + timedelta(microseconds=i))
        for i in range(90):
            _add_event(repo, "src-1", "INFO", now + timedelta(microseconds=i + 1000))
        evaluator = TriggerEvaluator(
            repository=repo,
            time_window_event_count=1000,
            time_window_seconds=300,
            anomaly_density_threshold=0.30,
        )
        decision = evaluator.evaluate("src-1")
        assert not decision.should_trigger
