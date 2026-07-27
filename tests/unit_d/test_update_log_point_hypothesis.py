"""F002 §十 — M1 RepoLogGraphService.update_log_point_hypothesis 测试。

spec §十：F002 实施时同步加新方法，不修改已有 6 个方法（AC-18 字节级稳定）。
M1 LogPoint.llm_hypothesis 字段在 candidate 阶段可空，confirmed 入库后必填。
M2 Phase 2 deep_analyze 是该字段的实际填充来源。

新方法签名（F002 spec §十）：
    update_log_point_hypothesis(
        log_point_ids: list[str],
        hypothesis: LLMHypothesis,
        writer: str  # 写入者标识（审计）
    ) -> int  # 返回成功更新行数

并发安全：用 WHERE ingestion_status='confirmed' AND id IN (...) 防止候选池数据被写。

测试设计避开 ingest_repo → tree-sitter 链路（环境约束），直接构造 LogPointModel
写入 DB，单独测 update_log_point_hypothesis 方法本身的行为。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import CollectorRegistry
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.enums import STATUS_CONFIRMED
from packages.contracts.log_point import LLMHypothesis
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
from packages.m1.storage.models import Base, LogPointModel
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_d_candidate_staging import LogPointFilter


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture()
def service(session: Session):
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

    registry = CollectorRegistry()

    return RepoLogGraphService(
        session=session, gitnexus=gn,
        llm_client=llm, cache=cache, config=config,
        tree_sitter=TreeSitterParser(),
        audit=AuditLogger(session),
        metrics=MetricsEmitter(registry=registry),
    )


def _make_log_point_row(
    lp_id: str = "lp-1",
    repo_id: str = "repo-1",
    ingestion_status: str = STATUS_CONFIRMED,
) -> LogPointModel:
    """直接构造 LogPointModel 写入 DB，绕开 ingest_repo → tree-sitter 链路。"""
    return LogPointModel(
        id=lp_id,
        repo_id=repo_id,
        git_commit_sha="sha-1",
        extractor_version="1.0.0",
        file_path="app/auth.py",
        function_signature="def login(uid)",
        line_start=10,
        line_end=10,
        language="python",
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=0.9,
        enclosing_class=None,
        call_chain_to_entry=[],
        enclosing_community=None,
        evidence_refs_json="[]",
        llm_hypothesis_json=None,
        occurrence_count=0,
        is_top_n=False,
        ingestion_status=ingestion_status,
        first_seen_at=datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 7, 27, 0, 0, 0, tzinfo=timezone.utc),
    )


def _make_hypothesis(summary: str = "phase2 root cause hypothesis") -> LLMHypothesis:
    return LLMHypothesis(
        summary=summary,
        possible_causes=["db timeout", "auth misconfigured"],
        error_kind="runtime_error",
        suggested_check="check pg connection pool",
        model_name="claude-opus-4",
        prompt_hash="sha256:abc123",
        generated_at=datetime(2026, 7, 27, 0, 0, 0),
    )


def test_update_log_point_hypothesis_writes_to_confirmed(
    service: RepoLogGraphService, session: Session
) -> None:
    """confirmed 状态的 LogPoint 可写入 hypothesis，返回 1。"""
    session.add(_make_log_point_row(lp_id="lp-1", ingestion_status=STATUS_CONFIRMED))
    session.commit()

    n = service.update_log_point_hypothesis(
        log_point_ids=["lp-1"], hypothesis=_make_hypothesis(), writer="m2-phase2-deep-analyzer"
    )
    assert n == 1

    queried = service.query_log_points("repo-1", LogPointFilter())
    assert len(queried) == 1
    assert queried[0].llm_hypothesis is not None
    assert queried[0].llm_hypothesis.summary == "phase2 root cause hypothesis"
    assert queried[0].llm_hypothesis.model_name == "claude-opus-4"


def test_update_log_point_hypothesis_skips_candidate(
    service: RepoLogGraphService, session: Session
) -> None:
    """candidate 状态的 LogPoint 不会被回写（防止候选池数据被污染）。"""
    session.add(_make_log_point_row(lp_id="lp-1", ingestion_status="candidate"))
    session.commit()

    n = service.update_log_point_hypothesis(
        log_point_ids=["lp-1"], hypothesis=_make_hypothesis("should not be written"),
        writer="m2-phase2"
    )
    assert n == 0


def test_update_log_point_hypothesis_batch(
    service: RepoLogGraphService, session: Session
) -> None:
    """批量回写多个 LogPoint，返回成功数。"""
    session.add(_make_log_point_row(lp_id="lp-1", ingestion_status=STATUS_CONFIRMED))
    session.add(_make_log_point_row(lp_id="lp-2", repo_id="repo-1", ingestion_status=STATUS_CONFIRMED))
    session.commit()

    n = service.update_log_point_hypothesis(
        log_point_ids=["lp-1", "lp-2"], hypothesis=_make_hypothesis("batch write"),
        writer="m2-phase2"
    )
    assert n == 2

    queried = service.query_log_points("repo-1", LogPointFilter())
    assert all(q.llm_hypothesis is not None for q in queried)
    assert all(q.llm_hypothesis.summary == "batch write" for q in queried)


def test_update_log_point_hypothesis_unknown_id_returns_zero(
    service: RepoLogGraphService, session: Session
) -> None:
    """不存在的 log_point_id 返回 0。"""
    n = service.update_log_point_hypothesis(
        log_point_ids=["lp-nonexistent-id"], hypothesis=_make_hypothesis(), writer="m2-phase2"
    )
    assert n == 0


def test_update_log_point_hypothesis_empty_list_returns_zero(
    service: RepoLogGraphService, session: Session
) -> None:
    """空列表返回 0。"""
    n = service.update_log_point_hypothesis(
        log_point_ids=[], hypothesis=_make_hypothesis(), writer="m2-phase2"
    )
    assert n == 0


def test_update_log_point_hypothesis_overwrites_existing(
    service: RepoLogGraphService, session: Session
) -> None:
    """重复调用覆盖既有 hypothesis（Phase 2 iteration 累积上下文）。"""
    session.add(_make_log_point_row(lp_id="lp-1", ingestion_status=STATUS_CONFIRMED))
    session.commit()

    service.update_log_point_hypothesis(
        log_point_ids=["lp-1"], hypothesis=_make_hypothesis("iteration 1"),
        writer="m2-phase2"
    )
    n = service.update_log_point_hypothesis(
        log_point_ids=["lp-1"], hypothesis=_make_hypothesis("iteration 2"),
        writer="m2-phase2"
    )
    assert n == 1

    queried = service.query_log_points("repo-1", LogPointFilter())
    assert queried[0].llm_hypothesis.summary == "iteration 2"


def test_update_log_point_hypothesis_mixed_status_batch(
    service: RepoLogGraphService, session: Session
) -> None:
    """混合状态批量：只更新 confirmed 的，candidate 的跳过。"""
    session.add(_make_log_point_row(lp_id="lp-1", ingestion_status=STATUS_CONFIRMED))
    session.add(_make_log_point_row(lp_id="lp-2", repo_id="repo-1", ingestion_status="candidate"))
    session.add(_make_log_point_row(lp_id="lp-3", repo_id="repo-1", ingestion_status=STATUS_CONFIRMED))
    session.commit()

    n = service.update_log_point_hypothesis(
        log_point_ids=["lp-1", "lp-2", "lp-3", "lp-missing"],
        hypothesis=_make_hypothesis(), writer="m2-phase2"
    )
    assert n == 2  # 只 lp-1 + lp-3 命中
