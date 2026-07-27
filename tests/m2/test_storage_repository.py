"""F002 M2 — Storage Repository 测试（spec §三 + AC-16）。

验证 dataclass ↔ Model JSON 转换 mappers：
  - AnalysisReport ↔ AnalysisReportModel
  - DeepAnalysisRecord ↔ DeepAnalysisModel
  - LogEntry ↔ LogEntryModel

双向映射要求：
  - dataclass → model：复杂结构字段（Anomaly/ErrorChain/CallContext/CaseRef）
    序列化为 JSON Text
  - model → dataclass：JSON Text 反序列化为 dataclass
  - 双向必须可逆：dataclass → model → dataclass 等于原 dataclass
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.analysis_report import AnalysisReport, Anomaly, ErrorChain, TokenUsage
from packages.contracts.audit import AuditLog  # 仅 import 不用，验证 contracts 完整性
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import CallContext, CaseRef, LLMHypothesis, LogPoint
from packages.m1.storage.models import Base
from packages.m2.storage.models import (
    AnalysisReportModel,
    DeepAnalysisModel,
    LogEntryModel,
)
from packages.m2.storage.repository import (
    M2Repository,
    _analysis_report_to_model,
    _analysis_report_to_dataclass,
    _deep_analysis_to_model,
    _deep_analysis_to_dataclass,
    _log_entry_to_model,
    _log_entry_to_dataclass,
)


@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


def _make_token_usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=150, completion_tokens=80, total_cost_usd=0.025)


def _make_anomaly(line_ids: list[str], summary: str, severity: str = "error") -> Anomaly:
    return Anomaly(
        line_ids=line_ids, severity=severity, module="auth",
        summary=summary, evidence_snippets=["raw log line 1", "raw log line 2"],
    )


def _make_error_chain(chain_id: str, line_ids: list[str], relation: str = "causal") -> ErrorChain:
    return ErrorChain(
        chain_id=chain_id, line_ids_ordered=line_ids, relation=relation,
        summary="chain description", confidence_score=0.85,
    )


def _make_analysis_report(report_id: str = "rpt-1") -> AnalysisReport:
    now = datetime(2026, 7, 27, 8, 30, 0, tzinfo=timezone.utc)
    return AnalysisReport(
        id=report_id,
        repo_id="repo-1",
        log_source="app.log",
        log_line_count=100,
        window_start=now,
        window_end=now,
        model_name="claude-haiku",
        prompt_hash="sha256:abc",
        system_summary="system ran normally",
        anomaly_localization=[_make_anomaly(["line-1"], "auth spike")],
        error_correlation=[_make_error_chain("chain-1", ["line-1", "line-2"])],
        generated_at=now,
        duration_seconds=12.5,
        token_usage=_make_token_usage(),
        ingestion_status="draft",
    )


def _make_caseref(case_id: str = "case-1") -> CaseRef:
    return CaseRef(
        case_id=case_id, repo_id="repo-1", file_path="app/auth.py",
        function_signature="def login(uid)",
        log_template="User {uid} logged in",
        resolved_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        resolution_summary="fixed by adding retry",
        resolution_diff_url="https://example.com/diff/1",
    )


def _make_call_context(sig: str = "def login(uid)") -> CallContext:
    return CallContext(
        function_signature=sig,
        callers=["def handle_request()"],
        callees=["def check_credentials()"],
        enclosing_community="AuthModule",
        related_log_points=[],
        evidence_refs=[_make_caseref()],
    )


def _make_deep_analysis(record_id: str = "da-1", iteration: int = 1) -> DeepAnalysisRecord:
    return DeepAnalysisRecord(
        id=record_id,
        report_id="rpt-1",
        line_ids=["line-1", "line-2"],
        log_point_ids=["lp-1", "lp-2"],
        call_contexts=[_make_call_context()],
        root_cause_hypothesis="db pool exhausted",
        fix_suggestion="increase pool size to 20",
        related_evidence=[_make_caseref()],
        model_name="claude-opus-4",
        prompt_hash="sha256:xyz",
        iteration=iteration,
        parent_record_id=None if iteration == 1 else "da-1",
        generated_at=datetime(2026, 7, 27, 8, 30, 0, tzinfo=timezone.utc),
        token_usage=_make_token_usage(),
    )


def _make_log_entry(entry_id: str = "le-1") -> LogEntry:
    return LogEntry(
        line_id=entry_id,
        raw_text="2026-07-27 08:30:00 INFO User 12345 logged in",
        timestamp=datetime(2026, 7, 27, 8, 30, 0, tzinfo=timezone.utc),
        level="INFO",
        log_message_template="User {var_0} logged in",
        variables={"var_0": "12345"},
        source_file="app.log",
        source_line=42,
    )


# ---------------- AnalysisReport mappers ----------------

class TestAnalysisReportMapping:
    """AnalysisReport ↔ AnalysisReportModel 双向映射。"""

    def test_dataclass_to_model_serializes_complex_fields(self) -> None:
        """dataclass → model：Anomaly/ErrorChain/TokenUsage 序列化为 JSON。"""
        report = _make_analysis_report()
        model = _analysis_report_to_model(report)

        assert model.id == "rpt-1"
        assert model.repo_id == "repo-1"
        # JSON 字段已序列化
        anomaly_json = json.loads(model.anomaly_localization_json)
        assert len(anomaly_json) == 1
        assert anomaly_json[0]["summary"] == "auth spike"
        assert anomaly_json[0]["module"] == "auth"

        ec_json = json.loads(model.error_correlation_json)
        assert len(ec_json) == 1
        assert ec_json[0]["chain_id"] == "chain-1"
        assert ec_json[0]["confidence_score"] == 0.85

        tu = json.loads(model.token_usage_json)
        assert tu["prompt_tokens"] == 150
        assert tu["total_cost_usd"] == 0.025

    def test_model_to_dataclass_deserializes_complex_fields(self) -> None:
        """model → dataclass：JSON 反序列化为 dataclass。"""
        report = _make_analysis_report()
        model = _analysis_report_to_model(report)
        round_tripped = _analysis_report_to_dataclass(model)

        assert round_tripped.id == report.id
        assert round_tripped.repo_id == report.repo_id
        assert len(round_tripped.anomaly_localization) == 1
        assert round_tripped.anomaly_localization[0].summary == "auth spike"
        assert round_tripped.anomaly_localization[0].module == "auth"
        assert round_tripped.anomaly_localization[0].evidence_snippets == ["raw log line 1", "raw log line 2"]
        assert len(round_tripped.error_correlation) == 1
        assert round_tripped.error_correlation[0].chain_id == "chain-1"
        assert round_tripped.error_correlation[0].confidence_score == 0.85
        assert round_tripped.token_usage.prompt_tokens == 150
        assert round_tripped.ingestion_status == "draft"

    def test_dataclass_with_empty_lists(self) -> None:
        """空 anomaly/error_correlation 列表 round-trip。"""
        report = _make_analysis_report()
        report = AnalysisReport(
            id=report.id, repo_id=report.repo_id, log_source=report.log_source,
            log_line_count=report.log_line_count,
            window_start=report.window_start, window_end=report.window_end,
            model_name=report.model_name, prompt_hash=report.prompt_hash,
            system_summary="all good",
            anomaly_localization=[], error_correlation=[],
            generated_at=report.generated_at,
            duration_seconds=report.duration_seconds,
            token_usage=report.token_usage,
            ingestion_status=report.ingestion_status,
        )
        model = _analysis_report_to_model(report)
        round_tripped = _analysis_report_to_dataclass(model)
        assert round_tripped.anomaly_localization == []
        assert round_tripped.error_correlation == []

    def test_repo_id_none_passthrough(self) -> None:
        """repo_id=None round-trip。"""
        report = _make_analysis_report()
        # frozen dataclass，用 dataclasses.replace
        from dataclasses import replace
        report = replace(report, repo_id=None)
        model = _analysis_report_to_model(report)
        assert model.repo_id is None
        round_tripped = _analysis_report_to_dataclass(model)
        assert round_tripped.repo_id is None


# ---------------- DeepAnalysisRecord mappers ----------------

class TestDeepAnalysisMapping:
    """DeepAnalysisRecord ↔ DeepAnalysisModel 双向映射。"""

    def test_dataclass_to_model_serializes_call_contexts_evidence(self) -> None:
        """CallContext + CaseRef 序列化为 JSON。"""
        record = _make_deep_analysis()
        model = _deep_analysis_to_model(record)

        assert model.id == "da-1"
        assert model.report_id == "rpt-1"
        # line_ids / log_point_ids JSON
        assert json.loads(model.line_ids_json) == ["line-1", "line-2"]
        assert json.loads(model.log_point_ids_json) == ["lp-1", "lp-2"]

        # call_contexts JSON
        cc_list = json.loads(model.call_contexts_json)
        assert len(cc_list) == 1
        assert cc_list[0]["function_signature"] == "def login(uid)"
        assert cc_list[0]["callers"] == ["def handle_request()"]
        assert len(cc_list[0]["evidence_refs"]) == 1

        # related_evidence JSON
        ev_list = json.loads(model.related_evidence_json)
        assert len(ev_list) == 1
        assert ev_list[0]["case_id"] == "case-1"

        # root_cause_hypothesis + fix_suggestion 直接字段
        assert model.root_cause_hypothesis == "db pool exhausted"
        assert model.fix_suggestion == "increase pool size to 20"

        # iteration + parent_record_id
        assert model.iteration == 1
        assert model.parent_record_id is None

    def test_model_to_dataclass_deserializes(self) -> None:
        """model → dataclass：JSON 反序列化。"""
        record = _make_deep_analysis()
        model = _deep_analysis_to_model(record)
        round_tripped = _deep_analysis_to_dataclass(model)

        assert round_tripped.id == record.id
        assert round_tripped.report_id == record.report_id
        assert round_tripped.line_ids == ["line-1", "line-2"]
        assert round_tripped.log_point_ids == ["lp-1", "lp-2"]
        assert len(round_tripped.call_contexts) == 1
        assert round_tripped.call_contexts[0].function_signature == "def login(uid)"
        assert round_tripped.call_contexts[0].callers == ["def handle_request()"]
        assert round_tripped.call_contexts[0].evidence_refs[0].case_id == "case-1"
        assert round_tripped.root_cause_hypothesis == "db pool exhausted"
        assert round_tripped.fix_suggestion == "increase pool size to 20"
        assert len(round_tripped.related_evidence) == 1
        assert round_tripped.related_evidence[0].case_id == "case-1"
        assert round_tripped.iteration == 1
        assert round_tripped.parent_record_id is None

    def test_iteration_2_chain_preserved(self) -> None:
        """iteration=2 + parent_record_id round-trip。"""
        record = _make_deep_analysis(record_id="da-2", iteration=2)
        from dataclasses import replace
        record = replace(record, parent_record_id="da-1", root_cause_hypothesis="v2 refined")
        model = _deep_analysis_to_model(record)
        round_tripped = _deep_analysis_to_dataclass(model)
        assert round_tripped.iteration == 2
        assert round_tripped.parent_record_id == "da-1"
        assert round_tripped.root_cause_hypothesis == "v2 refined"


# ---------------- LogEntry mappers ----------------

class TestLogEntryMapping:
    """LogEntry ↔ LogEntryModel 双向映射。"""

    def test_dataclass_to_model(self) -> None:
        entry = _make_log_entry()
        model = _log_entry_to_model(entry, report_id="rpt-1")

        assert model.id == "le-1"
        assert model.report_id == "rpt-1"
        assert model.raw_text == entry.raw_text
        assert model.level == "INFO"
        assert model.log_message_template == "User {var_0} logged in"
        assert json.loads(model.variables_json) == {"var_0": "12345"}
        assert model.source_file == "app.log"
        assert model.source_line == 42

    def test_model_to_dataclass(self) -> None:
        entry = _make_log_entry()
        model = _log_entry_to_model(entry, report_id="rpt-1")
        round_tripped = _log_entry_to_dataclass(model)

        assert round_tripped.line_id == "le-1"
        assert round_tripped.raw_text == entry.raw_text
        assert round_tripped.level == "INFO"
        assert round_tripped.log_message_template == "User {var_0} logged in"
        assert round_tripped.variables == {"var_0": "12345"}
        assert round_tripped.source_file == "app.log"
        assert round_tripped.source_line == 42

    def test_minimal_log_entry_template_none(self) -> None:
        """未识别格式：timestamp/level/template 全 None，仍可 round-trip。"""
        entry = LogEntry(
            line_id="le-min", raw_text="random text",
            timestamp=None, level=None, log_message_template=None,
            variables={}, source_file=None, source_line=None,
        )
        model = _log_entry_to_model(entry, report_id=None)
        round_tripped = _log_entry_to_dataclass(model)
        assert round_tripped.timestamp is None
        assert round_tripped.level is None
        assert round_tripped.log_message_template is None
        assert round_tripped.variables == {}


# ---------------- M2Repository 集成 ----------------

class TestM2Repository:
    """M2Repository 写入 + 查询（spec §五）。"""

    def test_save_and_get_analysis_report(self, session: Session) -> None:
        repo = M2Repository(session)
        report = _make_analysis_report()
        repo.save_analysis_report(report)

        read = repo.get_analysis_report("rpt-1")
        assert read is not None
        assert read.id == "rpt-1"
        assert read.system_summary == "system ran normally"
        assert len(read.anomaly_localization) == 1
        assert read.anomaly_localization[0].summary == "auth spike"

    def test_get_analysis_report_returns_none_when_missing(self, session: Session) -> None:
        repo = M2Repository(session)
        assert repo.get_analysis_report("rpt-missing") is None

    def test_save_and_get_deep_analysis(self, session: Session) -> None:
        repo = M2Repository(session)
        record = _make_deep_analysis()
        repo.save_deep_analysis(record)

        read = repo.get_deep_analysis("da-1")
        assert read is not None
        assert read.root_cause_hypothesis == "db pool exhausted"
        assert read.iteration == 1

    def test_list_deep_analyses_by_report(self, session: Session) -> None:
        """按 report_id 查所有 deep_analysis，按 iteration 升序。"""
        repo = M2Repository(session)
        # 3 条记录：iteration 1/2/3
        from dataclasses import replace
        r1 = _make_deep_analysis(record_id="da-1", iteration=1)
        r2 = replace(_make_deep_analysis(record_id="da-2", iteration=2), parent_record_id="da-1")
        r3 = replace(_make_deep_analysis(record_id="da-3", iteration=3), parent_record_id="da-2")
        repo.save_deep_analysis(r1)
        repo.save_deep_analysis(r2)
        repo.save_deep_analysis(r3)

        results = repo.list_deep_analyses("rpt-1")
        assert len(results) == 3
        assert [r.iteration for r in results] == [1, 2, 3]

    def test_save_and_get_log_entries(self, session: Session) -> None:
        """批量保存 LogEntry + 按 report_id 查询。"""
        repo = M2Repository(session)
        entries = [_make_log_entry(entry_id=f"le-{i}") for i in range(3)]
        repo.save_log_entries(entries, report_id="rpt-1")

        results = repo.list_log_entries("rpt-1")
        assert len(results) == 3
        assert all(e.source_file == "app.log" for e in results)

    def test_archive_report_updates_status(self, session: Session) -> None:
        """archive_report 把 ingestion_status draft → archived。"""
        repo = M2Repository(session)
        report = _make_analysis_report()
        repo.save_analysis_report(report)

        archived = repo.archive_report("rpt-1")
        assert archived is True

        read = repo.get_analysis_report("rpt-1")
        assert read is not None
        assert read.ingestion_status == "archived"

    def test_archive_report_returns_false_when_missing(self, session: Session) -> None:
        repo = M2Repository(session)
        assert repo.archive_report("rpt-missing") is False
