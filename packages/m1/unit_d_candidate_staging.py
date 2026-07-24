"""Unit D: Candidate Staging + Ingestion Gate — 两阶段入库（AC-9/10/11/13 + TTL）。"""
from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.enums import (
    ACTION_CONFIRM_INGESTION,
    ACTION_REVOKE_INGESTION,
    STATUS_CANDIDATE,
    STATUS_CONFIRMED,
    STATUS_INGESTED,
)
from packages.contracts.log_point import CaseRef, LLMHypothesis, LogPoint
from packages.m1.audit_log import AuditLogger
from packages.m1.storage.models import CandidateStagingModel, LogPointModel


@dataclasses.dataclass(frozen=True)
class CandidateFilter:
    include_all: bool = False  # True = 看全部；False = 只看 is_top_n


@dataclasses.dataclass(frozen=True)
class LogPointFilter:
    file_path: str | None = None
    function_signature: str | None = None
    log_level: str | None = None


class CandidateStager:
    def __init__(
        self,
        session: Session,
        audit: AuditLogger,
        top_n: int = 50,
    ) -> None:
        self._session = session
        self._audit = audit
        self._top_n = top_n

    def stage(self, repo_id: str, points: list[LogPoint]) -> None:
        """候选池写入（不入主表）。

        云长 MF-4 修复：候选池存储完整 LogPoint 字段（与 LogPointModel 对齐），
        用户筛选 UI 能看到真实文件路径/函数签名/日志内容（C-5 要求）。
        """
        # 排序找 top_n
        sorted_points = sorted(points, key=lambda p: p.occurrence_count, reverse=True)
        top_ids = {p.id for p in sorted_points[: self._top_n]}

        now = datetime.now(UTC)
        for p in points:
            p.is_top_n = p.id in top_ids
            p.ingestion_status = STATUS_CANDIDATE
            # MF-1：first_seen_at/last_seen_at 必填，候选池写入时设值
            if p.first_seen_at is None:
                p.first_seen_at = now
            if p.last_seen_at is None:
                p.last_seen_at = now

            staging = CandidateStagingModel(
                id=p.id, repo_id=repo_id,
                # 完整 LogPoint 字段（MF-4）
                git_commit_sha=p.git_commit_sha,
                extractor_version=p.extractor_version,
                file_path=p.file_path,
                function_signature=p.function_signature,
                line_start=p.line_start,
                line_end=p.line_end,
                language=p.language,
                log_level=p.log_level,
                log_message_template=p.log_message_template,
                log_message_variables_json=json.dumps(p.log_message_variables),
                framework_hint=p.framework_hint,
                confidence_score=p.confidence_score,
                enclosing_class=p.enclosing_class,
                call_chain_to_entry_json=json.dumps(p.call_chain_to_entry),
                enclosing_community=p.enclosing_community,
                evidence_refs_json=json.dumps([_caseref_to_dict(c) for c in p.evidence_refs]),
                llm_hypothesis_json=_llm_hyp_to_json(p.llm_hypothesis),
                # 频次 + 状态
                occurrence_count=p.occurrence_count,
                is_top_n=p.is_top_n,
                ingestion_status=STATUS_CANDIDATE,
                first_seen_at=p.first_seen_at,
                last_seen_at=p.last_seen_at,
            )
            self._session.add(staging)
        self._session.commit()

    def list_candidates(self, repo_id: str, filter: CandidateFilter) -> list[LogPoint]:
        """AC-10：默认 is_top_n=True。返回完整 LogPoint（MF-4 修复后含真实字段）。"""
        stmt = select(CandidateStagingModel).where(CandidateStagingModel.repo_id == repo_id)
        if not filter.include_all:
            stmt = stmt.where(CandidateStagingModel.is_top_n.is_(True))
        stmt = stmt.order_by(CandidateStagingModel.occurrence_count.desc())
        rows = self._session.scalars(stmt).all()
        return [self._staging_to_log_point(r) for r in rows]

    def confirm_ingestion(
        self, repo_id: str, log_point_ids: list[str], confirmer: str
    ) -> None:
        """AC-11：用户显式勾选后才入主表。

        MF-4 修复：从候选池复制完整 LogPoint 字段到主表（不再用假数据）。

        注意：LogPointModel 使用原生 JSON 列（log_message_variables, call_chain_to_entry），
        而 CandidateStagingModel 使用 _json 后缀的 Text 列。
        """
        for lp_id in log_point_ids:
            staging = self._session.scalar(
                select(CandidateStagingModel).where(CandidateStagingModel.id == lp_id)
            )
            if not staging:
                continue
            # 从候选池复制完整字段到主表
            # 解析 JSON 字段以适配 LogPointModel 的原生 JSON 列
            main_lp = LogPointModel(
                id=staging.id, repo_id=repo_id,
                git_commit_sha=staging.git_commit_sha,
                extractor_version=staging.extractor_version,
                file_path=staging.file_path,
                function_signature=staging.function_signature,
                line_start=staging.line_start,
                line_end=staging.line_end,
                language=staging.language,
                log_level=staging.log_level,
                log_message_template=staging.log_message_template,
                # LogPointModel 用原生 JSON 列，需解析
                log_message_variables=json.loads(staging.log_message_variables_json),
                framework_hint=staging.framework_hint,
                confidence_score=staging.confidence_score,
                enclosing_class=staging.enclosing_class,
                # LogPointModel 用原生 JSON 列，需解析
                call_chain_to_entry=json.loads(staging.call_chain_to_entry_json),
                enclosing_community=staging.enclosing_community,
                evidence_refs_json=staging.evidence_refs_json,
                llm_hypothesis_json=staging.llm_hypothesis_json,
                occurrence_count=staging.occurrence_count,
                is_top_n=staging.is_top_n,
                ingestion_status=STATUS_CONFIRMED,
                first_seen_at=staging.first_seen_at,
                last_seen_at=staging.last_seen_at,
            )
            self._session.merge(main_lp)
        self._session.commit()
        self._audit.log(
            actor=confirmer, action=ACTION_CONFIRM_INGESTION,
            target_repo_id=repo_id, target_log_point_ids=log_point_ids,
        )

    def revoke_ingestion(
        self, repo_id: str, log_point_ids: list[str], revoker: str
    ) -> None:
        """AC-9：从主表退回候选池。

        云长 MF-2 修复：不删主表记录（违反 P0 持久化铁律——删除 ≠ 退回），
        改为状态机回退 ingestion_status: ingested/confirmed → candidate。
        保留主表记录，用户可追溯历史；query_log_points 自动过滤 candidate 状态
        （AC-13 只返回 confirmed/ingested）。

        同时刷新候选池记录的 last_seen_at，让候选 UI 重新展示这条候选。
        """
        for lp_id in log_point_ids:
            main_lp = self._session.scalar(
                select(LogPointModel).where(LogPointModel.id == lp_id)
            )
            if main_lp:
                # 状态回退，不删记录
                main_lp.ingestion_status = STATUS_CANDIDATE
                main_lp.last_seen_at = datetime.now(UTC)
                # 同步刷新候选池（如果候选池还有记录的话）
                staging = self._session.scalar(
                    select(CandidateStagingModel).where(CandidateStagingModel.id == lp_id)
                )
                if staging:
                    staging.last_seen_at = main_lp.last_seen_at
        self._session.commit()
        self._audit.log(
            actor=revoker, action=ACTION_REVOKE_INGESTION,
            target_repo_id=repo_id, target_log_point_ids=log_point_ids,
        )

    def query_log_points(self, repo_id: str, filters: LogPointFilter) -> list[LogPoint]:
        """AC-13：只返回 ingested/confirmed 状态。"""
        stmt = (
            select(LogPointModel)
            .where(LogPointModel.repo_id == repo_id)
            .where(LogPointModel.ingestion_status.in_([STATUS_CONFIRMED, STATUS_INGESTED]))
        )
        if filters.file_path:
            stmt = stmt.where(LogPointModel.file_path == filters.file_path)
        if filters.function_signature:
            stmt = stmt.where(LogPointModel.function_signature == filters.function_signature)
        if filters.log_level:
            stmt = stmt.where(LogPointModel.log_level == filters.log_level)
        rows = self._session.scalars(stmt).all()
        return [self._model_to_log_point(r) for r in rows]

    def cleanup_expired(self, ttl_days: int = 30) -> int:
        """spec Risk：candidate TTL 清理。

        只删 candidate 状态的（主表已 confirmed/ingested 不动）。
        云长 SF-4 修复方向：触发机制待定（cron / 惰性 / worker），
        v1 实现由 ingest_repo 完成后顺带调用——见 plan T14 service 层。
        """
        cutoff = datetime.now(UTC) - timedelta(days=ttl_days)
        to_delete = self._session.scalars(
            select(CandidateStagingModel)
            .where(CandidateStagingModel.last_seen_at < cutoff)
            .where(CandidateStagingModel.ingestion_status == STATUS_CANDIDATE)
        ).all()
        for r in to_delete:
            self._session.delete(r)
        self._session.commit()
        return len(to_delete)

    def _staging_to_log_point(self, r: CandidateStagingModel) -> LogPoint:
        """MF-4 修复：从候选池完整字段重建 LogPoint（不再返回假数据）。"""
        return LogPoint(
            id=r.id, repo_id=r.repo_id,
            git_commit_sha=r.git_commit_sha,
            extractor_version=r.extractor_version,
            file_path=r.file_path,
            function_signature=r.function_signature,
            line_start=r.line_start, line_end=r.line_end,
            language=r.language, log_level=r.log_level,
            log_message_template=r.log_message_template,
            log_message_variables=json.loads(r.log_message_variables_json),
            framework_hint=r.framework_hint,
            confidence_score=r.confidence_score,
            enclosing_class=r.enclosing_class,
            call_chain_to_entry=json.loads(r.call_chain_to_entry_json),
            enclosing_community=r.enclosing_community,
            evidence_refs=[_dict_to_caseref(d) for d in json.loads(r.evidence_refs_json)],
            llm_hypothesis=_json_to_llm_hyp(r.llm_hypothesis_json),
            occurrence_count=r.occurrence_count, is_top_n=r.is_top_n,
            ingestion_status=r.ingestion_status,
            first_seen_at=r.first_seen_at, last_seen_at=r.last_seen_at,
        )

    def _model_to_log_point(self, r: LogPointModel) -> LogPoint:
        """从主表 LogPointModel 转换为 LogPoint dataclass。

        注意：LogPointModel 使用原生 JSON 列（log_message_variables, call_chain_to_entry），
        不需要 JSON 解析。但 evidence_refs_json 和 llm_hypothesis_json 需要。
        """
        return LogPoint(
            id=r.id, repo_id=r.repo_id, git_commit_sha=r.git_commit_sha,
            extractor_version=r.extractor_version, file_path=r.file_path,
            function_signature=r.function_signature, line_start=r.line_start, line_end=r.line_end,
            language=r.language, log_level=r.log_level,
            log_message_template=r.log_message_template,
            # LogPointModel 用原生 JSON 列，直接访问
            log_message_variables=r.log_message_variables,
            framework_hint=r.framework_hint, confidence_score=r.confidence_score,
            enclosing_class=r.enclosing_class,
            # LogPointModel 用原生 JSON 列，直接访问
            call_chain_to_entry=r.call_chain_to_entry,
            enclosing_community=r.enclosing_community,
            # JSON 字段需要解析
            evidence_refs=[_dict_to_caseref(d) for d in json.loads(r.evidence_refs_json)],
            llm_hypothesis=_json_to_llm_hyp(r.llm_hypothesis_json),
            occurrence_count=r.occurrence_count, is_top_n=r.is_top_n,
            ingestion_status=r.ingestion_status,
            first_seen_at=r.first_seen_at, last_seen_at=r.last_seen_at,
        )


