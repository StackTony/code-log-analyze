"""数据契约子包 — M2/M3/M4 import 这些 dataclass 而非依赖 M1 内部。"""
from packages.contracts.audit import AuditLog
from packages.contracts.log_point import (
    CallContext,
    CaseRef,
    LLMHypothesis,
    LogPoint,
    RepoIngestLock,
)

__all__ = [
    "AuditLog",
    "CallContext",
    "CaseRef",
    "LLMHypothesis",
    "LogPoint",
    "RepoIngestLock",
]
