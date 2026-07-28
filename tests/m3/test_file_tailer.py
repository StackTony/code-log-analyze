"""F003 M3 — FileTailer 后台 polling task（spec §二 + AC-1）。"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
from packages.m3.event_ingestor import EventIngestor
from packages.m3.file_tailer import FileTailer
from packages.m3.storage.models import Base as M3Base
from packages.m3.storage.repository import M3Repository
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import Base as M1Base


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
def temp_log_file(tmp_path) -> Path:
    """临时日志文件（用 tmp_path fixture）。"""
    f = tmp_path / "app.log"
    f.write_text("", encoding="utf-8")
    return f


class TestFileTailerPolling:
    def test_poll_once_ingests_new_lines(self, ingestor: EventIngestor, temp_log_file: Path, repo: M3Repository) -> None:
        """单次 polling 读取新增日志行 → EventIngestor 入库（AC-1）。"""
        # 写入 3 行日志
        with open(temp_log_file, "a", encoding="utf-8") as f:
            for i in range(3):
                f.write(f"2026-07-28 INFO line {i}\n")

        tailer = FileTailer(
            source_id="src-1",
            file_path=str(temp_log_file),
            ingestor=ingestor,
            poll_interval_seconds=0.05,
        )
        # 第一次 poll：从 0 开始读
        n = tailer._poll_once()
        assert n == 3

        # DB 验证
        now = datetime.now(UTC)
        evts = repo.list_events("src-1", now.replace(microsecond=0), now)
        # ingested_at 是 datetime.now(UTC) 当下，放宽窗口
        assert len(evts) >= 3

    def test_poll_resume_from_checkpoint(self, ingestor: EventIngestor, temp_log_file: Path) -> None:
        """位置 checkpoint：第二次 poll 从上次位置继续，不重读已读行（AC-1）。"""
        # 第一次写入 2 行
        with open(temp_log_file, "a", encoding="utf-8") as f:
            f.write("2026-07-28 INFO line 0\n")
            f.write("2026-07-28 INFO line 1\n")

        tailer = FileTailer(
            source_id="src-1",
            file_path=str(temp_log_file),
            ingestor=ingestor,
            poll_interval_seconds=0.05,
        )
        n1 = tailer._poll_once()
        assert n1 == 2

        # 第二次写入 2 行（不重读前 2 行）
        with open(temp_log_file, "a", encoding="utf-8") as f:
            f.write("2026-07-28 INFO line 2\n")
            f.write("2026-07-28 INFO line 3\n")

        n2 = tailer._poll_once()
        assert n2 == 2  # 只读新增 2 行

    def test_file_rotation_no_loss(self, ingestor: EventIngestor, tmp_path: Path) -> None:
        """文件轮转（截断）：tailer 检测 size 变小 → reset checkpoint（AC-1）。"""
        f1 = tmp_path / "app.log"
        f1.write_text("2026-07-28 INFO old line\n", encoding="utf-8")

        tailer = FileTailer(
            source_id="src-1",
            file_path=str(f1),
            ingestor=ingestor,
            poll_interval_seconds=0.05,
        )
        tailer._poll_once()  # 读 "old line"

        # 模拟轮转：截断 + 写新内容
        f1.write_text("2026-07-28 INFO new line after rotation\n", encoding="utf-8")
        n = tailer._poll_once()
        assert n == 1  # 轮转后从头读
