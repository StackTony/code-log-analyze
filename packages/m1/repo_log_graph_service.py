"""RepoLogGraphService — M1 对外 API（spec 第 226-259 行）。"""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.enums import STATUS_CONFIRMED
from packages.contracts.log_point import CallContext, LLMHypothesis, LogPoint
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
    _llm_hyp_to_json,
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

    # --- F002 §十：M2 Phase 2 假设回写入口（不动已有 6 个方法，AC-18 字节级稳定） ---
    def update_log_point_hypothesis(
        self,
        log_point_ids: list[str],
        hypothesis: LLMHypothesis,
        writer: str,
    ) -> int:
        """F002 §十 AC-9：M2 Phase 2 deep_analyze 完成后回写 M1 LogPoint.llm_hypothesis。

        只更新 confirmed 状态的 LogPoint，防止候选池数据被污染。
        覆盖式写入（Phase 2 iteration 累积上下文时，后一次覆盖前一次）。

        Args:
            log_point_ids: 要回写的 LogPoint id 列表
            hypothesis: LLM 假设对象
            writer: 写入者标识（审计用）

        Returns:
            成功更新的行数（candidate 状态或不存在的 id 不计入）
        """
        if not log_point_ids:
            return 0

        # 仅 confirmed 状态的 LogPoint 才会被回写
        rows = self._session.scalars(
            select(LogPointModel).where(
                LogPointModel.id.in_(log_point_ids),
                LogPointModel.ingestion_status == STATUS_CONFIRMED,
            )
        ).all()
        if not rows:
            return 0

        # 复用 _stager 的序列化逻辑（保持与 confirm_ingestion 路径一致）
        json_str = _llm_hyp_to_json(hypothesis)
        for row in rows:
            row.llm_hypothesis_json = json_str
            row.last_seen_at = hypothesis.generated_at  # 更新 last_seen_at
        self._session.flush()

        # 审计（复用 M1 AuditLogger，action 由调用方决定，这里只记字段级变更）
        self._audit.log(
            actor=writer,
            action="update_log_point_hypothesis",
            target_log_point_ids=log_point_ids,
            extra={"updated_count": len(rows), "model_name": hypothesis.model_name},
        )
        return len(rows)
