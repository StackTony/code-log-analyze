"""枚举常量 — 字符串 + 常量便于扩展（spec 第 185-208 行）。"""
from __future__ import annotations

# Language
LANGUAGE_C = "c"
LANGUAGE_PYTHON = "python"
# 后续扩展: LANGUAGE_JAVA, LANGUAGE_GO ...

# Ingestion status
STATUS_CANDIDATE = "candidate"
STATUS_CONFIRMED = "confirmed"
STATUS_INGESTED = "ingested"

# LLM hypothesis error kind
ERROR_KIND_PARAM = "param_error"
ERROR_KIND_STATE = "state_error"
ERROR_KIND_EXTERNAL = "external_dep_error"
ERROR_KIND_LOGIC = "logic_error"
ERROR_KIND_UNKNOWN = "unknown"

# AuditLog action（M2/M3/M4 写操作时统一引用，避免字符串硬编码不一致）
ACTION_INGEST_REPO = "ingest_repo"
ACTION_CONFIRM_INGESTION = "confirm_ingestion"
ACTION_REVOKE_INGESTION = "revoke_ingestion"
ACTION_QUERY = "query"
ACTION_LIST_CANDIDATES = "list_candidates"
ACTION_GET_CALL_CONTEXT = "get_call_context"
ACTION_FORCE_RELEASE_LOCK = "force_release_lock"  # admin only
# F002 M2 新增 action 常量
ACTION_PHASE1_ANALYZE = "phase1_analyze"
ACTION_PHASE2_DEEP_ANALYZE = "phase2_deep_analyze"
ACTION_ARCHIVE_REPORT = "archive_report"

# F002 M2 AnalysisReport.ingestion_status
STATUS_DRAFT = "draft"
STATUS_ARCHIVED = "archived"

# F002 M2 Anomaly.severity
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"
SEVERITY_CRITICAL = "critical"

# F002 M2 ErrorChain.relation
RELATION_CAUSAL = "causal"
RELATION_CORRELATION = "correlation"
RELATION_PROPAGATION = "propagation"

