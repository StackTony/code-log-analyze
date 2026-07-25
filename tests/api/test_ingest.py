"""POST /ingest 测试（spec §三 + AC-1 + 云长 C-1 修订）。"""
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
def fixture_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """临时 Python 仓（含一个 logging.info 调用）。"""
    repo = tmp_path / "test_repo"
    repo.mkdir()
    (repo / "main.py").write_text(
        "import logging\n"
        "def foo():\n"
        "    logging.info('hello')\n",
        encoding="utf-8",
    )
    return repo


def test_ingest_local_path_returns_repo_id(fixture_repo: pathlib.Path) -> None:
    """POST /ingest 成功返回 201 + repo_id。"""
    with TestClient(app) as c:
        r = c.post("/ingest", json={
            "local_path": str(fixture_repo),
            "ingester": {"id": "u1", "name": "alice"},
        })
        assert r.status_code == 201
        body = r.json()
        assert "repo_id" in body
        assert body["repo_id"].startswith("repo-")


def test_ingest_rejects_missing_source() -> None:
    """缺 local_path 和 github_url 返回 422 VALIDATION_ERROR。"""
    with TestClient(app) as c:
        r = c.post("/ingest", json={
            "ingester": {"id": "u1", "name": "alice"},
        })
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "GENERIC_VALIDATION_ERROR"


def test_ingest_rejects_extra_field(fixture_repo: pathlib.Path) -> None:
    """strict + extra=forbid 拒绝未知字段。"""
    with TestClient(app) as c:
        r = c.post("/ingest", json={
            "local_path": str(fixture_repo),
            "ingester": {"id": "u1", "name": "alice"},
            "extra_field": "forbidden",
        })
        assert r.status_code == 422


# 注：ingest_repo 锁并发场景较难在 TestClient 模拟，留 Task 13 端到端测试覆盖。
