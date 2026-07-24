"""RepoLogGraphService — M1 对外 API（spec 第 226-259 行）。"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.log_point import CallContext, LogPoint
from packages.m1.audit_log import AuditLogger
from packages.m1.config_loader import Config
from packages.m1.gitnexus_client import GitNexusClient
from packages.m1.llm_hypothesis_generator import LLMClient, LLMHypothesisGenerator, RedisCache
from packages.m1.log_sanitizer import LogSanitizer
from packages.m1.log_sanitizer import SanitizerConfig as LogSanitizerConfig
from packages.m1.metrics_emitter import MetricsEmitter
from packages.m1.storage.models import LogPointModel
from packages.m1.tree_sitter_parser import TreeSitterParser
from packages.m1.unit_a_repo_registrar import RepoRegistrar, RepoSource, User
from packages.m1.unit_b_log_point_finder import LogPointFinder
from packages.m1.unit_d_candidate_staging import (
    CandidateFilter,
    CandidateStager,
    LogPointFilter,
)


class RepoLogGraphService:
    """M1 对外 API — 串联 Unit A/B/C/D（AC-1/9/10/11/13/16）。"""

    def __init__(
        self,
        session: Session,
        gitnexus: GitNexusClient,
        llm_client: LLMClient,
        cache: RedisCache,
        config: Config,
        tree_sitter: TreeSitterParser,
        audit: AuditLogger,
        metrics: MetricsEmitter,
    ) -> None:
        self._session = session
        self._config = config
        self._audit = audit
        self._metrics = metrics
        self._last_repo_id: str = ""

        sanitizer = LogSanitizer(
            LogSanitizerConfig(
                enabled=config.sanitizer.enabled,
                patterns=config.sanitizer.patterns,
                replacement=config.sanitizer.replacement,
            )
        )

        self._llm_gen = LLMHypothesisGenerator(
            llm_client=llm_client,
            cache=cache,
            model_name=config.llm.model_name,
            extractor_version=config.extraction.extractor_version,
            sanitizer=sanitizer,
            batch_size=config.llm.batch_size,
            max_retries=config.llm.max_retries,
        )
        self._finder = LogPointFinder(gitnexus=gitnexus, tree_sitter=tree_sitter)
        self._stager = CandidateStager(
            session=session,
            audit=audit,
            top_n=config.extraction.top_n_candidates,
        )
        # T6 fix: 不传 git_user_email 参数（已删除）
        self._registrar = RepoRegistrar(
            gitnexus=gitnexus,
            session=session,
            audit=audit,
            finder=self._finder,
            llm_generator=self._llm_gen,
            extractor_version=config.extraction.extractor_version,
            stager=self._stager,
        )

    def ingest_repo(self, source: RepoSource, ingester: User, incremental: bool = False) -> str:
        """AC-1: 串联 Unit A→B→C→D。"""
        start = time.time()
        repo_id = self._registrar.ingest(source, ingester, incremental=incremental)
        self._last_repo_id = repo_id
        self._metrics.observe_ingest_duration(time.time() - start)
        return repo_id

    def list_candidates(self, repo_id: str, filter: CandidateFilter) -> list[LogPoint]:
        """AC-10: 候选池查询。"""
        return self._stager.list_candidates(repo_id, filter)

    def confirm_ingestion(
        self, repo_id: str, log_point_ids: list[str], confirmer: str
    ) -> None:
        """AC-11: 用户勾选入主表。"""
        self._stager.confirm_ingestion(repo_id, log_point_ids, confirmer=confirmer)

    def revoke_ingestion(
        self, repo_id: str, log_point_ids: list[str], revoker: str
    ) -> None:
        """AC-9: 从主表退回候选池（MF-2，不删记录）。"""
        self._stager.revoke_ingestion(repo_id, log_point_ids, revoker=revoker)

    def query_log_points(self, repo_id: str, filters: LogPointFilter) -> list[LogPoint]:
        """AC-13: 只返回 ingested/confirmed 状态。"""
        return self._stager.query_log_points(repo_id, filters)

    def get_call_context(self, repo_id: str, function_signature: str) -> CallContext:
        """AC-16: 调用上下文（callers/callees 暂时空列表，T14 或后续 family 填充）。"""
        rows = self._session.scalars(
            select(LogPointModel).where(LogPointModel.repo_id == repo_id)
        ).all()
        related = [self._stager._model_to_log_point(r) for r in rows]
        return CallContext(
            function_signature=function_signature,
            callers=[],
            callees=[],
            enclosing_community=rows[0].enclosing_community if rows else None,
            related_log_points=related,
            evidence_refs=[],
        )
