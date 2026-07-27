"""F002 M2 — LogAnalysisService 测试（spec §四 + AC-3/9/15/19）。

验证 5 个 API 方法编排：
  - analyze_logs: LogParser → LogPointMatcher → ReportGenerator → M2Repository + audit
  - deep_analyze: M1 get_call_context + ReportGenerator 摘要 + DeepAnalyzer
    + HypothesisWriter 回写 + M2Repository + audit
  - get_report: M2Repository.get_analysis_report
  - list_deep_analyses: M2Repository.list_deep_analyses
  - archive_report: M2Repository.archive_report + audit

验证点：
  - AC-15: 每个写操作（analyze/deep_analyze/archive）写 audit_log
  - AC-19: 端到端 fixture：upload log → Phase 1 → 选 line → Phase 2 → 验证 M1 回写
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.audit import AuditLog
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.enums import (
    ACTION_ARCHIVE_REPORT,
    ACTION_PHASE1_ANALYZE,
    ACTION_PHASE2_DEEP_ANALYZE,
    STATUS_ARCHIVED,
    STATUS_DRAFT,
)
from packages.contracts.log_entry import LogEntry, LogSource
from packages.contracts.log_point import CallContext, CaseRef, LogPoint
from packages.m1.audit_log import AuditLogger
from packages.m1.log_sanitizer import LogSanitizer, SanitizerConfig
from packages.m1.llm_hypothesis_generator import LLMClient, RedisCache
from packages.m1.storage.models import Base
from packages.m1.unit_a_repo_registrar import User
from packages.m2.deep_analyzer import DeepAnalyzer, Phase2Config
from packages.m2.hypothesis_writer import HypothesisWriter
from packages.m2.log_analysis_service import LogAnalysisService
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher
from packages.m2.report_generator import Phase1Config, ReportGenerator
from packages.m2.storage.repository import M2Repository


# ---- Fixtures ----

@pytest.fixture()
def session():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture()
def audit(session: Session) -> AuditLogger:
    return AuditLogger(session)


@pytest.fixture()
def cache() -> MagicMock:
    c = MagicMock(spec=RedisCache)
    c.get.return_value = None
    return c


@pytest.fixture()
def llm_client_phase1() -> AsyncMock:
    """Phase 1 LLM mock — 返回固定三类信息 JSON。"""
    client = AsyncMock(spec=LLMClient)
    import json
    client.complete.return_value = json.dumps({
        "system_summary": "system had errors",
        "anomaly_localization": [{
            "line_ids": ["le-1"], "severity": "error", "module": "auth",
            "summary": "auth failures", "evidence_snippets": ["raw"],
        }],
        "error_correlation": [{
            "chain_id": "c1", "line_ids_ordered": ["le-1"],
            "relation": "causal", "summary": "chain", "confidence_score": 0.8,
        }],
        "token_usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_cost_usd": 0.02},
    })
    return client


@pytest.fixture()
def llm_client_phase2() -> AsyncMock:
    """Phase 2 LLM mock — 返回 root_cause + fix + evidence JSON。"""
    client = AsyncMock(spec=LLMClient)
    import json
    client.complete.return_value = json.dumps({
        "root_cause_hypothesis": "db pool exhausted",
        "fix_suggestion": "increase pool size",
        "related_evidence": [{
            "case_id": "case-1", "repo_id": "repo-1",
            "file_path": "app/db.py", "function_signature": "def connect()",
            "log_template": "db connection failed",
            "resolved_at": "2026-07-01T00:00:00+00:00",
            "resolution_summary": "fixed by retry",
            "resolution_diff_url": "https://example.com/diff/1",
        }],
        "token_usage": {"prompt_tokens": 200, "completion_tokens": 100, "total_cost_usd": 0.05},
    })
    return client


@pytest.fixture()
def sanitizer() -> LogSanitizer:
    return LogSanitizer(SanitizerConfig(
        enabled=True, patterns=["api_key", "password", "token"],
        replacement="[REDACTED_{kind}]",
    ))


@pytest.fixture()
def repository(session: Session) -> M2Repository:
    return M2Repository(session)


@pytest.fixture()
def log_point_index() -> MagicMock:
    """M1 LogPoint 主表索引 mock。"""
    from packages.m2.log_point_matcher import LogPointIndex
    idx = MagicMock(spec=LogPointIndex)
    idx.lookup_by_template_hash.return_value = None  # 默认未命中
    return idx


@pytest.fixture()
def m1_service() -> MagicMock:
    """M1 RepoLogGraphService mock — 用于 deep_analyze 调用 get_call_context
    和 update_log_point_hypothesis。"""
    m = MagicMock()
    m.get_call_context.return_value = CallContext(
        function_signature="def connect()",
        callers=["def handle()"], callees=["def ping()"],
        enclosing_community="DbModule",
        related_log_points=[], evidence_refs=[],
    )
    m.update_log_point_hypothesis.return_value = 1  # 默认成功更新 1 条
    return m


@pytest.fixture()
def service(
    session: Session, audit: AuditLogger, cache: MagicMock,
    llm_client_phase1: AsyncMock, llm_client_phase2: AsyncMock,
    sanitizer: LogSanitizer, repository: M2Repository,
    log_point_index: MagicMock, m1_service: MagicMock,
) -> LogAnalysisService:
    return LogAnalysisService(
        session=session,
        audit=audit,
        repository=repository,
        log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(log_point_index),
        report_generator=ReportGenerator(
            llm_client=llm_client_phase1, cache=cache, sanitizer=sanitizer,
            config=Phase1Config(model_name="claude-haiku", window_hours=24,
                                max_log_lines_per_call=200, cache_ttl_seconds=86400),
        ),
        deep_analyzer=DeepAnalyzer(
            llm_client=llm_client_phase2, cache=cache, sanitizer=sanitizer,
            config=Phase2Config(model_name="claude-opus-4", max_iterations=5,
                                cache_ttl_seconds=86400),
        ),
        hypothesis_writer=HypothesisWriter(m1_service=m1_service),
        m1_service=m1_service,
    )


@pytest.fixture()
def metrics_mock() -> MagicMock:
    """M2MetricsEmitter mock — 用于 service 集成测试。"""
    from packages.m2.metrics_emitter import M2MetricsEmitter
    m = MagicMock(spec=M2MetricsEmitter)
    return m


@pytest.fixture()
def service_with_metrics(
    session: Session, audit: AuditLogger, cache: MagicMock,
    llm_client_phase1: AsyncMock, llm_client_phase2: AsyncMock,
    sanitizer: LogSanitizer, repository: M2Repository,
    log_point_index: MagicMock, m1_service: MagicMock,
    metrics_mock: MagicMock,
) -> LogAnalysisService:
    """Service with metrics emitter attached（用于 AC-14 集成测试）。"""
    return LogAnalysisService(
        session=session,
        audit=audit,
        repository=repository,
        log_parser=LogParser(),
        log_point_matcher=LogPointMatcher(log_point_index),
        report_generator=ReportGenerator(
            llm_client=llm_client_phase1, cache=cache, sanitizer=sanitizer,
            config=Phase1Config(model_name="claude-haiku", window_hours=24,
                                max_log_lines_per_call=200, cache_ttl_seconds=86400),
        ),
        deep_analyzer=DeepAnalyzer(
            llm_client=llm_client_phase2, cache=cache, sanitizer=sanitizer,
            config=Phase2Config(model_name="claude-opus-4", max_iterations=5,
                                cache_ttl_seconds=86400),
        ),
        hypothesis_writer=HypothesisWriter(m1_service=m1_service),
        m1_service=m1_service,
        metrics=metrics_mock,
    )


# ---- analyze_logs (Phase 1) ----

class TestAnalyzeLogs:
    """Phase 1 全量分析端到端。"""

    async def test_analyze_logs_text_source(
        self, service: LogAnalysisService, repository: M2Repository,
        audit: AuditLogger, session: Session,
    ) -> None:
        """从文本日志生成 Phase 1 报告 + 持久化 + 写 audit_log。"""
        log_text = """
