"""F002 M2 — Storage models + migration 测试（spec §三 + AC-16）。

验证三张表（analysis_report / deep_analysis / log_entry）：
  1. 复用 M1 Base，create_all 一把建 7 张表（M1 4 + M2 3）
  2. AC-16 P0 持久化：所有表无 TTL 字段，默认持久化
  3. AC-18 字节级稳定：M1 已有 4 张表无新增列
  4. dataclass ↔ JSON 转换在 service 层（model 层只存 JSON Text）
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from packages.m1.storage.models import Base
from packages.m2.storage.models import (
    AnalysisReportModel,
    DeepAnalysisModel,
    LogEntryModel,
)


@pytest.fixture()
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


class TestSchema:
    """表结构 + AC-16 P0 持久化验证。"""

    def test_all_seven_tables_created(self, engine) -> None:
        """create_all 一把建 7 张表（M1 4 + M2 3）。"""
        insp = inspect(engine)
        tables = set(insp.get_table_names())
        expected = {
            # M1 已有 4 张
            "log_point", "candidate_staging", "repo_ingest_lock", "audit_log",
            # M2 新增 3 张
            "analysis_report", "deep_analysis", "log_entry",
        }
        assert expected.issubset(tables), f"missing: {expected - tables}"

    def test_analysis_report_table_no_ttl_field(self, engine) -> None:
        """AC-16: analysis_report 表无 TTL 字段。"""
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("analysis_report")}
        assert "ttl" not in cols
        assert "expires_at" not in cols
        assert "expires_at_ts" not in cols

    def test_deep_analysis_table_no_ttl_field(self, engine) -> None:
        """AC-16: deep_analysis 表无 TTL 字段。"""
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("deep_analysis")}
        assert "ttl" not in cols
        assert "expires_at" not in cols

    def test_log_entry_table_no_ttl_field(self, engine) -> None:
        """AC-16: log_entry 表无 TTL 字段。"""
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("log_entry")}
        assert "ttl" not in cols
        assert "expires_at" not in cols

    def test_m1_log_point_unchanged_ac18(self, engine) -> None:
        """AC-18: M1 log_point 表无新增列（字节级稳定）。

        M1 spec §三 L100-L181 列定义 23 字段，M2 实施不动。
        """
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("log_point")}
        expected_m1_cols = {
            "id", "repo_id", "git_commit_sha", "extractor_version",
            "file_path", "function_signature", "line_start", "line_end",
            "language", "log_level", "log_message_template", "log_message_variables",
            "framework_hint", "confidence_score", "enclosing_class",
            "call_chain_to_entry", "enclosing_community", "evidence_refs_json",
            "llm_hypothesis_json", "occurrence_count", "is_top_n",
            "ingestion_status", "first_seen_at", "last_seen_at",
        }
        assert cols == expected_m1_cols, (
            f"M1 log_point table changed (AC-18 violation): "
            f"extra={cols - expected_m1_cols}, missing={expected_m1_cols - cols}"
        )

    def test_m1_candidate_staging_unchanged_ac18(self, engine) -> None:
        """AC-18: M1 candidate_staging 表无新增列。"""
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("candidate_staging")}
        expected_m1_cols = {
            "id", "repo_id", "git_commit_sha", "extractor_version",
            "file_path", "function_signature", "line_start", "line_end",
            "language", "log_level", "log_message_template",
            "log_message_variables_json", "framework_hint", "confidence_score",
            "enclosing_class", "call_chain_to_entry_json", "enclosing_community",
            "evidence_refs_json", "llm_hypothesis_json", "occurrence_count",
            "is_top_n", "ingestion_status", "first_seen_at", "last_seen_at",
        }
        assert cols == expected_m1_cols, (
            f"M1 candidate_staging changed (AC-18 violation): "
            f"extra={cols - expected_m1_cols}, missing={expected_m1_cols - cols}"
        )


class TestAnalysisReportModelCRUD:
    """AnalysisReportModel 基础 CRUD（验证字段映射）。"""

    def test_insert_and_read(self, session: Session) -> None:
        """插入 + 查询完整字段。"""
        now = datetime(2026, 7, 27, 8, 30, 0, tzinfo=timezone.utc)
        model = AnalysisReportModel(
            id="rpt-1",
            repo_id="repo-1",
            log_source="app.log",
            log_line_count=1000,
            window_start=now,
            window_end=now,
            model_name="claude-haiku",
            prompt_hash="sha256:abc",
            system_summary="system ran normally",
            anomaly_localization_json="[]",
            error_correlation_json="[]",
            generated_at=now,
            duration_seconds=12.5,
            token_usage_json='{"prompt_tokens": 100, "completion_tokens": 50, "total_cost_usd": 0.02}',
            ingestion_status="draft",
        )
        session.add(model)
        session.commit()

        read = session.get(AnalysisReportModel, "rpt-1")
        assert read is not None
        assert read.repo_id == "repo-1"
        assert read.log_line_count == 1000
        assert read.system_summary == "system ran normally"
        assert read.ingestion_status == "draft"

    def test_repo_id_nullable_for_orphan_logs(self, session: Session) -> None:
        """repo_id 可空 — 日志无代码仓关联时为 None（spec §三）。"""
        model = AnalysisReportModel(
            id="rpt-orphan",
            repo_id=None,
            log_source="raw.log",
            log_line_count=10,
            model_name="m", prompt_hash="h",
            system_summary="x",
            generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            duration_seconds=0.1,
        )
        session.add(model)
        session.commit()

        read = session.get(AnalysisReportModel, "rpt-orphan")
        assert read is not None
        assert read.repo_id is None

    def test_default_ingestion_status_draft(self, session: Session) -> None:
        """新报告默认 ingestion_status=draft（spec §三 STATUS_*）。"""
        model = AnalysisReportModel(
            id="rpt-default", repo_id=None, log_source="x",
            log_line_count=0, model_name="m", prompt_hash="h",
            system_summary="x",
            generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            duration_seconds=0.1,
        )
        session.add(model)
        session.commit()

        read = session.get(AnalysisReportModel, "rpt-default")
        assert read is not None
        assert read.ingestion_status == "draft"


class TestDeepAnalysisModelCRUD:
    """DeepAnalysisModel 基础 CRUD + 迭代性字段。"""

    def test_insert_with_iteration_and_parent(self, session: Session) -> None:
        """iteration + parent_record_id 链。"""
        model = DeepAnalysisModel(
            id="da-1",
            report_id="rpt-1",
            line_ids_json='["line-1"]',
            log_point_ids_json='["lp-1"]',
            call_contexts_json="[]",
            root_cause_hypothesis="root cause v1",
            fix_suggestion="fix v1",
            related_evidence_json="[]",
            model_name="claude-opus-4",
            prompt_hash="sha256:abc",
            iteration=1,
            parent_record_id=None,
            generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            token_usage_json='{"prompt_tokens": 100, "completion_tokens": 50, "total_cost_usd": 0.02}',
        )
        session.add(model)
        session.commit()

        read = session.get(DeepAnalysisModel, "da-1")
        assert read is not None
        assert read.iteration == 1
        assert read.parent_record_id is None

    def test_iteration_chain(self, session: Session) -> None:
        """iteration=2 + parent_record_id 指向前次。"""
        session.add(DeepAnalysisModel(
            id="da-1", report_id="rpt-1",
            root_cause_hypothesis="v1", model_name="m", prompt_hash="h",
            iteration=1, parent_record_id=None,
            generated_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
        ))
        session.commit()

        session.add(DeepAnalysisModel(
            id="da-2", report_id="rpt-1",
            root_cause_hypothesis="v2 (refined)", model_name="m", prompt_hash="h2",
            iteration=2, parent_record_id="da-1",
            generated_at=datetime(2026, 7, 27, 1, 0, 0, tzinfo=timezone.utc),
        ))
        session.commit()

        read_v2 = session.get(DeepAnalysisModel, "da-2")
        assert read_v2.iteration == 2
        assert read_v2.parent_record_id == "da-1"


class TestLogEntryModelCRUD:
    """LogEntryModel 基础 CRUD。"""

    def test_insert_minimal(self, session: Session) -> None:
        """最小字段集（解析失败的日志条目：timestamp/level/template 全 None）。"""
        model = LogEntryModel(
            id="le-1",
            report_id=None,
            raw_text="unrecognized log line",
            timestamp=None, level=None,
            log_message_template=None,
            variables_json="{}",
            source_file=None, source_line=None,
        )
        session.add(model)
        session.commit()

        read = session.get(LogEntryModel, "le-1")
        assert read is not None
        assert read.timestamp is None
        assert read.level is None
        assert read.log_message_template is None

    def test_insert_full(self, session: Session) -> None:
        """完整字段（解析成功的日志条目）。"""
        ts = datetime(2026, 7, 27, 8, 30, 0, tzinfo=timezone.utc)
        model = LogEntryModel(
            id="le-2",
            report_id="rpt-1",
            raw_text="2026-07-27 08:30:00 INFO User 12345 logged in",
            timestamp=ts, level="INFO",
            log_message_template="User {var_0} logged in",
            variables_json='{"var_0": "12345"}',
            source_file="app.log", source_line=42,
        )
        session.add(model)
        session.commit()

        read = session.get(LogEntryModel, "le-2")
        # SQLite 不保留 tzinfo（postgres 保留），tz-tolerant 比较：
        # 比较时刻而非 datetime 对象本身
        assert read.timestamp is not None
        if read.timestamp.tzinfo is None:
            # SQLite 行：本地时间转 UTC 后比较
            assert read.timestamp.replace(tzinfo=timezone.utc) == ts
        else:
            assert read.timestamp == ts
        assert read.level == "INFO"
        assert read.source_line == 42
