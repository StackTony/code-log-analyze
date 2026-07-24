"""端到端测试 — RepoLogGraphService 5 个 API（AC-1/9/10/11/13/16）。"""
from __future__ import annotations

import json
import pathlib
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import STATUS_CONFIRMED
from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import (
    Config,
    ExtractionConfig,
    LLMConfig,
    MetricsConfig,
    SanitizerConfig,
    StorageConfig,
)
from packages.m1.metrics_emitter import MetricsEmitter
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.storage.models import Base
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_a_repo_registrar import RepoSource, User
from packages.m1.unit_d_candidate_staging import CandidateFilter, LogPointFilter


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def service(session: Session, fixtures_dir: pathlib.Path):
    gn = MagicMock()
    gn.analyze.return_value = None
    gn.cypher.return_value = []
    gn.context.return_value = {}

    llm = AsyncMock()
    llm.complete.return_value = json.dumps({
        "summary": "test", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None,
    })
    cache = MagicMock()
    cache.get.return_value = None

    config = Config(
        llm=LLMConfig(api_key="k", model_name="gpt-4", endpoint="e"),
        storage=StorageConfig(postgres_dsn="d", redis_port=6398, redis_namespace="ns"),
        extraction=ExtractionConfig(
            top_n_candidates=50, include_print=False,
            ingest_timeout_minutes=30, candidate_ttl_days=30,
            extractor_version="1.0.0",
        ),
        sanitizer=SanitizerConfig(enabled=True, patterns=["api_key"], replacement="[R]"),
        metrics=MetricsConfig(enabled=True, endpoint="/metrics", port=9100),
    )

    # 每个测试用独立 registry，避免 prometheus 重复注册
    registry = CollectorRegistry()

    return RepoLogGraphService(
        session=session, gitnexus=gn,
        llm_client=llm, cache=cache, config=config,
        tree_sitter=TreeSitterParser(),
        audit=AuditLogger(session),
        metrics=MetricsEmitter(registry=registry),
    )


def test_ingest_repo_end_to_end(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    # 注意：不使用 @pytest.mark.asyncio，因为 ingest_repo 是同步方法（内部用 asyncio.run）
    repo_id = service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    assert repo_id.startswith("repo-")


def test_list_candidates_after_ingest(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    candidates = service.list_candidates(service._last_repo_id, CandidateFilter(include_all=True))
    assert len(candidates) >= 4  # fixture python_logging_repo 有 4 个 LOG 调用


def test_confirm_then_query(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    repo_id = service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    candidates = service.list_candidates(repo_id, CandidateFilter(include_all=True))
    ids = [c.id for c in candidates]
    service.confirm_ingestion(repo_id, ids, confirmer="user-1")

    queried = service.query_log_points(repo_id, LogPointFilter())
    assert len(queried) == len(ids)
    assert all(q.ingestion_status == STATUS_CONFIRMED for q in queried)


def test_get_call_context_returns_callcontext(
    service: RepoLogGraphService, fixtures_dir: pathlib.Path
) -> None:
    repo_id = service.ingest_repo(
        RepoSource(local_path=str(fixtures_dir / "python_logging_repo")),
        User(id="user-1", name="alice"),
    )
    ctx = service.get_call_context(repo_id, "def login(uid: str) -> bool")
    assert ctx is not None
    assert hasattr(ctx, "callers")
    assert hasattr(ctx, "callees")
