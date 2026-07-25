"""FastAPI 依赖注入 — 全局 engine + sessionmaker + service factory（spec §五 + 云长 I-1 修订）。"""
from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import Config, load_config
from packages.m1.gitnexus_client import (
    GitNexusClient,  # noqa: F401 — placeholder for production use
)
from packages.m1.llm_hypothesis_generator import (  # noqa: F401 — placeholder
    LLMClient,
    LLMHypothesisGenerator,
    RedisCache,
)
from packages.m1.log_sanitizer import LogSanitizer
from packages.m1.log_sanitizer import SanitizerConfig as LogSanitizerConfig
from packages.m1.metrics_emitter import MetricsEmitter
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.tree_sitter_parser import TreeSitterParser

if TYPE_CHECKING:
    pass

# 全局单例（每个 uvicorn worker 独立持有）
_config: Config = load_config()
_dsn = _config.storage.postgres_dsn
# 检查 DSN 非空且非占位符（${...}）才创建 engine
_engine = create_engine(_dsn, pool_pre_ping=True) if _dsn and not _dsn.startswith('${') else None
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False) if _engine else None

# Module-level singleton emitter — constructed once per worker, reused across requests.
_metrics_emitter: MetricsEmitter | None = None


def _get_metrics_emitter() -> MetricsEmitter:
    """Get or create the singleton MetricsEmitter instance."""
    global _metrics_emitter
    if _metrics_emitter is None:
        _metrics_emitter = MetricsEmitter()
    return _metrics_emitter


def get_session() -> Generator[Session, None, None]:
    """FastAPI Depends — per-request session（云长 I-1 修订）。"""
    if SessionLocal is None:
        raise RuntimeError("SessionLocal not initialized — postgres_dsn not configured")
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_service(session: Session = Depends(get_session)) -> Generator[RepoLogGraphService, None, None]:  # type: ignore[assignment]  # noqa: B008 — FastAPI Depends pattern
    """FastAPI Depends — 构造 RepoLogGraphService。"""
    # 复用 M1 service 构造逻辑（参考 tests/e2e/test_repo_log_graph_service.py fixture）
    from unittest.mock import AsyncMock, MagicMock

    gn = MagicMock()
    gn.analyze.return_value = None
    gn.cypher.return_value = []
    gn.context.return_value = {}

    llm = AsyncMock()
    cache = MagicMock()
    cache.get.return_value = None

    sanitizer = LogSanitizer(
        LogSanitizerConfig(
            enabled=_config.sanitizer.enabled,
            patterns=_config.sanitizer.patterns,
            replacement=_config.sanitizer.replacement,
        )
    )
    llm_gen = LLMHypothesisGenerator(  # noqa: F841 — placeholder for production use
        llm_client=llm, cache=cache,
        model_name=_config.llm.model_name,
        extractor_version=_config.extraction.extractor_version,
        sanitizer=sanitizer,
        batch_size=_config.llm.batch_size,
        max_retries=_config.llm.max_retries,
    )
    finder = None  # noqa: F841 — 实际生产用 LogPointFinder(gitnexus=gn, tree_sitter=TreeSitterParser())
    stager = None  # noqa: F841 — 实际生产用 CandidateStager(session=session, audit=AuditLogger(session))

    service = RepoLogGraphService(
        session=session, gitnexus=gn, llm_client=llm, cache=cache, config=_config,
        tree_sitter=TreeSitterParser(), audit=AuditLogger(session),
        metrics=_get_metrics_emitter(),
    )
    try:
        yield service
    finally:
        pass
