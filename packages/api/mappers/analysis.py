"""F002 M2 — dataclass ↔ API schema mappers（spec §四）。"""
from __future__ import annotations

from packages.api.schemas.analysis import (
    AnalysisReportAPI,
    AnomalyAPI,
    CaseRefAPI,
    DeepAnalysisAPI,
    ErrorChainAPI,
    TokenUsageAPI,
)
from packages.contracts.analysis_report import AnalysisReport, Anomaly, ErrorChain, TokenUsage
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_point import CaseRef


def _anomaly_to_api(a: Anomaly) -> AnomalyAPI:
    return AnomalyAPI(
        line_ids=a.line_ids, severity=a.severity,
        module=a.module, summary=a.summary,
        evidence_snippets=a.evidence_snippets,
    )


def _error_chain_to_api(ec: ErrorChain) -> ErrorChainAPI:
    return ErrorChainAPI(
        chain_id=ec.chain_id, line_ids_ordered=ec.line_ids_ordered,
        relation=ec.relation, summary=ec.summary,
        confidence_score=ec.confidence_score,
    )


def _token_usage_to_api(tu: TokenUsage) -> TokenUsageAPI:
    return TokenUsageAPI(
        prompt_tokens=tu.prompt_tokens,
        completion_tokens=tu.completion_tokens,
        total_cost_usd=tu.total_cost_usd,
    )


def _caseref_to_api(c: CaseRef) -> CaseRefAPI:
    return CaseRefAPI(
        case_id=c.case_id, repo_id=c.repo_id, file_path=c.file_path,
        function_signature=c.function_signature, log_template=c.log_template,
        resolved_at=c.resolved_at, resolution_summary=c.resolution_summary,
        resolution_diff_url=c.resolution_diff_url,
    )


def analysis_report_to_response(r: AnalysisReport) -> AnalysisReportAPI:
    """AnalysisReport dataclass → AnalysisReportAPI。"""
    return AnalysisReportAPI(
        id=r.id, repo_id=r.repo_id, log_source=r.log_source,
        log_line_count=r.log_line_count,
        window_start=r.window_start, window_end=r.window_end,
        model_name=r.model_name, prompt_hash=r.prompt_hash,
        system_summary=r.system_summary,
        anomaly_localization=[_anomaly_to_api(a) for a in r.anomaly_localization],
        error_correlation=[_error_chain_to_api(ec) for ec in r.error_correlation],
        generated_at=r.generated_at, duration_seconds=r.duration_seconds,
        token_usage=_token_usage_to_api(r.token_usage),
        ingestion_status=r.ingestion_status,
    )


def deep_analysis_to_response(r: DeepAnalysisRecord) -> DeepAnalysisAPI:
    """DeepAnalysisRecord dataclass → DeepAnalysisAPI。"""
    return DeepAnalysisAPI(
        id=r.id, report_id=r.report_id,
        line_ids=r.line_ids, log_point_ids=r.log_point_ids,
        root_cause_hypothesis=r.root_cause_hypothesis,
        fix_suggestion=r.fix_suggestion,
        related_evidence=[_caseref_to_api(e) for e in r.related_evidence],
        model_name=r.model_name, prompt_hash=r.prompt_hash,
        iteration=r.iteration, parent_record_id=r.parent_record_id,
        generated_at=r.generated_at,
        token_usage=_token_usage_to_api(r.token_usage),
    )
