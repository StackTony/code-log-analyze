"""Mapper 测试 — dataclass → Pydantic 转换（spec §十 + AC-12）。"""
from __future__ import annotations

from datetime import UTC, datetime

from packages.api.mappers.call_context import call_context_to_response
from packages.api.mappers.log_point import log_point_to_response
from packages.api.schemas.call_context import CallContextAPI
from packages.api.schemas.log_point import LogPointAPI
from packages.contracts.log_point import CallContext, CaseRef, LLMHypothesis, LogPoint


def _make_log_point() -> LogPoint:
    now = datetime.now(UTC)
    return LogPoint(
        id="lp-1", repo_id="repo-1", git_commit_sha="sha", extractor_version="1.0.0",
        file_path="src/foo.py", function_signature="def bar()",
        line_start=10, line_end=12, language="python", log_level="INFO",
        log_message_template="hi {}", log_message_variables=["name"],
        framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community="C",
        first_seen_at=now, last_seen_at=now,
        occurrence_count=2, is_top_n=True, ingestion_status="candidate",
    )


def test_log_point_to_response_full() -> None:
    lp = _make_log_point()
    api = log_point_to_response(lp)
    assert isinstance(api, LogPointAPI)
    assert api.id == "lp-1"
    assert api.file_path == "src/foo.py"
    assert api.llm_hypothesis is None


def test_log_point_to_response_with_llm_hypothesis() -> None:
    lp = _make_log_point()
    now = datetime.now(UTC)
    lp.llm_hypothesis = LLMHypothesis(
        summary="s", possible_causes=["a"], error_kind="unknown",
        suggested_check=None, model_name="gpt-4", prompt_hash="h",
        generated_at=now,
    )
    api = log_point_to_response(lp)
    assert api.llm_hypothesis is not None
    assert api.llm_hypothesis.summary == "s"


def test_log_point_to_response_with_evidence_refs() -> None:
    lp = _make_log_point()
    now = datetime.now(UTC)
    lp.evidence_refs = [CaseRef(
        case_id="c1", repo_id="r1", file_path="a", function_signature="f",
        log_template="t", resolved_at=now, resolution_summary="s",
        resolution_diff_url=None,
    )]
    api = log_point_to_response(lp)
    assert len(api.evidence_refs) == 1
    assert api.evidence_refs[0]["case_id"] == "c1"


def test_call_context_to_response() -> None:
    lp = _make_log_point()
    ctx = CallContext(
        function_signature="def foo()", callers=["a"], callees=["b"],
        enclosing_community="C", related_log_points=[lp], evidence_refs=[],
    )
    api = call_context_to_response(ctx)
    assert isinstance(api, CallContextAPI)
    assert api.function_signature == "def foo()"
    assert len(api.related_log_points) == 1
    assert api.related_log_points[0].id == "lp-1"
