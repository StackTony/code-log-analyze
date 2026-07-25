"""LogPoint dataclass → LogPointAPI Pydantic 转换（spec §十，文若 W-4）。"""
from __future__ import annotations

import dataclasses

from packages.api.schemas.log_point import LLMHypothesisAPI, LogPointAPI
from packages.contracts.log_point import CaseRef, LLMHypothesis, LogPoint


def _caseref_to_dict(c: CaseRef) -> dict:
    return dataclasses.asdict(c)


def _llm_hyp_to_api(h: LLMHypothesis | None) -> LLMHypothesisAPI | None:
    if h is None:
        return None
    return LLMHypothesisAPI.model_validate(h, from_attributes=True)


def log_point_to_response(lp: LogPoint) -> LogPointAPI:
    """LogPoint dataclass → LogPointAPI Pydantic schema。"""
    return LogPointAPI(
        id=lp.id, repo_id=lp.repo_id, git_commit_sha=lp.git_commit_sha,
        extractor_version=lp.extractor_version, file_path=lp.file_path,
        function_signature=lp.function_signature, line_start=lp.line_start,
        line_end=lp.line_end, language=lp.language, log_level=lp.log_level,
        log_message_template=lp.log_message_template,
        log_message_variables=lp.log_message_variables,
        framework_hint=lp.framework_hint, confidence_score=lp.confidence_score,
        enclosing_class=lp.enclosing_class,
        call_chain_to_entry=lp.call_chain_to_entry,
        enclosing_community=lp.enclosing_community,
        evidence_refs=[_caseref_to_dict(c) for c in lp.evidence_refs],
        llm_hypothesis=_llm_hyp_to_api(lp.llm_hypothesis),
        occurrence_count=lp.occurrence_count, is_top_n=lp.is_top_n,
        ingestion_status=lp.ingestion_status,
        first_seen_at=lp.first_seen_at, last_seen_at=lp.last_seen_at,
    )
