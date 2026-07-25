"""GET /candidates/{repo_id} 测试（spec §三 + AC-1）。"""
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
    """ingest 一个 fixture repo，返回 repo_id。"""
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
        assert r.status_code == 201
        return r.json()["repo_id"]


def test_get_candidates_default(ingested_repo_id: str) -> None:
    """GET /candidates/{repo_id} 默认返回 is_top_n=True 候选。"""
    with TestClient(app) as c:
        r = c.get(f"/candidates/{ingested_repo_id}")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        # fixture 有 1 个 logging.info 调用
        assert len(body) >= 1


def test_get_candidates_include_all(ingested_repo_id: str) -> None:
    """?include_all=true 返回全部候选。"""
    with TestClient(app) as c:
        r = c.get(f"/candidates/{ingested_repo_id}?include_all=true")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)


def test_get_candidates_invalid_repo_id_returns_empty() -> None:
    """repo_id 不存在返回空列表（不报错）。"""
    with TestClient(app) as c:
        r = c.get("/candidates/repo-nonexistent")
        assert r.status_code == 200
        assert r.json() == []
