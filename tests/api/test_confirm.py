"""POST /confirm/{repo_id} 测试（spec §三 + AC-1 + AC-11）。"""
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
from packages.m1.storage.models import Base, CandidateStagingModel, LogPointModel


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
def repo_with_candidates(tmp_path: pathlib.Path) -> tuple[str, list[str]]:
    """创建 repo 并直接插入候选池记录（绕过 mock gitnexus 问题）。

    返回 (repo_id, candidate_ids)。
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "import logging\n"
        "def foo():\n    logging.info('hello')\n",
        encoding="utf-8",
    )

    # 直接在 DB 中插入候选池记录
    repo_id = f"repo-test-{uuid.uuid4().hex[:8]}"
    cand_id_1 = f"lp-{uuid.uuid4().hex}"
    cand_id_2 = f"lp-{uuid.uuid4().hex}"
    now = datetime.now(UTC)

    session = deps_mod.SessionLocal()
    try:
        # 插入候选池记录
        cand1 = CandidateStagingModel(
            id=cand_id_1,
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
            log_message_variables_json="[]",
            framework_hint="logging",
            confidence_score=0.95,
            enclosing_class=None,
            call_chain_to_entry_json="[]",
            enclosing_community=None,
            evidence_refs_json="[]",
            llm_hypothesis_json=None,
            occurrence_count=1,
            is_top_n=True,
            ingestion_status="candidate",
            first_seen_at=now,
            last_seen_at=now,
        )
        cand2 = CandidateStagingModel(
            id=cand_id_2,
            repo_id=repo_id,
            git_commit_sha="abc123",
            extractor_version="v1",
            file_path="utils.py",
            function_signature="bar()",
            line_start=10,
            line_end=10,
            language="python",
            log_level="DEBUG",
            log_message_template="debug msg",
            log_message_variables_json="[]",
            framework_hint="logging",
            confidence_score=0.85,
            enclosing_class=None,
            call_chain_to_entry_json="[]",
            enclosing_community=None,
            evidence_refs_json="[]",
            llm_hypothesis_json=None,
            occurrence_count=1,
            is_top_n=False,
            ingestion_status="candidate",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(cand1)
        session.add(cand2)
        session.commit()
    finally:
        session.close()

    return repo_id, [cand_id_1, cand_id_2]


def test_confirm_returns_204(repo_with_candidates: tuple[str, list[str]]) -> None:
    """POST /confirm 返回 204 No Content。"""
    repo_id, cand_ids = repo_with_candidates
    with TestClient(app) as c:
        r = c.post(f"/confirm/{repo_id}", json={
            "log_point_ids": [cand_ids[0]],
            "confirmer": "alice",
        })
        assert r.status_code == 204
        assert r.content == b""


def test_confirm_empty_list_returns_422(repo_with_candidates: tuple[str, list[str]]) -> None:
    """空 log_point_ids 返回 422。"""
    repo_id, _ = repo_with_candidates
    with TestClient(app) as c:
        r = c.post(f"/confirm/{repo_id}", json={
            "log_point_ids": [],
            "confirmer": "alice",
        })
        assert r.status_code == 422


def test_confirm_creates_log_point_record(repo_with_candidates: tuple[str, list[str]]) -> None:
    """confirm 后主表有对应记录（直接查 DB 验证，绕过 prometheus 问题）。"""
    repo_id, cand_ids = repo_with_candidates
    # confirm via HTTP
    with TestClient(app) as c:
        r = c.post(f"/confirm/{repo_id}", json={
            "log_point_ids": [cand_ids[0]],
            "confirmer": "alice",
        })
        assert r.status_code == 204

    # 直接查 DB 验证主表有记录
    session = deps_mod.SessionLocal()
    try:
        lp = session.scalar(
            select(LogPointModel).where(LogPointModel.id == cand_ids[0])
        )
        assert lp is not None
        assert lp.repo_id == repo_id
        assert lp.ingestion_status == "confirmed"
    finally:
        session.close()
