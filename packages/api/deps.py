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
from packages.m2.metrics_emitter import M2MetricsEmitter

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
_m2_metrics_emitter: M2MetricsEmitter | None = None


def _get_metrics_emitter() -> MetricsEmitter:
    """Get or create the singleton M1 MetricsEmitter instance."""
    global _metrics_emitter
    if _metrics_emitter is None:
        _metrics_emitter = MetricsEmitter()
    return _metrics_emitter


def _get_m2_metrics_emitter() -> M2MetricsEmitter:
    """Get or create the singleton M2 MetricsEmitter instance（spec §八 + AC-14）。"""
    global _m2_metrics_emitter
    if _m2_metrics_emitter is None:
        _m2_metrics_emitter = M2MetricsEmitter()
    return _m2_metrics_emitter


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


def get_log_analysis_service(  # noqa: B008 — FastAPI Depends pattern
    session: Session = Depends(get_session),
) -> Generator["LogAnalysisService", None, None]:
    """FastAPI Depends — 构造 M2 LogAnalysisService（spec §五）。

    生产环境复用 M1 service（m1_service 注入 get_service 产物）+ 真实 LLM client。
    测试 / fixture 可直接 mock。
    """
    from unittest.mock import AsyncMock, MagicMock

    from packages.m1.llm_hypothesis_generator import LLMClient
    from packages.m2.deep_analyzer import DeepAnalyzer, Phase2Config
    from packages.m2.hypothesis_writer import HypothesisWriter
    from packages.m2.log_analysis_service import LogAnalysisService
    from packages.m2.log_parser import LogParser
    from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
    from packages.m2.report_generator import Phase1Config, ReportGenerator
    from packages.m2.storage.repository import M2Repository
    from packages.m2.storage_backed_log_point_index import (
        LogPointIndexFactory,
    )

    # 复用 M1 service（含 m1_service.update_log_point_hypothesis / get_call_context）
    m1_service_gen = get_service(session)
    m1_service = next(m1_service_gen)

    cache = MagicMock()
    cache.get.return_value = None

    sanitizer = LogSanitizer(
        LogSanitizerConfig(
            enabled=_config.sanitizer.enabled,
            patterns=_config.sanitizer.patterns,
            replacement=_config.sanitizer.replacement,
        )
    )

    # LLM client 占位 — 生产注入真实 LLMClient 子类（review OQ-1）
    llm_phase1 = AsyncMock(spec=LLMClient)
    llm_phase2 = AsyncMock(spec=LLMClient)

    # LogPoint 索引：按 repo_id 动态构造（review OQ-2 已落地真实 index）。
    # service 内部每次 analyze_logs/deep_analyze 收到 repo_id 后调 factory
    # 构造对应 repo 的 index（factory 内部 cache 避免重复扫表）。
    index_factory = LogPointIndexFactory(session=session)

    # Fallback matcher：无 repo_id 场景（text-only analyze_logs）使用。
    # repo_id 非空时 service 内部会通过 index_factory 重建 matcher 覆盖此默认值。
    fallback_matcher = LogPointMatcher(NullLogPointIndex())

    service = LogAnalysisService(
        session=session,
        audit=AuditLogger(session),
        repository=M2Repository(session),
        log_parser=LogParser(),
        log_point_matcher=fallback_matcher,
        report_generator=ReportGenerator(
            llm_client=llm_phase1, cache=cache, sanitizer=sanitizer,
            config=Phase1Config(
                model_name=_config.m2.phase1_model,
                window_hours=_config.m2.phase1_window_hours,
                max_log_lines_per_call=_config.m2.phase1_batch_size,
                cache_ttl_seconds=_config.m2.cache_ttl_days * 86400,
            ),
        ),
        deep_analyzer=DeepAnalyzer(
            llm_client=llm_phase2, cache=cache, sanitizer=sanitizer,
            config=Phase2Config(
                model_name=_config.m2.phase2_model,
                max_iterations=_config.m2.phase2_max_iterations,
                cache_ttl_seconds=_config.m2.cache_ttl_days * 86400,
            ),
        ),
        hypothesis_writer=HypothesisWriter(m1_service=m1_service),
        m1_service=m1_service,
        metrics=_get_m2_metrics_emitter(),
        index_factory=index_factory,
    )
    try:
        yield service
    finally:
        # 关闭 M1 service generator（如有 cleanup）
        try:
            next(m1_service_gen)
        except StopIteration:
            pass


def get_online_log_scanner() -> "OnlineLogScanner":  # type: ignore[name-defined]
    """构造 OnlineLogScanner（依赖注入 m2 service + m1 audit + storage）。

    生产环境用 lifespan 管理 file_tailer task，dev 用 lazy 启动。
    """
    from packages.m2.log_parser import LogParser
    from packages.m2.log_point_matcher import LogPointMatcher, NullLogPointIndex
    from packages.m3.event_ingestor import EventIngestor
    from packages.m3.metrics_emitter import M3MetricsEmitter
    from packages.m3.online_log_scanner import OnlineLogScanner
    from packages.m3.storage.repository import M3Repository
    from packages.m3.trigger_evaluator import TriggerEvaluator

    if SessionLocal is None:
        raise RuntimeError("SessionLocal not initialized — postgres_dsn not configured")

    session = SessionLocal()
    try:
        m2_service_gen = get_log_analysis_service(session)
        m2_service = next(m2_service_gen)
        audit = AuditLogger(session)
        repo = M3Repository(session=session)
        ingestor = EventIngestor(
            repository=repo,
            log_parser=LogParser(),
            log_point_matcher=LogPointMatcher(NullLogPointIndex()),
            audit=audit,
        )
        evaluator = TriggerEvaluator(repository=repo)
        return OnlineLogScanner(
            repository=repo,
            ingestor=ingestor,
            trigger_evaluator=evaluator,
            m2_service=m2_service,
            audit=audit,
        )
    finally:
        # session 在 service 生命周期外仍有效（service 内部可能持有它）
        # 暂不 close，留 lifespan 管理；dev 测试场景手动 close
        pass

