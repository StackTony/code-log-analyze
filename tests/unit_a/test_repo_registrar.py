"""Unit A 测试 — AC-1 / AC-2 / AC-14 / AC-20。"""
from __future__ import annotations

import pathlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.contracts.enums import ACTION_INGEST_REPO
from packages.m1.storage.models import Base, RepoIngestLockModel
from packages.m1.unit_a_repo_registrar import (
    RepoRegistrar,
    RepoSource,
    UnsafePathError,
    UnsafeUrlError,
    User,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def registrar(db_session: Session):
    gn_mock = MagicMock()
    gn_mock.analyze.return_value = None
    return RepoRegistrar(gitnexus=gn_mock, session=db_session, git_user_email="bot@codefly")


def test_ingest_local_path_returns_repo_id(registrar: RepoRegistrar, tmp_path: pathlib.Path) -> None:
    source = RepoSource(local_path=str(tmp_path))
    repo_id = registrar.ingest(source, User(id="user-1", name="alice"))
    assert repo_id.startswith("repo-")
    # gitnexus.analyze 被调用
    registrar._gitnexus.analyze.assert_called_once()


def test_ingest_rejects_dotdot_path(registrar: RepoRegistrar) -> None:
    source = RepoSource(local_path="/etc/../../../sensitive")
    with pytest.raises(UnsafePathError):
        registrar.ingest(source, User(id="user-1", name="alice"))


def test_ingest_rejects_non_https_url(registrar: RepoRegistrar) -> None:
    source = RepoSource(url="http://github.com/evil/repo")
    with pytest.raises(UnsafeUrlError):
        registrar.ingest(source, User(id="user-1", name="alice"))


def test_ingest_accepts_https_url(registrar: RepoRegistrar) -> None:
    source = RepoSource(url="https://github.com/foo/bar")
    # Mock _clone_url to avoid network calls
    with patch.object(registrar, "_clone_url", return_value="/tmp/mock-repo"):
        repo_id = registrar.ingest(source, User(id="user-1", name="alice"))
        assert repo_id


def test_concurrent_ingest_same_repo_returns_running(
    db_session: Session, registrar: RepoRegistrar, tmp_path: pathlib.Path
) -> None:
    # 预置一个 running lock
    db_session.add(RepoIngestLockModel(
        repo_id="repo-running",
        status="running",
        started_at=datetime.now(UTC),
        finished_at=None,
        error_msg=None,
        ingester="user-0",
    ))
    db_session.commit()

    # 因为 lock 已存在，新 ingest 应该返回同一个 repo_id 标记 running
    # 用相同 path 触发相同 repo_id hash
    source = RepoSource(local_path=str(tmp_path))
    # 强制让 lock 已存在：
    # 先 ingest 一次让它 running
    with patch.object(registrar, "_compute_repo_id", return_value="repo-running"):
        result = registrar.ingest(source, User(id="user-1", name="alice"))
        assert result == "repo-running"
        # gitnexus.analyze 不应再次调用（因为已经在 running）
        # 第一次 fixture 已调用一次（test_ingest_local_path_returns_repo_id），这里不同 test 互不影响
        # 我们再 assert 当前 test 里没新调用
        # （registrar fixture 是 fresh mock，所以 analyze 不该被调）
        registrar._gitnexus.analyze.assert_not_called()


def test_ingest_writes_audit_log(registrar: RepoRegistrar, tmp_path: pathlib.Path, db_session: Session) -> None:
    from packages.m1.audit_log import AuditLogger
    audit_mock = MagicMock(spec=AuditLogger)
    registrar._audit = audit_mock

    source = RepoSource(local_path=str(tmp_path))
    registrar.ingest(source, User(id="user-1", name="alice"))
    audit_mock.log.assert_called_once()
    call_kwargs = audit_mock.log.call_args
    assert call_kwargs.kwargs["action"] == ACTION_INGEST_REPO


def test_force_release_lock_admin_only(registrar: RepoRegistrar, db_session: Session) -> None:
    # 预置 running lock
    db_session.add(RepoIngestLockModel(
        repo_id="repo-x",
        status="running",
        started_at=datetime.now(UTC),
        finished_at=None,
        error_msg=None,
        ingester="user-0",
    ))
    db_session.commit()

    # 非 admin 调用 → 拒绝
    with pytest.raises(PermissionError):
        registrar.force_release_lock("repo-x", User(id="user-non-admin", name="bob", is_admin=False))

    # admin 调用 → 成功
    registrar.force_release_lock("repo-x", User(id="admin", name="root", is_admin=True))
    lock = db_session.scalar(select(RepoIngestLockModel).where(RepoIngestLockModel.repo_id == "repo-x").order_by(RepoIngestLockModel.id.desc()))
    assert lock.status == "failed"  # 强制释放 = 标记 failed
