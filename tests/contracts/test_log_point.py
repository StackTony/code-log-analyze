"""数据契约测试 — 字段、类型、枚举常量。"""
from __future__ import annotations

from datetime import UTC, datetime

from packages.contracts.audit import AuditLog
from packages.contracts.enums import (
    ACTION_CONFIRM_INGESTION,
    ACTION_FORCE_RELEASE_LOCK,
    ACTION_GET_CALL_CONTEXT,
    ACTION_INGEST_REPO,
    ACTION_LIST_CANDIDATES,
    ACTION_QUERY,
    ACTION_REVOKE_INGESTION,
    ERROR_KIND_LOGIC,
    ERROR_KIND_PARAM,
    ERROR_KIND_UNKNOWN,
    LANGUAGE_C,
    LANGUAGE_PYTHON,
    STATUS_CANDIDATE,
    STATUS_CONFIRMED,
    STATUS_INGESTED,
)
from packages.contracts.log_point import (
    CallContext,
    CaseRef,
    LLMHypothesis,
    LogPoint,
    RepoIngestLock,
)


def test_log_point_roundtrip() -> None:
    lp = LogPoint(
        id="lp-1",
        repo_id="repo-1",
        git_commit_sha="abc123",
        extractor_version="1.0.0",
        file_path="src/app.py",
        function_signature="def login(uid: str) -> bool",
        line_start=10,
        line_end=12,
        language=LANGUAGE_PYTHON,
        log_level="INFO",
        log_message_template="User {uid} logged in",
        log_message_variables=["uid"],
        framework_hint="logging",
        confidence_score=1.0,
        enclosing_class=None,
        call_chain_to_entry=["api_handler", "auth_middleware", "login"],
        enclosing_community="auth",
        evidence_refs=[],
        llm_hypothesis=None,
        occurrence_count=1,
        is_top_n=True,
        ingestion_status=STATUS_CANDIDATE,
        first_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert lp.language == "python"
    assert lp.confidence_score == 1.0
    assert lp.ingestion_status == "candidate"


def test_llm_hypothesis_includes_prompt_hash_and_error_kind() -> None:
    h = LLMHypothesis(
        summary="uid 可能为空",
        possible_causes=["参数未校验"],
        error_kind=ERROR_KIND_PARAM,
        suggested_check="检查 uid 是否 None",
        model_name="gpt-4",
        prompt_hash="v1-sha256-abc",
        generated_at=datetime(2026, 7, 24, tzinfo=UTC),
    )
    assert h.error_kind == "param_error"
    assert len(h.possible_causes) == 1


def test_case_ref_includes_resolution_fields() -> None:
    c = CaseRef(
        case_id="case-1",
        repo_id="repo-1",
        file_path="src/app.py",
        function_signature="def login(uid)",
        log_template="User {uid} logged in",
        resolved_at=datetime(2026, 7, 24, tzinfo=UTC),
        resolution_summary="加 uid 非空校验",
        resolution_diff_url="https://git.example.com/repo/-/merge_requests/1.diff",
    )
    assert c.resolution_summary
    assert c.resolution_diff_url is not None


def test_call_context_shape() -> None:
    ctx = CallContext(
        function_signature="def login(uid)",
        callers=["def api_handler()"],
        callees=["_verify_token"],
        enclosing_community="auth",
        related_log_points=[],
        evidence_refs=[],
    )
    assert ctx.callers == ["def api_handler()"]


def test_repo_ingest_lock_status_running() -> None:
    lock = RepoIngestLock(
        repo_id="repo-1",
        status="running",
        started_at=datetime(2026, 7, 24, tzinfo=UTC),
        finished_at=None,
        error_msg=None,
        ingester="user-1",
    )
    assert lock.status == "running"
    assert lock.finished_at is None


def test_audit_log_has_action_constants() -> None:
    a = AuditLog(
        id="audit-1",
        actor="user-1",
        action=ACTION_INGEST_REPO,
        target_repo_id="repo-1",
        target_log_point_ids=None,
        timestamp=datetime(2026, 7, 24, tzinfo=UTC),
        extra={"incremental": False},
    )
    assert a.action == "ingest_repo"
    # 所有 ACTION_* 常量都该是字符串
    for action in [
        ACTION_INGEST_REPO, ACTION_CONFIRM_INGESTION, ACTION_REVOKE_INGESTION,
        ACTION_QUERY, ACTION_LIST_CANDIDATES, ACTION_GET_CALL_CONTEXT,
        ACTION_FORCE_RELEASE_LOCK,
    ]:
        assert isinstance(action, str)


def test_language_and_status_constants() -> None:
    assert LANGUAGE_C == "c"
    assert LANGUAGE_PYTHON == "python"
    assert STATUS_CANDIDATE == "candidate"
    assert STATUS_CONFIRMED == "confirmed"
    assert STATUS_INGESTED == "ingested"
    assert ERROR_KIND_LOGIC == "logic_error"
    assert ERROR_KIND_UNKNOWN == "unknown"
