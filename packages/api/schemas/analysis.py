"""F002 M2 — AnalysisReport / DeepAnalysis / archive API schemas（spec §四）。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---- Common sub-structs ----

class AnomalyAPI(BaseModel):
    """spec §三 Anomaly。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    line_ids: list[str]
    severity: str
    module: str | None
    summary: str
    evidence_snippets: list[str]


class ErrorChainAPI(BaseModel):
    """spec §三 ErrorChain。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    chain_id: str
    line_ids_ordered: list[str]
    relation: str
    summary: str
    confidence_score: float


class TokenUsageAPI(BaseModel):
    """spec §三 TokenUsage。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    prompt_tokens: int
    completion_tokens: int
    total_cost_usd: float


# ---- POST /analyze ----

class AnalyzeUserAPI(BaseModel):
    """analyzer 子结构。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    name: str


class AnalyzeRequest(BaseModel):
    """POST /analyze body — spec §四。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    log_text: str | None = None              # 直接传日志文本（互斥三选一）
    log_file_path: str | None = None         # 文件路径
    log_stream_id: str | None = None         # M3 流引用
    analyzer: AnalyzeUserAPI
    repo_id: str | None = None               # 关联代码仓（可选，启用 M1 LogPoint 匹配）
    window_hours: int | None = None          # 时间窗覆盖（None = 默认 24h）

    @classmethod
    def check_at_least_one_source(cls, v: "AnalyzeRequest") -> "AnalyzeRequest":
        if not v.log_text and not v.log_file_path and not v.log_stream_id:
            raise ValueError("must provide one of log_text / log_file_path / log_stream_id")
        return v


class AnalysisReportAPI(BaseModel):
    """AnalysisReport response — spec §四 + §三。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    repo_id: str | None
    log_source: str
    log_line_count: int
    window_start: datetime | None
    window_end: datetime | None
    model_name: str
    prompt_hash: str
    system_summary: str
    anomaly_localization: list[AnomalyAPI]
    error_correlation: list[ErrorChainAPI]
    generated_at: datetime
    duration_seconds: float
    token_usage: TokenUsageAPI
    ingestion_status: str


# ---- POST /analyze/deep ----

class DeepAnalyzeRequest(BaseModel):
    """POST /analyze/deep body — spec §四。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    report_id: str
    line_ids: list[str] = Field(min_length=1)
    analyzer: AnalyzeUserAPI
    iteration_context: str | None = None     # 用户补充上下文


class CaseRefAPI(BaseModel):
    """spec §三 CaseRef。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    case_id: str
    repo_id: str
    file_path: str
    function_signature: str
    log_template: str
    resolved_at: datetime
    resolution_summary: str
    resolution_diff_url: str | None


class DeepAnalysisAPI(BaseModel):
    """DeepAnalysisRecord response — spec §四 + §三。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    report_id: str
    line_ids: list[str]
    log_point_ids: list[str]
    root_cause_hypothesis: str
    fix_suggestion: str | None
    related_evidence: list[CaseRefAPI]
    model_name: str
    prompt_hash: str
    iteration: int
    parent_record_id: str | None
    generated_at: datetime
    token_usage: TokenUsageAPI
