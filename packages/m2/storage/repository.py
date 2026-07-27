"""F002 M2 — Storage Repository（spec §五）。

dataclass ↔ Model JSON 转换 mappers + 5 个查询方法：
  - save_analysis_report / get_analysis_report / archive_report
  - save_deep_analysis / get_deep_analysis / list_deep_analyses
  - save_log_entries / list_log_entries

设计：
  - 复杂结构字段（Anomaly/ErrorChain/CallContext/CaseRef/TokenUsage）
    序列化为 JSON Text 存
  - dataclass ↔ JSON 转换的双向函数对称（round-trip 等价）
  - repository 接受 Session 注入，避免与 HTTP service 层耦合
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.enums import STATUS_ARCHIVED
from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import CallContext, CaseRef
from packages.m2.storage.models import (
    AnalysisReportModel,
    DeepAnalysisModel,
    LogEntryModel,
)


# ===================== Anomaly / ErrorChain 序列化 =====================

def _anomaly_to_dict(a: Anomaly) -> dict:
    return {
        "line_ids": a.line_ids, "severity": a.severity,
        "module": a.module, "summary": a.summary,
        "evidence_snippets": a.evidence_snippets,
    }


def _dict_to_anomaly(d: dict) -> Anomaly:
    return Anomaly(
        line_ids=d["line_ids"], severity=d["severity"],
        module=d["module"], summary=d["summary"],
        evidence_snippets=d["evidence_snippets"],
    )


def _error_chain_to_dict(ec: ErrorChain) -> dict:
    return {
        "chain_id": ec.chain_id,
        "line_ids_ordered": ec.line_ids_ordered,
        "relation": ec.relation, "summary": ec.summary,
        "confidence_score": ec.confidence_score,
    }


def _dict_to_error_chain(d: dict) -> ErrorChain:
    return ErrorChain(
        chain_id=d["chain_id"], line_ids_ordered=d["line_ids_ordered"],
        relation=d["relation"], summary=d["summary"],
        confidence_score=d["confidence_score"],
    )


def _token_usage_to_dict(tu: TokenUsage) -> dict:
    return {
        "prompt_tokens": tu.prompt_tokens,
        "completion_tokens": tu.completion_tokens,
        "total_cost_usd": tu.total_cost_usd,
    }


def _dict_to_token_usage(d: dict) -> TokenUsage:
    return TokenUsage(
        prompt_tokens=d["prompt_tokens"],
        completion_tokens=d["completion_tokens"],
        total_cost_usd=d["total_cost_usd"],
    )


# ===================== CaseRef / CallContext 序列化 =====================

def _caseref_to_dict(c: CaseRef) -> dict:
    return {
        "case_id": c.case_id, "repo_id": c.repo_id,
        "file_path": c.file_path, "function_signature": c.function_signature,
        "log_template": c.log_template, "resolved_at": c.resolved_at.isoformat(),
        "resolution_summary": c.resolution_summary,
        "resolution_diff_url": c.resolution_diff_url,
    }


def _dict_to_caseref(d: dict) -> CaseRef:
    return CaseRef(
        case_id=d["case_id"], repo_id=d["repo_id"], file_path=d["file_path"],
        function_signature=d["function_signature"], log_template=d["log_template"],
        resolved_at=datetime.fromisoformat(d["resolved_at"]),
        resolution_summary=d["resolution_summary"],
        resolution_diff_url=d.get("resolution_diff_url"),
    )


def _call_context_to_dict(cc: CallContext) -> dict:
    return {
        "function_signature": cc.function_signature,
        "callers": cc.callers, "callees": cc.callees,
        "enclosing_community": cc.enclosing_community,
        # related_log_points 是 LogPoint dataclass 列表，序列化为 id 列表（够用）
        "related_log_point_ids": [lp.id for lp in cc.related_log_points],
        "evidence_refs": [_caseref_to_dict(e) for e in cc.evidence_refs],
    }


def _dict_to_call_context(d: dict) -> CallContext:
    # related_log_points 在 storage 层无法重建（需要关联查询），暂返回空列表
    # Phase 2 deep_analyze 装配上下文时由 service 层补全
    return CallContext(
        function_signature=d["function_signature"],
        callers=d.get("callers", []),
        callees=d.get("callees", []),
        enclosing_community=d.get("enclosing_community"),
        related_log_points=[],
        evidence_refs=[_dict_to_caseref(e) for e in d.get("evidence_refs", [])],
    )


# ===================== AnalysisReport mappers =====================

def _analysis_report_to_model(report: AnalysisReport) -> AnalysisReportModel:
    return AnalysisReportModel(
        id=report.id,
        repo_id=report.repo_id,
        log_source=report.log_source,
        log_line_count=report.log_line_count,
        window_start=report.window_start,
        window_end=report.window_end,
        model_name=report.model_name,
        prompt_hash=report.prompt_hash,
        system_summary=report.system_summary,
        anomaly_localization_json=json.dumps(
            [_anomaly_to_dict(a) for a in report.anomaly_localization]
        ),
        error_correlation_json=json.dumps(
            [_error_chain_to_dict(ec) for ec in report.error_correlation]
        ),
        generated_at=report.generated_at,
        duration_seconds=report.duration_seconds,
        token_usage_json=json.dumps(_token_usage_to_dict(report.token_usage)),
        ingestion_status=report.ingestion_status,
    )


def _analysis_report_to_dataclass(model: AnalysisReportModel) -> AnalysisReport:
    return AnalysisReport(
        id=model.id,
        repo_id=model.repo_id,
        log_source=model.log_source,
        log_line_count=model.log_line_count,
        window_start=model.window_start,
        window_end=model.window_end,
        model_name=model.model_name,
        prompt_hash=model.prompt_hash,
        system_summary=model.system_summary,
        anomaly_localization=[
            _dict_to_anomaly(d) for d in json.loads(model.anomaly_localization_json)
        ],
        error_correlation=[
            _dict_to_error_chain(d) for d in json.loads(model.error_correlation_json)
        ],
        generated_at=model.generated_at,
        duration_seconds=model.duration_seconds,
        token_usage=_dict_to_token_usage(json.loads(model.token_usage_json)),
        ingestion_status=model.ingestion_status,
    )


# ===================== DeepAnalysisRecord mappers =====================

def _deep_analysis_to_model(record: DeepAnalysisRecord) -> DeepAnalysisModel:
    return DeepAnalysisModel(
        id=record.id,
        report_id=record.report_id,
        line_ids_json=json.dumps(record.line_ids),
        log_point_ids_json=json.dumps(record.log_point_ids),
        call_contexts_json=json.dumps(
            [_call_context_to_dict(cc) for cc in record.call_contexts]
        ),
        root_cause_hypothesis=record.root_cause_hypothesis,
        fix_suggestion=record.fix_suggestion,
        related_evidence_json=json.dumps(
            [_caseref_to_dict(e) for e in record.related_evidence]
        ),
        model_name=record.model_name,
        prompt_hash=record.prompt_hash,
        iteration=record.iteration,
        parent_record_id=record.parent_record_id,
        generated_at=record.generated_at,
        token_usage_json=json.dumps(_token_usage_to_dict(record.token_usage)),
    )


def _deep_analysis_to_dataclass(model: DeepAnalysisModel) -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id=model.id,
        report_id=model.report_id,
        line_ids=json.loads(model.line_ids_json),
        log_point_ids=json.loads(model.log_point_ids_json),
        call_contexts=[
            _dict_to_call_context(d)
            for d in json.loads(model.call_contexts_json)
        ],
        root_cause_hypothesis=model.root_cause_hypothesis,
        fix_suggestion=model.fix_suggestion,
        related_evidence=[
            _dict_to_caseref(d)
            for d in json.loads(model.related_evidence_json)
        ],
        model_name=model.model_name,
        prompt_hash=model.prompt_hash,
        iteration=model.iteration,
        parent_record_id=model.parent_record_id,
        generated_at=model.generated_at,
        token_usage=_dict_to_token_usage(json.loads(model.token_usage_json)),
    )


# ===================== LogEntry mappers =====================

def _log_entry_to_model(entry: LogEntry, report_id: str | None = None) -> LogEntryModel:
    return LogEntryModel(
        id=entry.line_id,
        report_id=report_id,
        raw_text=entry.raw_text,
        timestamp=entry.timestamp,
        level=entry.level,
        log_message_template=entry.log_message_template,
        variables_json=json.dumps(entry.variables),
        source_file=entry.source_file,
        source_line=entry.source_line,
    )


def _log_entry_to_dataclass(model: LogEntryModel) -> LogEntry:
    return LogEntry(
        line_id=model.id,
        raw_text=model.raw_text,
        timestamp=model.timestamp,
        level=model.level,
        log_message_template=model.log_message_template,
        variables=json.loads(model.variables_json),
        source_file=model.source_file,
        source_line=model.source_line,
    )


# ===================== Repository =====================

class M2Repository:
    """M2 持久化层 — 接受 Session 注入，封装三表 CRUD。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    # AnalysisReport
    def save_analysis_report(self, report: AnalysisReport) -> None:
        """插入新报告（同 id 已存在会抛 IntegrityError，由 service 层保证 id 唯一）。"""
        self._session.add(_analysis_report_to_model(report))
        self._session.commit()

    def get_analysis_report(self, report_id: str) -> AnalysisReport | None:
        """按 id 查报告。"""
        m = self._session.get(AnalysisReportModel, report_id)
        return _analysis_report_to_dataclass(m) if m is not None else None

    def archive_report(self, report_id: str) -> bool:
        """draft → archived（spec §三 STATUS_*）。

        Returns:
            True 表示状态已更新，False 表示未找到（或已是 archived 状态）。
        """
        result = self._session.execute(
            update(AnalysisReportModel)
            .where(AnalysisReportModel.id == report_id)
            .where(AnalysisReportModel.ingestion_status != STATUS_ARCHIVED)
            .values(ingestion_status=STATUS_ARCHIVED)
        )
        self._session.commit()
        return result.rowcount > 0

    # DeepAnalysis
    def save_deep_analysis(self, record: DeepAnalysisRecord) -> None:
        self._session.add(_deep_analysis_to_model(record))
        self._session.commit()

    def get_deep_analysis(self, record_id: str) -> DeepAnalysisRecord | None:
        m = self._session.get(DeepAnalysisModel, record_id)
        return _deep_analysis_to_dataclass(m) if m is not None else None

    def list_deep_analyses(self, report_id: str) -> list[DeepAnalysisRecord]:
        """按 report_id 查所有 deep_analysis，按 iteration 升序（spec §三）。"""
        rows = self._session.scalars(
            select(DeepAnalysisModel)
            .where(DeepAnalysisModel.report_id == report_id)
            .order_by(DeepAnalysisModel.iteration.asc())
        ).all()
        return [_deep_analysis_to_dataclass(r) for r in rows]

    # LogEntry
    def save_log_entries(self, entries: list[LogEntry], report_id: str | None = None) -> None:
        """批量保存 LogEntry。"""
        for e in entries:
            self._session.add(_log_entry_to_model(e, report_id=report_id))
        self._session.commit()

    def list_log_entries(self, report_id: str) -> list[LogEntry]:
        """按 report_id 查所有 LogEntry。"""
        rows = self._session.scalars(
            select(LogEntryModel)
            .where(LogEntryModel.report_id == report_id)
            .order_by(LogEntryModel.source_line.asc().nulls_last())
        ).all()
        return [_log_entry_to_dataclass(r) for r in rows]
