"""F002 M2 — StorageBackedLogPointIndex 测试（review OQ-2）。

从 M1 LogPointModel 主表（confirmed 状态）建索引：
  - 初始化时预扫全表 → 对每条 log_message_template 归一化 + 哈希
  - 内存 dict: template_hash → LogPoint dataclass
  - lookup_by_template_hash O(1)
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.log_point import LogPoint
from packages.m1.storage.models import Base, LogPointModel
from packages.m2.log_point_matcher import _hash_signature, _normalize_to_signature
from packages.m2.storage_backed_log_point_index import StorageBackedLogPointIndex


@pytest.fixture()
def session_with_log_points():
    """In-memory SQLite + 3 条 confirmed LogPoint + 1 条 candidate。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        now = datetime.now(UTC)
        for i, (template, status) in enumerate([
            ("User {uid} logged in", "confirmed"),
            ("connection refused", "confirmed"),
            ("User {uid} from {ip}", "confirmed"),
            ("should not match", "candidate"),  # candidate 不进 index
        ]):
            s.add(LogPointModel(
                id=f"lp-{i+1}",
                repo_id="repo-1",
                git_commit_sha="sha",
                extractor_version="v1",
                file_path=f"app/file{i}.py",
                function_signature=f"def f{i}()",
                line_start=i * 10 + 1,
                line_end=i * 10 + 1,
                language="python",
                log_level="INFO" if i % 2 == 0 else "ERROR",
                log_message_template=template,
                log_message_variables=[],
                framework_hint="logging",
                confidence_score=0.9,
                enclosing_class=None,
                call_chain_to_entry=[],
                enclosing_community=None,
                evidence_refs_json="[]",
                llm_hypothesis_json=None,
                occurrence_count=1,
                is_top_n=False,
                ingestion_status=status,
                first_seen_at=now,
                last_seen_at=now,
            ))
        s.commit()
        yield s
    engine.dispose()


def test_index_builds_from_confirmed_log_points(session_with_log_points: Session) -> None:
    """初始化时预扫 confirmed 状态的 LogPoint 主表。"""
    idx = StorageBackedLogPointIndex(repo_id="repo-1", session=session_with_log_points)

    # 验证 3 个 confirmed 模板都能查到
    h1 = _hash_signature(_normalize_to_signature("User {uid} logged in"))
    h2 = _hash_signature(_normalize_to_signature("connection refused"))
    h3 = _hash_signature(_normalize_to_signature("User {uid} from {ip}"))
    assert idx.lookup_by_template_hash(h1) is not None
    assert idx.lookup_by_template_hash(h2) is not None
    assert idx.lookup_by_template_hash(h3) is not None


def test_index_excludes_candidate_status(session_with_log_points: Session) -> None:
    """candidate 状态不进 index（M2 只匹配 confirmed，防止污染）。"""
    idx = StorageBackedLogPointIndex(repo_id="repo-1", session=session_with_log_points)
    h = _hash_signature(_normalize_to_signature("should not match"))
    assert idx.lookup_by_template_hash(h) is None


def test_index_normalizes_template_before_hash(session_with_log_points: Session) -> None:
    """M1 用 {uid}、M2 用 {var_0}，归一化后命中同一签名。"""
    idx = StorageBackedLogPointIndex(repo_id="repo-1", session=session_with_log_points)
    # M2 风格的变量编号
    m2_template = "User {var_0} logged in"
    h = _hash_signature(_normalize_to_signature(m2_template))
    lp = idx.lookup_by_template_hash(h)
    assert lp is not None
    assert lp.id == "lp-1"  # M1 那条 "User {uid} logged in"
    assert lp.log_message_template == "User {uid} logged in"


def test_index_returns_none_on_miss(session_with_log_points: Session) -> None:
    """未命中模板返回 None。"""
    idx = StorageBackedLogPointIndex(repo_id="repo-1", session=session_with_log_points)
    h = _hash_signature(_normalize_to_signature("nonexistent template"))
    assert idx.lookup_by_template_hash(h) is None


def test_index_empty_repo_returns_none() -> None:
    """无 confirmed LogPoint 的 repo 也能初始化，lookup 一律 None。"""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        idx = StorageBackedLogPointIndex(repo_id="repo-empty", session=s)
        h = _hash_signature(_normalize_to_signature("anything"))
        assert idx.lookup_by_template_hash(h) is None
    engine.dispose()


def test_index_returns_log_point_dataclass_not_model(
    session_with_log_points: Session,
) -> None:
    """返回 LogPoint dataclass（contracts 层），不是 ORM Model。"""
    idx = StorageBackedLogPointIndex(repo_id="repo-1", session=session_with_log_points)
    h = _hash_signature(_normalize_to_signature("User {uid} logged in"))
    lp = idx.lookup_by_template_hash(h)
    assert isinstance(lp, LogPoint)
    assert lp.repo_id == "repo-1"
    assert lp.ingestion_status == "confirmed"


def test_index_scopes_by_repo_id(session_with_log_points: Session) -> None:
    """repo_id 不匹配的 LogPoint 不进 index。"""
    # 加一个 repo-2 的 LogPoint
    now = datetime.now(UTC)
    session_with_log_points.add(LogPointModel(
        id="lp-other-repo",
        repo_id="repo-2",
        git_commit_sha="sha",
        extractor_version="v1",
        file_path="app/other.py",
        function_signature="def other()",
        line_start=1,
        line_end=1,
        language="python",
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=[],
        framework_hint="logging",
        confidence_score=0.9,
        enclosing_class=None,
        call_chain_to_entry=[],
        enclosing_community=None,
        evidence_refs_json="[]",
        llm_hypothesis_json=None,
        occurrence_count=1,
        is_top_n=False,
        ingestion_status="confirmed",
        first_seen_at=now,
        last_seen_at=now,
    ))
    session_with_log_points.commit()

    # 查 repo-1 的 index，应该只命中 repo-1 的 LogPoint
    idx = StorageBackedLogPointIndex(repo_id="repo-1", session=session_with_log_points)
    h = _hash_signature(_normalize_to_signature("User {uid} logged in"))
    lp = idx.lookup_by_template_hash(h)
    assert lp is not None
    assert lp.repo_id == "repo-1"
