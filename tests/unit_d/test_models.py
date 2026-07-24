"""SQLAlchemy models 测试 — 用 SQLite in-memory 验证表结构 + 基础 CRUD。"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.contracts.enums import LANGUAGE_PYTHON, STATUS_CANDIDATE
from packages.m1.storage.models import (
    AuditLogModel,
    Base,
    CandidateStagingModel,
    LogPointModel,
    RepoIngestLockModel,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_log_point_model_roundtrip(db_session: Session) -> None:
    lp = LogPointModel(
        id="lp-1",
        repo_id="repo-1",
        git_commit_sha="abc123",
        extractor_version="1.0.0",
        file_path="src/app.py",
        function_signature="def login()",
        line_start=10,
        line_end=12,
        language=LANGUAGE_PYTHON,
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=1.0,
        enclosing_class=None,
        call_chain_to_entry=["api_handler"],
        enclosing_community="auth",
        evidence_refs_json="[]",
        llm_hypothesis_json=None,
        occurrence_count=1,
        is_top_n=True,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    db_session.add(lp)
    db_session.commit()

    result = db_session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert result is not None
    assert result.file_path == "src/app.py"
    assert result.file_path == result.file_path.replace("\\", "/")  # POSIX 风格
    assert result.ingestion_status == "candidate"


def test_candidate_staging_model_has_full_log_point_fields(db_session: Session) -> None:
    """候选池存储完整 LogPoint 字段（云长 MF-4 修复）。

    CandidateStagingModel 必须 23 字段与 LogPointModel 对齐，
    否则 list_candidates() 返回假数据，用户筛选 UI 无法决策。
    """
    staging = CandidateStagingModel(
        id="cand-1",
        repo_id="repo-1",
        git_commit_sha="abc123",
        extractor_version="1.0.0",
        file_path="src/auth.py",
        function_signature="def logout()",
        line_start=20,
        line_end=22,
        language=LANGUAGE_PYTHON,
        log_level="WARN",
        log_message_template="Session {sid} expired",
        log_message_variables_json='["sid"]',
        framework_hint="logging",
        confidence_score=0.9,
        enclosing_class=None,
        call_chain_to_entry_json='["middleware"]',
        enclosing_community="auth",
        evidence_refs_json="[]",
        llm_hypothesis_json=None,
        occurrence_count=5,
        is_top_n=True,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    db_session.add(staging)
    db_session.commit()

    # 验证候选池可以查询所有 LogPoint 字段
    cand = db_session.scalar(
        select(CandidateStagingModel).where(CandidateStagingModel.id == "cand-1")
    )
    assert cand is not None
    assert cand.file_path == "src/auth.py"
    assert cand.log_level == "WARN"
    assert cand.occurrence_count == 5
    # 主表此时应该没有这条记录（候选池和主表分离）
    main_lp = db_session.scalar(select(LogPointModel).where(LogPointModel.id == "cand-1"))
    assert main_lp is None


def test_repo_ingest_lock_model_state_machine(db_session: Session) -> None:
    lock = RepoIngestLockModel(
        repo_id="repo-1",
        status="running",
        started_at=datetime(2026, 7, 24, tzinfo=UTC),
        finished_at=None,
        error_msg=None,
        ingester="user-1",
    )
    db_session.add(lock)
    db_session.commit()

    result = db_session.scalar(
        select(RepoIngestLockModel).where(RepoIngestLockModel.repo_id == "repo-1")
    )
    assert result.status == "running"


def test_audit_log_model(db_session: Session) -> None:
    audit = AuditLogModel(
        id="audit-1",
        actor="user-1",
        action="ingest_repo",
        target_repo_id="repo-1",
        target_log_point_ids_json=None,
        timestamp=datetime(2026, 7, 24, tzinfo=UTC),
        extra_json='{"incremental": false}',
    )
    db_session.add(audit)
    db_session.commit()
    result = db_session.scalar(select(AuditLogModel).where(AuditLogModel.id == "audit-1"))
    assert result.action == "ingest_repo"
