"""LogPoint + LLMHypothesis schemas — 24 字段对齐 LogPoint dataclass（spec §九 + AC-6）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class LLMHypothesisAPI(BaseModel):
    """LLM 假设嵌套 schema（云长 C-3 修订）。"""
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)

    summary: str
    possible_causes: list[str]
    error_kind: str
    suggested_check: str | None = None
    model_name: str
    prompt_hash: str
    generated_at: datetime


class LogPointAPI(BaseModel):
    """LogPoint API schema — 24 字段对齐 LogPoint dataclass（MF-4 + AC-6）。"""
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)

    id: str
    repo_id: str
    git_commit_sha: str
    extractor_version: str
    file_path: str
    function_signature: str
    line_start: int
    line_end: int
    language: str
    log_level: str
    log_message_template: str
    log_message_variables: list[str]
    framework_hint: str
    confidence_score: float
    enclosing_class: str | None = None
    call_chain_to_entry: list[str]
    enclosing_community: str | None = None
    evidence_refs: list[dict[str, Any]]  # CaseRef dict（避免循环依赖）
    llm_hypothesis: LLMHypothesisAPI | None = None
    occurrence_count: int
    is_top_n: bool
    ingestion_status: str
    first_seen_at: datetime
    last_seen_at: datetime
