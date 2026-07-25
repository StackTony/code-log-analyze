"""Pydantic v2 schema 测试 — strict 模式 + 字段对齐 dataclass（spec §九 + AC-6）。"""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from packages.api.schemas.call_context import CallContextAPI, CaseRefAPI
from packages.api.schemas.common import ErrorResponse, HealthResponse, ReadyResponse
from packages.api.schemas.confirm import (
    CallContextRequest,
    ConfirmRequest,
    RevokeRequest,
)
from packages.api.schemas.ingest import IngestRequest, IngestResponse
from packages.api.schemas.log_point import LLMHypothesisAPI, LogPointAPI
from packages.contracts.log_point import CallContext, CaseRef, LLMHypothesis, LogPoint

# --- common.py ---

def test_error_response_strict() -> None:
    """ErrorResponse 强制 strict + extra=forbid。"""
    r = ErrorResponse(code="M1_INVALID_PATH", message="bad path", details={"key": "v"})
    assert r.code == "M1_INVALID_PATH"
    with pytest.raises(ValidationError):
        ErrorResponse.model_validate({"code": "X", "message": "Y", "details": {}, "extra_field": "forbidden"})


def test_health_response() -> None:
    r = HealthResponse(status="ok")
    assert r.status == "ok"


def test_ready_response() -> None:
    r = ReadyResponse(status="ready")
    assert r.status == "ready"
    r2 = ReadyResponse(status="not_ready", reason="db_unavailable")
    assert r2.reason == "db_unavailable"


# --- ingest.py ---

def test_ingest_request_local_path() -> None:
    r = IngestRequest(local_path="/tmp/foo", ingester={"id": "u1", "name": "alice"})
    assert r.local_path == "/tmp/foo"
    assert r.ingester.id == "u1"
    assert r.github_url is None


def test_ingest_request_github_url() -> None:
    r = IngestRequest(github_url="https://github.com/x/y", ingester={"id": "u1", "name": "alice"})
    assert r.github_url == "https://github.com/x/y"
    assert r.local_path is None


def test_ingest_request_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        IngestRequest.model_validate({
            "local_path": "/x",
            "ingester": {"id": "u", "name": "n"},
            "extra": "forbidden",
        })


def test_ingest_request_requires_at_least_one_source() -> None:
    with pytest.raises(ValidationError):
        IngestRequest.model_validate({"ingester": {"id": "u", "name": "n"}})


def test_ingest_response() -> None:
    r = IngestResponse(repo_id="repo-abc")
    assert r.repo_id == "repo-abc"


# --- log_point.py ---

def test_log_point_api_from_dataclass() -> None:
    """from_attributes=True 让 LogPoint dataclass 直接转 LogPointAPI。"""
    now = datetime.now(UTC)
    lp = LogPoint(
        id="lp-1", repo_id="repo-1", git_commit_sha="sha", extractor_version="1.0.0",
        file_path="src/foo.py", function_signature="def bar() -> None",
        line_start=10, line_end=12, language="python", log_level="INFO",
        log_message_template="hello {}", log_message_variables=["name"],
        framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
        first_seen_at=now, last_seen_at=now,
        occurrence_count=1, is_top_n=True, ingestion_status="candidate",
    )
    api = LogPointAPI.model_validate(lp, from_attributes=True)
    assert api.id == "lp-1"
    assert api.file_path == "src/foo.py"
    assert api.first_seen_at == now
    assert api.llm_hypothesis is None


def test_log_point_api_fields_match_dataclass() -> None:
    """AC-6: schema 字段与 LogPoint dataclass 对齐。"""
    dataclass_fields = {f.name for f in dataclasses.fields(LogPoint)}
    schema_fields = set(LogPointAPI.model_fields.keys())
    # dataclass 有 repo_id 但 schema 必须有；schema 不含 evidence_refs 是 list[dict]（与 dataclass list[CaseRef] 不同）
    # 核心字段全覆盖（除 evidence_refs 类型不同，但字段名相同）
    assert dataclass_fields == schema_fields


def test_llm_hypothesis_api_from_dataclass() -> None:
    now = datetime.now(UTC)
    hyp = LLMHypothesis(
        summary="test", possible_causes=["a"], error_kind="unknown",
        suggested_check=None, model_name="gpt-4", prompt_hash="h",
        generated_at=now,
    )
    api = LLMHypothesisAPI.model_validate(hyp, from_attributes=True)
    assert api.summary == "test"
    assert api.possible_causes == ["a"]


# --- call_context.py ---

def test_call_context_api_from_dataclass() -> None:
    now = datetime.now(UTC)
    lp = LogPoint(
        id="lp-1", repo_id="repo-1", git_commit_sha="s", extractor_version="v",
        file_path="a", function_signature="b", line_start=1, line_end=2,
        language="python", log_level="INFO", log_message_template="t",
        log_message_variables=[], framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
        first_seen_at=now, last_seen_at=now,
    )
    ctx = CallContext(
        function_signature="def foo()",
        callers=["a"], callees=["b"], enclosing_community="C",
        related_log_points=[lp], evidence_refs=[],
    )
    api = CallContextAPI.model_validate(ctx, from_attributes=True)
    assert api.function_signature == "def foo()"
    assert api.callers == ["a"]
    assert len(api.related_log_points) == 1


def test_caseref_api_from_dataclass() -> None:
    now = datetime.now(UTC)
    c = CaseRef(
        case_id="c1", repo_id="r1", file_path="a", function_signature="f",
        log_template="t", resolved_at=now, resolution_summary="s",
        resolution_diff_url=None,
    )
    api = CaseRefAPI.model_validate(c, from_attributes=True)
    assert api.case_id == "c1"


# --- confirm.py ---

def test_confirm_request() -> None:
    r = ConfirmRequest(log_point_ids=["lp-1", "lp-2"], confirmer="alice")
    assert r.log_point_ids == ["lp-1", "lp-2"]
    assert r.confirmer == "alice"


def test_confirm_request_rejects_empty_list() -> None:
    with pytest.raises(ValidationError):
        ConfirmRequest(log_point_ids=[], confirmer="alice")


def test_revoke_request() -> None:
    r = RevokeRequest(log_point_ids=["lp-1"], revoker="alice")
    assert r.revoker == "alice"


def test_call_context_request() -> None:
    """POST body 形式传 function_signature（云长 OQ-1 修订）。"""
    r = CallContextRequest(function_signature="def foo(uid: str) -> bool")
    assert r.function_signature == "def foo(uid: str) -> bool"
