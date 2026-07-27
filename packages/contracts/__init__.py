"""数据契约子包 — M2/M3/M4 import 这些 dataclass 而非依赖 M1 内部。"""
from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.audit import AuditLog
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_entry import LogEntry, LogSource
from packages.contracts.log_point import (
    CallContext,
    CaseRef,
    LLMHypothesis,
    LogPoint,
    RepoIngestLock,
)

__all__ = [
    "AnalysisReport",
    "Anomaly",
    "AuditLog",
    "CallContext",
    "CaseRef",
    "DeepAnalysisRecord",
    "ErrorChain",
    "LLMHypothesis",
    "LogEntry",
    "LogPoint",
    "LogSource",
    "RepoIngestLock",
    "TokenUsage",
]
