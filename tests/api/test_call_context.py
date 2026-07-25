"""POST /call-context/{repo_id} 测试（spec §三 + AC-1 + 云长 OQ-1 修订）。"""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import packages.api.deps as deps_mod
from packages.api.app import app
from packages.m1.storage.models import Base


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
def ingested_repo_id(tmp_path: pathlib.Path) -> str:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "import logging\n"
        "def foo():\n    logging.info('hello')\n",
        encoding="utf-8",
    )
    with TestClient(app) as c:
        r = c.post("/ingest", json={
            "local_path": str(repo),
            "ingester": {"id": "u1", "name": "alice"},
        })
        return r.json()["repo_id"]


def test_post_call_context_returns_callcontext(ingested_repo_id: str) -> None:
    """POST /call-context/{repo_id} 返回 CallContextAPI。"""
    with TestClient(app) as c:
        r = c.post(f"/call-context/{ingested_repo_id}", json={
            "function_signature": "def foo() -> None",
        })
        assert r.status_code == 200
        body = r.json()
        assert "function_signature" in body
        assert "callers" in body
        assert "callees" in body
        assert "related_log_points" in body


def test_post_call_context_rejects_missing_body(ingested_repo_id: str) -> None:
    """缺 body 返回 422。"""
    with TestClient(app) as c:
        r = c.post(f"/call-context/{ingested_repo_id}", json={})
        assert r.status_code == 422
