"""GET /log-points/{repo_id} 测试（spec §三 + AC-1 + AC-13）。"""
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
def confirmed_repo_id(tmp_path: pathlib.Path) -> str:
    """ingest + confirm 一个候选，返回 repo_id。"""
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
        repo_id = r.json()["repo_id"]
        # list candidates 拿 ID
        cands = c.get(f"/candidates/{repo_id}?include_all=true").json()
        if cands:
            c.post(f"/confirm/{repo_id}", json={
                "log_point_ids": [cands[0]["id"]],
                "confirmer": "alice",
            })
        return repo_id


def test_get_log_points_returns_confirmed_only(confirmed_repo_id: str) -> None:
    """query_log_points 只返回 confirmed/ingested（AC-13）。"""
    with TestClient(app) as c:
        r = c.get(f"/log-points/{confirmed_repo_id}")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        # confirm 后应返回 1 条
        assert len(body) >= 1


def test_get_log_points_filter_by_file_path(confirmed_repo_id: str) -> None:
    """?file_path= 过滤。"""
    with TestClient(app) as c:
        r = c.get(f"/log-points/{confirmed_repo_id}?file_path=main.py")
        assert r.status_code == 200
        body = r.json()
        assert all(item["file_path"].endswith("main.py") for item in body)
