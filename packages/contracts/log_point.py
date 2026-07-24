"""LogPoint + 关联 dataclass（spec 第 100-181 行）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


@dataclass
class CaseRef:
    case_id: str
    repo_id: str
    file_path: str
    function_signature: str
    log_template: str
    resolved_at: datetime
    resolution_summary: str
    resolution_diff_url: str | None


@dataclass
class LLMHypothesis:
    summary: str
    possible_causes: list[str]
    error_kind: str  # ERROR_KIND_* 常量
    suggested_check: str | None
    model_name: str
    prompt_hash: str
    generated_at: datetime


@dataclass
class LogPoint:
    id: str  # UUID
    repo_id: str
    git_commit_sha: str
    extractor_version: str
    file_path: str  # POSIX 风格
    function_signature: str
    line_start: int
    line_end: int
    language: str  # LANGUAGE_* 常量
    log_level: str
    log_message_template: str
    log_message_variables: list[str]
    framework_hint: str
    confidence_score: float

    # gitnexus 上下文
    enclosing_class: str | None
    call_chain_to_entry: list[str]
    enclosing_community: str | None

    # 时间戳（必填）
    first_seen_at: datetime  # 必填，候选池写入时设值（云长 MF-1 修复）
    last_seen_at: datetime  # 必填，候选池写入时设值（云长 MF-1 修复）

    # 历史案例
    evidence_refs: list[CaseRef] = field(default_factory=list)

    # LLM 假设
    llm_hypothesis: LLMHypothesis | None = None

    # 频次 + 状态
    occurrence_count: int = 0
    is_top_n: bool = False
    ingestion_status: str = "candidate"  # STATUS_* 常量


@dataclass
class CallContext:
    """get_call_context() 返回值 — M4 依赖。"""
    function_signature: str
    callers: list[str]
    callees: list[str]
    enclosing_community: str | None
    related_log_points: list[LogPoint]
    evidence_refs: list[CaseRef]


@dataclass
class RepoIngestLock:
    repo_id: str
    status: str  # "running" | "done" | "failed"
    started_at: datetime
    finished_at: datetime | None
    error_msg: str | None
    ingester: str
