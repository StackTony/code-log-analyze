"""POST /revoke/{repo_id} 测试（spec §三 + AC-1 + AC-9 + MF-2）。"""
from __future__ import annotations

import pathlib
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import packages.api.deps as deps_mod
from packages.api.app import app
from packages.m1.storage.models import Base, LogPointModel


@pytest.fixture(autouse=True)
def _setup_test_db() -> None:
    """每个测试前设置 in-memory SQLite + 表（shared cache 模式避免多连接问题）。"""
    engine = create_engine(
        "sqlite:///file:test.db?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    deps_mod._engine = engine
    deps_mod.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def repo_with_confirmed_log_point(tmp_path: pathlib.Path) -> tuple[str, str]:
    """创建 repo 并直接插入已确认的 log_point 记录。

    返回 (repo_id, log_point_id)。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "import logging\n"
        "def foo():\n    logging.info('hello')\n",
        encoding="utf-8",
    )

    # 直接在 DB 中插入主表记录（已确认状态）
    repo_id = f"repo-test-{uuid.uuid4().hex[:8]}"
    lp_id = f"lp-{uuid.uuid4().hex}"
    now = datetime.now(UTC)

    session = deps_mod.SessionLocal()
    try:
        lp = LogPointModel(
            id=lp_id,
            repo_id=repo_id,
            git_commit_sha="abc123",
            extractor_version="v1",
            file_path="main.py",
            function_signature="foo()",
            line_start=3,
            line_end=3,
            language="python",
            log_level="INFO",
            log_message_template="hello",
            log_message_variables=[],
            framework_hint="logging",
            confidence_score=0.95,
            enclosing_class=None,
            call_chain_to_entry=[],
            enclosing_community=None,
            evidence_refs_json="[]",
            llm_hypothesis_json=None,
            occurrence_count=1,
            is_top_n=True,
            ingestion_status="confirmed",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(lp)
        session.commit()
    finally:
        session.close()

    return repo_id, lp_id


def test_revoke_returns_204(repo_with_confirmed_log_point: tuple[str, str]) -> None:
    """POST /revoke 返回 204。"""
    repo_id, lp_id = repo_with_confirmed_log_point
    with TestClient(app) as c:
        r = c.post(f"/revoke/{repo_id}", json={
            "log_point_ids": [lp_id],
            "revoker": "alice",
        })
        assert r.status_code == 204


def test_revoke_preserves_record_in_db(repo_with_confirmed_log_point: tuple[str, str]) -> None:
    """MF-2 铁律：revoke 不删记录，仅状态回退。"""
    repo_id, lp_id = repo_with_confirmed_log_point
    with TestClient(app) as c:
        # revoke
        r = c.post(f"/revoke/{repo_id}", json={
            "log_point_ids": [lp_id],
            "revoker": "alice",
        })
        assert r.status_code == 204

    # 直接查 DB 验证记录仍存在（状态变为 candidate）
    session = deps_mod.SessionLocal()
    try:
        lp = session.scalar(
            select(LogPointModel).where(LogPointModel.id == lp_id)
        )
        assert lp is not None  # 记录未删除
        assert lp.ingestion_status == "candidate"  # 状态回退
    finally:
        session.close()


def test_revoke_empty_list_returns_422(repo_with_confirmed_log_point: tuple[str, str]) -> None:
    """空 log_point_ids 返回 422。"""
    repo_id, _ = repo_with_confirmed_log_point
    with TestClient(app) as c:
        r = c.post(f"/revoke/{repo_id}", json={
            "log_point_ids": [],
            "revoker": "alice",
        })
        assert r.status_code == 422