2026-07-27 08:30:00,123 INFO [auth] User 12345 logged in
2026-07-27 08:31:00,456 ERROR [db] connection failed to postgres://host:5432
"""
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )

        assert isinstance(report, AnalysisReport)
        assert report.system_summary == "system had errors"
        assert report.ingestion_status == STATUS_DRAFT
        assert report.log_line_count == 2

        # 持久化
        persisted = repository.get_analysis_report(report.id)
        assert persisted is not None
        assert persisted.system_summary == "system had errors"

        # LogEntry 持久化（关联 report_id）
        entries = repository.list_log_entries(report.id)
        assert len(entries) == 2

        # AC-15: 写 audit_log
        from packages.m1.storage.models import AuditLogModel
        audit_rows = session.query(AuditLogModel).filter_by(
            action=ACTION_PHASE1_ANALYZE
        ).all()
        assert len(audit_rows) == 1
        assert audit_rows[0].actor == "user-1"

    async def test_analyze_logs_with_repo_id(
        self, service: LogAnalysisService, log_point_index: MagicMock,
    ) -> None:
        """有 repo_id 时启用 M1 LogPoint 匹配。"""
        # 准备一个 LogPoint 让 matcher 命中
        from packages.m2.log_point_matcher import (
            LogPointIndex, _normalize_to_signature, _hash_signature,
        )
        log_point = LogPoint(
            id="lp-1", repo_id="repo-1", git_commit_sha="sha",
            extractor_version="v", file_path="app/auth.py",
            function_signature="def login()", line_start=10, line_end=10,
            language="python", log_level="INFO",
            log_message_template="User {uid} logged in",
            log_message_variables=["uid"], framework_hint="logging",
            confidence_score=0.9, enclosing_class=None,
            call_chain_to_entry=[], enclosing_community=None,
            first_seen_at=datetime(2026, 7, 27, tzinfo=UTC),
            last_seen_at=datetime(2026, 7, 27, tzinfo=UTC),
        )
        h = _hash_signature(_normalize_to_signature("User {uid} logged in"))
        log_point_index.lookup_by_template_hash.return_value = log_point

        log_text = "2026-07-27 08:30:00,123 INFO [auth] User 12345 logged in"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
            repo_id="repo-1",
        )
        assert report.repo_id == "repo-1"


# ---- deep_analyze (Phase 2) ----

class TestDeepAnalyze:
    """Phase 2 深入分析端到端 + M1 回写。"""

    async def test_deep_analyze_writes_record_and_calls_m1(
        self, service: LogAnalysisService, repository: M2Repository,
        m1_service: MagicMock, session: Session,
    ) -> None:
        """AC-19 端到端：先 analyze_logs，再 deep_analyze，验证 M1 回写。"""
        # Phase 1: 先有报告 + LogEntry 持久化
        log_text = "2026-07-27 08:30:00,123 ERROR [db] connection failed"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        # 取 line_id
        entries = repository.list_log_entries(report.id)
        assert len(entries) == 1
        line_id = entries[0].line_id

        # Phase 2: 选这一行深入分析
        record = await service.deep_analyze(
            report_id=report.id,
            line_ids=[line_id],
            analyzer=User(id="user-1", name="alice"),
        )
        assert isinstance(record, DeepAnalysisRecord)
        assert record.report_id == report.id
        assert record.iteration == 1
        assert record.parent_record_id is None
        assert record.root_cause_hypothesis == "db pool exhausted"
        assert record.fix_suggestion == "increase pool size"

        # 持久化
        persisted = repository.get_deep_analysis(record.id)
        assert persisted is not None

        # AC-9: M1 update_log_point_hypothesis 被调用（即使 log_point_ids 为空也不调用，
        # 但 deep_analyze 内应尝试回写——这里因 LogPointMatcher fallback 无匹配，
        # 不调用 M1）
        # 此测试中 LogPoint 未命中，故 m1_service.update_log_point_hypothesis 不应被调
        m1_service.update_log_point_hypothesis.assert_not_called()

        # AC-15: 写 audit_log
        from packages.m1.storage.models import AuditLogModel
        audit_rows = session.query(AuditLogModel).filter_by(
            action=ACTION_PHASE2_DEEP_ANALYZE
        ).all()
        assert len(audit_rows) == 1

    async def test_deep_analyze_with_log_point_match_calls_m1_writeback(
        self, service: LogAnalysisService, repository: M2Repository,
        m1_service: MagicMock, log_point_index: MagicMock,
    ) -> None:
        """AC-9 + AC-19: LogPoint 匹配命中时，deep_analyze 后回写 M1。"""
        from packages.m2.log_point_matcher import (
            _normalize_to_signature, _hash_signature,
        )
        # 一个匹配 "connection failed" 的 LogPoint
        log_point = LogPoint(
            id="lp-1", repo_id="repo-1", git_commit_sha="sha",
            extractor_version="v", file_path="app/db.py",
            function_signature="def connect()",
            line_start=10, line_end=10, language="python",
            log_level="ERROR",
            log_message_template="connection failed",
            log_message_variables=[], framework_hint="logging",
            confidence_score=0.9, enclosing_class=None,
            call_chain_to_entry=[], enclosing_community="DbModule",
            first_seen_at=datetime(2026, 7, 27, tzinfo=UTC),
            last_seen_at=datetime(2026, 7, 27, tzinfo=UTC),
        )
        h = _hash_signature(_normalize_to_signature("connection failed"))
        log_point_index.lookup_by_template_hash.return_value = log_point

        log_text = "2026-07-27 08:30:00,123 ERROR [db] connection failed"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
            repo_id="repo-1",
        )
        entries = repository.list_log_entries(report.id)
        line_id = entries[0].line_id

        record = await service.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="user-1", name="alice"),
        )

        # AC-9: M1 update_log_point_hypothesis 被调用
        m1_service.update_log_point_hypothesis.assert_called_once()
        call_kwargs = m1_service.update_log_point_hypothesis.call_args.kwargs
        assert call_kwargs["log_point_ids"] == ["lp-1"]
        assert call_kwargs["writer"] == "m2-phase2-deep-analyzer"

    async def test_deep_analyze_iteration_2_with_parent(
        self, service: LogAnalysisService, repository: M2Repository,
    ) -> None:
        """AC-10: 同 line 第 2 次 deep_analyze iteration=2 + parent 链。"""
        log_text = "2026-07-27 08:30:00,123 ERROR [db] connection failed"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        entries = repository.list_log_entries(report.id)
        line_id = entries[0].line_id

        first = await service.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="user-1", name="alice"),
        )
        second = await service.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="user-1", name="alice"),
        )
        assert second.iteration == 2
        assert second.parent_record_id == first.id

    async def test_deep_analyze_subset_lines_uses_parent_with_overlap(
        self, service: LogAnalysisService, repository: M2Repository,
    ) -> None:
        """Q4 修复：前次 [L1, L2] 本次 [L1]（子集）应继承 iteration + parent 链。

        场景：铲屎官"二次/多次"深入分析最常见的是"上次分析多行，
        这次只想再深入其中一行"——子集关系，不能丢上下文链。

        修复策略：parent 选有非空交集且 iteration 最大者；
        多候选取交集最大者（最相关）。
        """
        log_text = (
            "2026-07-27 08:30:00,123 ERROR [db] connection failed\n"
            "2026-07-27 08:31:00,123 ERROR [db] query timeout\n"
        )
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        entries = repository.list_log_entries(report.id)
        assert len(entries) == 2
        line1, line2 = entries[0].line_id, entries[1].line_id

        # Phase 2 round 1: 选 [L1, L2] 两行
        first = await service.deep_analyze(
            report_id=report.id, line_ids=[line1, line2],
            analyzer=User(id="user-1", name="alice"),
        )
        assert first.iteration == 1
        assert first.parent_record_id is None

        # Phase 2 round 2: 只选 [L1] 一行（子集）
        # Q4 修复前：set(L1) != set(L1, L2) → parent=None → iteration=1（丢链）
        # Q4 修复后：有非空交集 → 继承 iteration=2 + parent=first.id
        second = await service.deep_analyze(
            report_id=report.id, line_ids=[line1],
            analyzer=User(id="user-1", name="alice"),
        )
        assert second.iteration == 2
        assert second.parent_record_id == first.id
        # 新 record 的 line_ids 是本次选的（[L1]）
        assert second.line_ids == [line1]

    async def test_deep_analyze_disjoint_lines_starts_iteration_1(
        self, service: LogAnalysisService, repository: M2Repository,
    ) -> None:
        """Q4 边界：完全不相交的 line 集合应 iteration=1（新链）。"""
        log_text = (
            "2026-07-27 08:30:00,123 ERROR [db] connection failed\n"
            "2026-07-27 08:31:00,123 ERROR [db] query timeout\n"
        )
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        entries = repository.list_log_entries(report.id)
        line1, line2 = entries[0].line_id, entries[1].line_id

        # 第一次：[L1]
        first = await service.deep_analyze(
            report_id=report.id, line_ids=[line1],
            analyzer=User(id="user-1", name="alice"),
        )
        # 第二次：[L2]（不相交）
        second = await service.deep_analyze(
            report_id=report.id, line_ids=[line2],
            analyzer=User(id="user-1", name="alice"),
        )
        # 不相交 → 新链 → iteration=1
        assert second.iteration == 1
        assert second.parent_record_id is None

    async def test_deep_analyze_subset_picks_most_overlap_when_multiple(
        self, service: LogAnalysisService, repository: M2Repository,
    ) -> None:
        """Q4 边界：多个候选父时取交集最大者（最相关）。

        历史：
          - [L1, L2] iter=1
          - [L1, L2] iter=2（parent=iter1）
          - [L1] iter=3（parent=iter2，因为 [L1] ⊂ [L1, L2] 交集 1）
        现在：[L1, L2, L3]——
          - 与 [L1, L2] iter=2 交集 2
          - 与 [L1] iter=3 交集 1
          → 取交集大者 iter=2 → 继承 iteration=3
        """
        log_text = (
            "2026-07-27 08:30:00,123 ERROR [db] connection failed\n"
            "2026-07-27 08:31:00,123 ERROR [db] query timeout\n"
            "2026-07-27 08:32:00,123 ERROR [db] pool exhausted\n"
        )
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        entries = repository.list_log_entries(report.id)
        l1, l2, l3 = (e.line_id for e in entries)

        await service.deep_analyze(
            report_id=report.id, line_ids=[l1, l2],
            analyzer=User(id="user-1", name="alice"),
        )
        await service.deep_analyze(
            report_id=report.id, line_ids=[l1, l2],
            analyzer=User(id="user-1", name="alice"),
        )
        await service.deep_analyze(
            report_id=report.id, line_ids=[l1],
            analyzer=User(id="user-1", name="alice"),
        )
        record = await service.deep_analyze(
            report_id=report.id, line_ids=[l1, l2, l3],
            analyzer=User(id="user-1", name="alice"),
        )
        # 选交集最大的 parent（iter=2 的 [L1, L2]），继承 iter=3
        assert record.iteration == 3
        # parent 应是 [L1, L2] iter=2 那条
        from packages.contracts.deep_analysis import DeepAnalysisRecord
        parent = service._repo.get_deep_analysis(record.parent_record_id)
        assert parent is not None
        assert set(parent.line_ids) == {l1, l2}
        assert parent.iteration == 2


# ---- get_report + list_deep_analyses ----

class TestQueryAPIs:
    """get_report + list_deep_analyses 只读 API。"""

    async def test_get_report_returns_dataclass(
        self, service: LogAnalysisService, repository: M2Repository,
    ) -> None:
        log_text = "2026-07-27 08:30:00,123 INFO system ready"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        fetched = service.get_report(report.id)
        assert fetched is not None
        assert fetched.id == report.id

    async def test_get_report_returns_none_when_missing(
        self, service: LogAnalysisService
    ) -> None:
        assert service.get_report("rpt-missing") is None

    async def test_list_deep_analyses_empty(
        self, service: LogAnalysisService
    ) -> None:
        assert service.list_deep_analyses("rpt-no-deep") == []

    async def test_list_deep_analyses_after_two_iterations(
        self, service: LogAnalysisService, repository: M2Repository,
    ) -> None:
        log_text = "2026-07-27 08:30:00,123 ERROR connection failed"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        entries = repository.list_log_entries(report.id)
        line_id = entries[0].line_id

        await service.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="user-1", name="alice"),
        )
        await service.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="user-1", name="alice"),
        )

        results = service.list_deep_analyses(report.id)
        assert len(results) == 2
        assert results[0].iteration == 1
        assert results[1].iteration == 2


# ---- archive_report ----

class TestArchiveReport:
    """archive_report 改状态 + 写 audit_log。"""

    async def test_archive_report_updates_status(
        self, service: LogAnalysisService, repository: M2Repository,
        session: Session,
    ) -> None:
        log_text = "2026-07-27 08:30:00,123 INFO system ready"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="user-1", name="alice"),
        )
        assert report.ingestion_status == STATUS_DRAFT

        service.archive_report(report.id, archiver=User(id="user-1", name="alice"))

        persisted = repository.get_analysis_report(report.id)
        assert persisted is not None
        assert persisted.ingestion_status == STATUS_ARCHIVED

        # AC-15: 写 audit_log
        from packages.m1.storage.models import AuditLogModel
        audit_rows = session.query(AuditLogModel).filter_by(
            action=ACTION_ARCHIVE_REPORT
        ).all()
        assert len(audit_rows) == 1

    def test_archive_report_missing_raises(
        self, service: LogAnalysisService
    ) -> None:
        """归档不存在的 report 抛 ValueError（service 层契约）。"""
        with pytest.raises(ValueError, match="not found"):
            service.archive_report("rpt-missing", archiver=User(id="u", name="n"))


# ---- AC-14: metrics 集成 ----

class TestMetricsIntegration:
    """AC-14: LogAnalysisService 集成 M2MetricsEmitter。"""

    async def test_analyze_logs_emits_metrics(
        self, service_with_metrics: LogAnalysisService,
        metrics_mock: MagicMock,
    ) -> None:
        """Phase 1 analyze_logs 完成后写 4 个指标：
        set_log_point_match_rate + observe_llm_call_duration(phase1)
        + inc_llm_cost + inc_analysis_report
        """
        log_text = "2026-07-27 08:30:00,123 INFO system ready"
        await service_with_metrics.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="u1", name="alice"),
        )
        # AC-14: 4 个指标都被调用
        metrics_mock.set_log_point_match_rate.assert_called_once()
        metrics_mock.observe_llm_call_duration.assert_called_once()
        # 验证 phase 标签
        assert metrics_mock.observe_llm_call_duration.call_args.kwargs["phase"] == "phase1"
        # seconds 是 float > 0（实际 LLM 调用耗时，mock 立即返回）
        assert metrics_mock.observe_llm_call_duration.call_args.kwargs["seconds"] >= 0.0
        metrics_mock.inc_llm_cost.assert_called_once_with(usd=0.02)
        metrics_mock.inc_analysis_report.assert_called_once_with(
            repo_id="<no-repo>",
        )

    async def test_deep_analyze_emits_metrics(
        self, service_with_metrics: LogAnalysisService,
        repository: M2Repository, metrics_mock: MagicMock,
    ) -> None:
        """Phase 2 deep_analyze 完成后写 3 个指标：
        observe_llm_call_duration(phase2) + inc_llm_cost + inc_deep_analysis
        """
        log_text = "2026-07-27 08:30:00,123 ERROR connection failed"
        report = await service_with_metrics.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="u1", name="alice"),
        )
        # 重置 mock 计数（只看 deep_analyze 触发的）
        metrics_mock.reset_mock()

        entries = repository.list_log_entries(report.id)
        line_id = entries[0].line_id

        await service_with_metrics.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="u1", name="alice"),
        )
        # AC-14: 3 个指标都被调用
        metrics_mock.observe_llm_call_duration.assert_called_once()
        assert metrics_mock.observe_llm_call_duration.call_args.kwargs["phase"] == "phase2"
        assert metrics_mock.observe_llm_call_duration.call_args.kwargs["seconds"] >= 0.0
        metrics_mock.inc_llm_cost.assert_called_once_with(usd=0.05)
        metrics_mock.inc_deep_analysis.assert_called_once_with(
            repo_id="<no-repo>",
        )

    async def test_analyze_logs_without_metrics_emitter_skips_metrics(
        self, service: LogAnalysisService,
    ) -> None:
        """metrics=None 时不抛错（生产旧代码向后兼容）。"""
        log_text = "2026-07-27 08:30:00,123 INFO system ready"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="u1", name="alice"),
        )
        assert report.system_summary == "system had errors"


# ---- StorageBackedLogPointIndex 集成 ----

class TestStorageBackedLogPointIndexIntegration:
    """review OQ-2：用真实 StorageBackedLogPointIndex 取代 MagicMock。"""

    async def test_analyze_logs_with_real_index_matches_confirmed_log_point(
        self, session: Session, audit: AuditLogger, cache: MagicMock,
        llm_client_phase1: AsyncMock, llm_client_phase2: AsyncMock,
        sanitizer: LogSanitizer, repository: M2Repository,
        m1_service: MagicMock,
    ) -> None:
        """真实 StorageBackedLogPointIndex 命中 confirmed LogPoint。

        场景：M1 主表有 "User {uid} logged in"（confirmed），
        M2 LogParser 解析出 "User 12345 logged in" → 模板
        "User {var_0} logged in" → 归一化为 "User {x} logged in" → 命中。
        """
        from packages.m1.storage.models import LogPointModel
        from packages.m2.storage_backed_log_point_index import (
            StorageBackedLogPointIndex,
        )

        # 准备 M1 主表数据（confirmed 状态）
        now = datetime.now(UTC)
        session.add(LogPointModel(
            id="lp-real-1",
            repo_id="repo-real",
            git_commit_sha="sha",
            extractor_version="v1",
            file_path="app/auth.py",
            function_signature="def login()",
            line_start=10,
            line_end=10,
            language="python",
            log_level="INFO",
            log_message_template="User {uid} logged in",
            log_message_variables=["uid"],
            framework_hint="logging",
            confidence_score=0.95,
            enclosing_class=None,
            call_chain_to_entry=[],
            enclosing_community=None,
            evidence_refs_json="[]",
            llm_hypothesis_json=None,
            occurrence_count=1,
            is_top_n=True,
            ingestion_status="confirmed",
            first_seen_at=now,
            last_seen_at=now,
        ))
        session.commit()

        # 用真实 index
        real_index = StorageBackedLogPointIndex(
            repo_id="repo-real", session=session,
        )
        service = LogAnalysisService(
            session=session,
            audit=audit,
            repository=repository,
            log_parser=LogParser(),
            log_point_matcher=LogPointMatcher(real_index),
            report_generator=ReportGenerator(
                llm_client=llm_client_phase1, cache=cache, sanitizer=sanitizer,
                config=Phase1Config(
                    model_name="claude-haiku", window_hours=24,
                    max_log_lines_per_call=200, cache_ttl_seconds=86400,
                ),
            ),
            deep_analyzer=DeepAnalyzer(
                llm_client=llm_client_phase2, cache=cache, sanitizer=sanitizer,
                config=Phase2Config(
                    model_name="claude-opus-4", max_iterations=5,
                    cache_ttl_seconds=86400,
                ),
            ),
            hypothesis_writer=HypothesisWriter(m1_service=m1_service),
            m1_service=m1_service,
        )

        # 日志格式让 LogParser 提取模板 "User {var_0} logged in"
        # （与 M1 的 "User {uid} logged in" 不同变量名但归一化后等价）
        log_text = "2026-07-27 08:30:00,123 INFO User 12345 logged in"
        report = await service.analyze_logs(
            log_source=LogSource(text=log_text),
            analyzer=User(id="u1", name="alice"),
            repo_id="repo-real",
        )
        assert report.system_summary == "system had errors"

        # 端到端 deep_analyze，验证 M1 回写被调用
        entries = repository.list_log_entries(report.id)
        line_id = entries[0].line_id
        record = await service.deep_analyze(
            report_id=report.id, line_ids=[line_id],
            analyzer=User(id="u1", name="alice"),
        )
        # M1 update_log_point_hypothesis 应被调用（log_point_ids 含真实 LogPoint id）
        m1_service.update_log_point_hypothesis.assert_called_once()
        call_kwargs = m1_service.update_log_point_hypothesis.call_args.kwargs
        assert call_kwargs["log_point_ids"] == ["lp-real-1"]
        assert call_kwargs["writer"] == "m2-phase2-deep-analyzer"
        # record.log_point_ids 也应含真实 LogPoint id
        assert "lp-real-1" in record.log_point_ids
