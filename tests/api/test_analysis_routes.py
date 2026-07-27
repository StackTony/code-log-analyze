"""F002 M2 — HTTP routes 测试（spec §六 + AC-12 + AC-13）。

5 个端点：
  - POST /analyze
  - POST /analyze/deep
  - GET /reports/{report_id}
  - GET /reports/{report_id}/deep-analyses
  - POST /reports/{report_id}/archive

测试策略：
  - 用 FastAPI dependency_overrides 注入 mock LogAnalysisService，避免触发真实 LLM 调用
  - 端到端流程已在 tests/m2/test_log_analysis_service.py 覆盖
  - 本测试专注 HTTP 语义：状态码 + response schema + 错误码前缀 M2_*（AC-13）

AC-12: status code + response schema
AC-13: M2_* 错误码前缀
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import packages.api.deps as deps_mod
from packages.api.app import app
from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.enums import (
    STATUS_ARCHIVED,
    STATUS_DRAFT,
)
from packages.contracts.log_point import CaseRef


# ---- Fixtures ----

@pytest.fixture()
def mock_service() -> MagicMock:
    """Mock LogAnalysisService — 所有方法为 AsyncMock/MagicMock。"""
    m = MagicMock()
    m.analyze_logs = AsyncMock()
    m.deep_analyze = AsyncMock()
    m.get_report = MagicMock()
    m.list_deep_analyses = MagicMock()
    m.archive_report = MagicMock()
    return m


@pytest.fixture()
def client(mock_service: MagicMock) -> TestClient:
    """TestClient with dependency override — 注入 mock_service。"""
    def _override():
        return mock_service
    app.dependency_overrides[deps_mod.get_log_analysis_service] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def sample_report() -> AnalysisReport:
    return AnalysisReport(
        id="rpt-test-1",
        repo_id="repo-1",
        log_source="text",
        log_line_count=2,
        window_start=datetime(2026, 7, 27, 8, 30, tzinfo=UTC),
        window_end=datetime(2026, 7, 27, 8, 31, tzinfo=UTC),
        model_name="claude-haiku",
        prompt_hash="hash123",
        system_summary="system had errors",
        anomaly_localization=[
            Anomaly(
                line_ids=["le-1"], severity="error", module="auth",
                summary="auth failures", evidence_snippets=["raw"],
            ),
        ],
        error_correlation=[
            ErrorChain(
                chain_id="c1", line_ids_ordered=["le-1"],
                relation="causal", summary="chain", confidence_score=0.8,
            ),
        ],
        generated_at=datetime(2026, 7, 27, 8, 31, tzinfo=UTC),
        duration_seconds=1.2,
        token_usage=TokenUsage(
            prompt_tokens=100, completion_tokens=50, total_cost_usd=0.02,
        ),
        ingestion_status=STATUS_DRAFT,
    )


@pytest.fixture()
def sample_deep_record() -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id="da-test-1",
        report_id="rpt-test-1",
        line_ids=["le-1"],
        log_point_ids=["lp-1"],
        call_contexts=[],
        root_cause_hypothesis="db pool exhausted",
        fix_suggestion="increase pool size",
        related_evidence=[
            CaseRef(
                case_id="case-1", repo_id="repo-1",
                file_path="app/db.py", function_signature="def connect()",
                log_template="db connection failed",
                resolved_at=datetime(2026, 7, 1, tzinfo=UTC),
                resolution_summary="fixed by retry",
                resolution_diff_url="https://example.com/diff/1",
            ),
        ],
        model_name="claude-opus-4",
        prompt_hash="hash456",
        iteration=1,
        parent_record_id=None,
        generated_at=datetime(2026, 7, 27, 8, 35, tzinfo=UTC),
        token_usage=TokenUsage(
            prompt_tokens=200, completion_tokens=100, total_cost_usd=0.05,
        ),
    )


# ---- POST /analyze ----

def test_post_analyze_returns_201(
    client: TestClient, mock_service: MagicMock, sample_report: AnalysisReport,
) -> None:
    """AC-12: POST /analyze 成功返回 201 + AnalysisReportAPI schema。"""
    mock_service.analyze_logs.return_value = sample_report

    r = client.post("/analyze", json={
        "log_text": "2026-07-27 ERROR connection failed",
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "rpt-test-1"
    assert body["repo_id"] == "repo-1"
    assert body["log_source"] == "text"
    assert body["log_line_count"] == 2
    assert body["model_name"] == "claude-haiku"
    assert body["system_summary"] == "system had errors"
    assert len(body["anomaly_localization"]) == 1
    assert body["anomaly_localization"][0]["severity"] == "error"
    assert len(body["error_correlation"]) == 1
    assert body["error_correlation"][0]["confidence_score"] == 0.8
    assert body["token_usage"]["prompt_tokens"] == 100
    assert body["ingestion_status"] == "draft"


def test_post_analyze_with_file_path(
    client: TestClient, mock_service: MagicMock, sample_report: AnalysisReport,
) -> None:
    """log_file_path 作为日志来源。"""
    mock_service.analyze_logs.return_value = sample_report

    r = client.post("/analyze", json={
        "log_file_path": "/var/log/app.log",
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 201


def test_post_analyze_with_repo_id(
    client: TestClient, mock_service: MagicMock, sample_report: AnalysisReport,
) -> None:
    """带 repo_id + window_hours 覆盖。"""
    mock_service.analyze_logs.return_value = sample_report

    r = client.post("/analyze", json={
        "log_text": "log text",
        "analyzer": {"id": "u1", "name": "alice"},
        "repo_id": "repo-42",
        "window_hours": 48,
    })
    assert r.status_code == 201


def test_post_analyze_rejects_missing_all_sources(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-13: 三字段都缺 → 400 + M2_ANALYZE_NO_SOURCE 错误码。"""
    r = client.post("/analyze", json={
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "M2_ANALYZE_NO_SOURCE"
    assert "log_text" in body["message"]


def test_post_analyze_rejects_extra_field(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """strict + extra=forbid 拒绝未知字段（422）。"""
    r = client.post("/analyze", json={
        "log_text": "text",
        "analyzer": {"id": "u1", "name": "alice"},
        "unknown_field": "forbidden",
    })
    assert r.status_code == 422


def test_post_analyze_handles_invalid_source_value_error(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-13: LogSource.resolve_text 抛 ValueError → 400 + M2_ANALYZE_INVALID_SOURCE。"""
    mock_service.analyze_logs.side_effect = ValueError("log source file not found: /x.log")

    r = client.post("/analyze", json={
        "log_file_path": "/x.log",
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "M2_ANALYZE_INVALID_SOURCE"


# ---- POST /analyze/deep ----

def test_post_deep_analyze_returns_201(
    client: TestClient, mock_service: MagicMock,
    sample_deep_record: DeepAnalysisRecord,
) -> None:
    """AC-12: POST /analyze/deep 成功返回 201 + DeepAnalysisAPI schema。"""
    mock_service.deep_analyze.return_value = sample_deep_record

    r = client.post("/analyze/deep", json={
        "report_id": "rpt-test-1",
        "line_ids": ["le-1"],
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 201
    body = r.json()
    assert body["id"] == "da-test-1"
    assert body["report_id"] == "rpt-test-1"
    assert body["line_ids"] == ["le-1"]
    assert body["log_point_ids"] == ["lp-1"]
    assert body["root_cause_hypothesis"] == "db pool exhausted"
    assert body["fix_suggestion"] == "increase pool size"
    assert len(body["related_evidence"]) == 1
    assert body["related_evidence"][0]["case_id"] == "case-1"
    assert body["iteration"] == 1
    assert body["parent_record_id"] is None
    assert body["token_usage"]["completion_tokens"] == 100


def test_post_deep_analyze_rejects_empty_line_ids(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """空 line_ids 返回 422（min_length=1）。"""
    r = client.post("/analyze/deep", json={
        "report_id": "rpt-1",
        "line_ids": [],
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 422


def test_post_deep_analyze_404_when_report_missing(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-13: report_id 不存在 → 404 + M2_DEEP_ANALYZE_NOT_FOUND。"""
    mock_service.deep_analyze.side_effect = ValueError("phase1 report not found: rpt-x")

    r = client.post("/analyze/deep", json={
        "report_id": "rpt-x",
        "line_ids": ["le-1"],
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "M2_DEEP_ANALYZE_NOT_FOUND"


def test_post_deep_analyze_409_when_iteration_exceeded(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-13 + AC-11: IterationLimitExceeded → 409 + M2_DEEP_ANALYZE_ITERATION_LIMIT + details。"""
    from packages.m2.deep_analyzer import IterationLimitExceeded

    exc = IterationLimitExceeded(
        current=6, limit=5, report_id="rpt-1",
    )
    mock_service.deep_analyze.side_effect = exc

    r = client.post("/analyze/deep", json={
        "report_id": "rpt-1",
        "line_ids": ["le-1"],
        "analyzer": {"id": "u1", "name": "alice"},
    })
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "M2_DEEP_ANALYZE_ITERATION_LIMIT"
    assert "details" in body
    assert body["details"]["current"] == 6
    assert body["details"]["limit"] == 5
    assert body["details"]["report_id"] == "rpt-1"


# ---- GET /reports/{report_id} ----

def test_get_report_returns_200(
    client: TestClient, mock_service: MagicMock, sample_report: AnalysisReport,
) -> None:
    """AC-12: GET /reports/{id} 成功返回 200 + AnalysisReportAPI。"""
    mock_service.get_report.return_value = sample_report

    r = client.get("/reports/rpt-test-1")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "rpt-test-1"
    assert body["system_summary"] == "system had errors"


def test_get_report_404_when_missing(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-13: report 不存在 → 404 + M2_REPORT_NOT_FOUND。"""
    mock_service.get_report.return_value = None

    r = client.get("/reports/rpt-missing")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "M2_REPORT_NOT_FOUND"


# ---- GET /reports/{report_id}/deep-analyses ----

def test_list_deep_analyses_returns_200(
    client: TestClient, mock_service: MagicMock,
    sample_deep_record: DeepAnalysisRecord,
) -> None:
    """AC-12: GET /reports/{id}/deep-analyses 成功返回 200 + list[DeepAnalysisAPI]。"""
    mock_service.list_deep_analyses.return_value = [sample_deep_record]

    r = client.get("/reports/rpt-test-1/deep-analyses")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 1
    assert body[0]["id"] == "da-test-1"
    assert body[0]["iteration"] == 1


def test_list_deep_analyses_with_line_id_filter(
    client: TestClient, mock_service: MagicMock,
    sample_deep_record: DeepAnalysisRecord,
) -> None:
    """?line_id= 过滤。"""
    mock_service.list_deep_analyses.return_value = [sample_deep_record]

    r = client.get("/reports/rpt-test-1/deep-analyses?line_id=le-1")
    assert r.status_code == 200
    # 验证 service 被传入 line_id 参数
    mock_service.list_deep_analyses.assert_called_once_with(
        "rpt-test-1", line_id="le-1",
    )


def test_list_deep_analyses_empty(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """无 deep analysis 记录返回空列表。"""
    mock_service.list_deep_analyses.return_value = []

    r = client.get("/reports/rpt-no-deep/deep-analyses")
    assert r.status_code == 200
    body = r.json()
    assert body == []


# ---- POST /reports/{report_id}/archive ----

def test_archive_report_returns_204(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-12: POST /reports/{id}/archive 成功返回 204 No Content。"""
    r = client.post(
        "/reports/rpt-test-1/archive",
        params={"archiver_id": "u1", "archiver_name": "alice"},
    )
    assert r.status_code == 204
    assert r.content == b""
    mock_service.archive_report.assert_called_once()


def test_archive_report_404_when_missing(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """AC-13: 归档不存在的 report → 404 + M2_REPORT_NOT_FOUND。"""
    mock_service.archive_report.side_effect = ValueError("report not found: rpt-x")

    r = client.post(
        "/reports/rpt-x/archive",
        params={"archiver_id": "u1", "archiver_name": "alice"},
    )
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "M2_REPORT_NOT_FOUND"


def test_archive_report_requires_archiver_query_params(
    client: TestClient, mock_service: MagicMock,
) -> None:
    """缺 archiver_id / archiver_name 查询参数返回 422。"""
    r = client.post("/reports/rpt-test-1/archive")
    assert r.status_code == 422