# --- MF-4 修复辅助函数：CaseRef/LLMHypothesis 序列化反序列化 ---
# 候选池表用 JSON 字段存 evidence_refs 和 llm_hypothesis，需要 ↔ dataclass 转换

def _caseref_to_dict(c: CaseRef) -> dict:
    return {
        "case_id": c.case_id, "repo_id": c.repo_id,
        "file_path": c.file_path, "function_signature": c.function_signature,
        "log_template": c.log_template, "resolved_at": c.resolved_at.isoformat(),
        "resolution_summary": c.resolution_summary, "resolution_diff_url": c.resolution_diff_url,
    }


def _dict_to_caseref(d: dict) -> CaseRef:
    return CaseRef(
        case_id=d["case_id"], repo_id=d["repo_id"],
        file_path=d["file_path"], function_signature=d["function_signature"],
        log_template=d["log_template"],
        resolved_at=datetime.fromisoformat(d["resolved_at"]),
        resolution_summary=d["resolution_summary"],
        resolution_diff_url=d.get("resolution_diff_url"),
    )


def _llm_hyp_to_json(hyp: LLMHypothesis | None) -> str | None:
    if hyp is None:
        return None
    return json.dumps({
        "summary": hyp.summary, "possible_causes": hyp.possible_causes,
        "error_kind": hyp.error_kind, "suggested_check": hyp.suggested_check,
        "model_name": hyp.model_name, "prompt_hash": hyp.prompt_hash,
        "generated_at": hyp.generated_at.isoformat(),
    })


def _json_to_llm_hyp(s: str | None) -> LLMHypothesis | None:
    if not s:
        return None
    d = json.loads(s)
    return LLMHypothesis(
        summary=d["summary"], possible_causes=d["possible_causes"],
        error_kind=d["error_kind"], suggested_check=d.get("suggested_check"),
        model_name=d["model_name"], prompt_hash=d["prompt_hash"],
        generated_at=datetime.fromisoformat(d["generated_at"]),
    )
