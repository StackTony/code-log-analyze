"""Unit D 测试 — AC-9 / AC-10 / AC-11 / AC-13 / TTL。"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    ACTION_CONFIRM_INGESTION,
    LANGUAGE_PYTHON,
    STATUS_CANDIDATE,
    STATUS_CONFIRMED,
)
from packages.contracts.log_point import LogPoint
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import Base, CandidateStagingModel, LogPointModel
from packages.m1.unit_d_candidate_staging import (
    CandidateFilter,
    CandidateStager,
    LogPointFilter,
)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _make_lp(lp_id: str, template: str, count: int = 1) -> LogPoint:
    return LogPoint(
        id=lp_id, repo_id="repo-1", git_commit_sha="abc",
        extractor_version="1.0.0", file_path="src/app.py",
        function_signature="def login()", line_start=10, line_end=10,
        language=LANGUAGE_PYTHON, log_level="INFO",
        log_message_template=template, log_message_variables=["uid"],
        framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
        evidence_refs=[], llm_hypothesis=None,
        occurrence_count=count, is_top_n=False,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


def test_stage_writes_to_candidate_pool_not_main(session: Session) -> None:
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "User {uid} logged in", count=3)]
    stager.stage("repo-1", points)

    # 候选池有
    cand = session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "lp-1"))
    assert cand is not None
    assert cand.occurrence_count == 3
    # 主表没有（AC-11）
    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is None


def test_is_top_n_marked_for_high_freq(session: Session) -> None:
    """AC-10：按 occurrence_count 倒序前 N 标记 is_top_n。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=2)
    # 5 个 log_template，不同 occurrence_count
    points = [
        _make_lp("lp-1", "msg A", count=10),
        _make_lp("lp-2", "msg B", count=5),
        _make_lp("lp-3", "msg C", count=3),
        _make_lp("lp-4", "msg D", count=1),
        _make_lp("lp-5", "msg E", count=1),
    ]
    stager.stage("repo-1", points)

    top_n = session.scalars(
        select(CandidateStagingModel).where(CandidateStagingModel.is_top_n.is_(True))
    ).all()
    top_n_ids = {c.id for c in top_n}
    assert top_n_ids == {"lp-1", "lp-2"}  # 前 2 高频


def test_list_candidates_default_only_top_n(session: Session) -> None:
    """AC-10：默认只返回 is_top_n=True。

    云长 MF-4 修复后加强断言：返回的 LogPoint 含真实字段（file_path/function_signature
    等非空），不再是假数据。验证用户筛选 UI 能看到真实日志内容。
    """
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=2)
    points = [
        _make_lp("lp-1", "msg A", count=10),
        _make_lp("lp-2", "msg B", count=5),
        _make_lp("lp-3", "msg C", count=3),
    ]
    stager.stage("repo-1", points)

    # 默认只 top_n
    result = stager.list_candidates("repo-1", CandidateFilter(include_all=False))
    assert {p.id for p in result} == {"lp-1", "lp-2"}

    # MF-4：返回的 LogPoint 含真实字段（不是空字符串）
    for p in result:
        assert p.file_path  # 非空
        assert p.function_signature  # 非空
        assert p.log_message_template  # 非空
        assert p.language  # 非空
        # first_seen_at / last_seen_at 必填（MF-1）
        assert p.first_seen_at is not None
        assert p.last_seen_at is not None

    # include_all=True 看全部
    result_all = stager.list_candidates("repo-1", CandidateFilter(include_all=True))
    assert len(result_all) == 3


def test_confirm_ingestion_preserves_full_fields(session: Session) -> None:
    """MF-4 修复后：confirm 后主表记录含完整字段（从候选池复制）。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")

    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is not None
    assert main_lp.ingestion_status == STATUS_CONFIRMED
    # MF-4：主表记录含真实字段（不是假数据 "staged" / 空字符串）
    assert main_lp.file_path  # 非空
    assert main_lp.function_signature  # 非空
    assert main_lp.log_message_template == "msg A"


def test_confirm_ingestion_moves_to_main(session: Session) -> None:
    """AC-11：confirm 后入主表。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")

    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is not None
    assert main_lp.ingestion_status == STATUS_CONFIRMED  # 状态机：candidate → confirmed → ingested


def test_query_log_points_returns_only_ingested(session: Session) -> None:
    """AC-13：query_log_points 只返回 ingested。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)
    # 还没 confirm
    result = stager.query_log_points("repo-1", LogPointFilter())
    assert result == []


def test_revoke_ingestion_back_to_candidate(session: Session) -> None:
    """AC-9：revoke 从 ingested 退回 candidate。

    云长 MF-2 修复后断言加强：
    - 主表记录**保留**（不删，符合 P0 持久化铁律）
    - ingestion_status 回退到 candidate
    - query_log_points 不再返回这条（AC-13 只返回 confirmed/ingested）
    """
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)
    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")

    stager.revoke_ingestion("repo-1", ["lp-1"], revoker="user-1")

    # 主表记录保留，状态回 candidate
    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is not None  # MF-2: 不删除
    assert main_lp.ingestion_status == STATUS_CANDIDATE
    # 候选池记录也保留（last_seen_at 刷新）
    cand = session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "lp-1"))
    assert cand is not None
    # query_log_points 不再返回（AC-13）
    result = stager.query_log_points("repo-1", LogPointFilter())
    assert all(p.id != "lp-1" for p in result)


def test_ttl_cleanup_removes_old_candidates(session: Session) -> None:
    """spec Risk 表：candidate TTL 30 天清理。"""
    stager = CandidateStager(session=session, audit=AuditLogger(session), top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    # 手动改 first_seen_at 为 31 天前
    cand = session.scalar(select(CandidateStagingModel).where(CandidateStagingModel.id == "lp-1"))
    cand.first_seen_at = datetime.now(UTC) - timedelta(days=31)
    cand.last_seen_at = cand.first_seen_at
    session.commit()

    removed = stager.cleanup_expired(ttl_days=30)
    assert removed == 1
    # 主表不应有（本来就只是 candidate）
    main_lp = session.scalar(select(LogPointModel).where(LogPointModel.id == "lp-1"))
    assert main_lp is None


def test_audit_log_written_on_confirm(session: Session) -> None:
    """AC-17：写操作写 audit_log。"""
    audit = AuditLogger(session)
    stager = CandidateStager(session=session, audit=audit, top_n=50)
    points = [_make_lp("lp-1", "msg A", count=5)]
    stager.stage("repo-1", points)

    from packages.m1.storage.models import AuditLogModel
    before = session.scalars(select(AuditLogModel)).all()
    stager.confirm_ingestion("repo-1", ["lp-1"], confirmer="user-1")
    after = session.scalars(select(AuditLogModel)).all()
    assert len(after) == len(before) + 1
    # 最新一条 action 是 confirm_ingestion
    assert after[-1].action == ACTION_CONFIRM_INGESTION
