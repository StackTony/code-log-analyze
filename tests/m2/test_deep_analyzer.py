"""F002 M2 — DeepAnalyzer 测试（spec §三 + AC-7/8/10/11）。

Phase 2 深入分析：
  选 line + M1 CallContext + Phase 1 报告摘要 → 强模型 LLM → DeepAnalysisRecord

验证点：
  - AC-7: 上下文组装含 4 部分（选定日志原文 + M1 LogPoint + M1 CallContext + Phase 1 摘要）
  - AC-8: 产出 DeepAnalysisRecord 含 root_cause_hypothesis + fix_suggestion + related_evidence
  - AC-10: 迭代性 — 同 line 多次 deep_analyze 累积上下文（iteration 递增 + parent_record_id 链）
  - AC-11: 累积上限 phase2_max_iterations（默认 5）触发时拒绝 + 提示归档重启
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.deep_analysis import DeepAnalysisRecord
from packages.contracts.log_entry import LogEntry
from packages.contracts.log_point import CallContext, CaseRef, LogPoint
from packages.m1.log_sanitizer import LogSanitizer, SanitizerConfig
from packages.m1.llm_hypothesis_generator import LLMClient, RedisCache
from packages.m2.deep_analyzer import DeepAnalyzer, Phase2Config


# ---- Fixtures ----

def _make_entry(
    line_id: str = "le-1",
    raw_text: str = "2026-07-27 08:30:00 ERROR db connection failed",
    template: str | None = "db connection failed",
    level: str = "ERROR",
) -> LogEntry:
    return LogEntry(
        line_id=line_id, raw_text=raw_text,
        timestamp=datetime(2026, 7, 27, 8, 30, 0, tzinfo=UTC),
        level=level, log_message_template=template,
        variables={}, source_file="app.log", source_line=42,
    )


def _make_log_point(lp_id: str = "lp-1") -> LogPoint:
    return LogPoint(
        id=lp_id, repo_id="repo-1", git_commit_sha="sha-1",
        extractor_version="v1", file_path="app/db.py",
        function_signature="def connect()",
        line_start=10, line_end=10, language="python",
        log_level="ERROR",
        log_message_template="db connection failed",
        log_message_variables=[], framework_hint="logging",
        confidence_score=0.9, enclosing_class=None,
        call_chain_to_entry=[], enclosing_community="DbModule",
        first_seen_at=datetime(2026, 7, 27, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 27, tzinfo=UTC),
    )


def _make_call_context(sig: str = "def connect()") -> CallContext:
    return CallContext(
        function_signature=sig,
        callers=["def handle_request()"],
        callees=["def ping()"],
        enclosing_community="DbModule",
        related_log_points=[],
        evidence_refs=[],
    )


def _make_phase1_report() -> AnalysisReport:
    return AnalysisReport(
        id="rpt-1", repo_id="repo-1", log_source="app.log",
        log_line_count=100,
        window_start=datetime(2026, 7, 27, tzinfo=UTC),
        window_end=datetime(2026, 7, 27, 1, 0, 0, tzinfo=UTC),
        model_name="claude-haiku", prompt_hash="sha256:abc",
        system_summary="system had errors",
        anomaly_localization=[Anomaly(
            line_ids=["le-1"], severity="error", module="db",
            summary="db connection failures", evidence_snippets=["raw"],
        )],
        error_correlation=[ErrorChain(
            chain_id="c1", line_ids_ordered=["le-1"],
            relation="causal", summary="causal chain", confidence_score=0.8,
        )],
        generated_at=datetime(2026, 7, 27, tzinfo=UTC),
        duration_seconds=12.0,
        token_usage=TokenUsage(prompt_tokens=100, completion_tokens=50, total_cost_usd=0.02),
        ingestion_status="draft",
    )


def _make_llm_response(
    root_cause: str = "db pool exhausted",
    fix_suggestion: str | None = "increase pool size to 20",
) -> str:
    payload = {
        "root_cause_hypothesis": root_cause,
        "fix_suggestion": fix_suggestion,
        "related_evidence": [
            {
                "case_id": "case-1", "repo_id": "repo-1",
                "file_path": "app/db.py", "function_signature": "def connect()",
                "log_template": "db connection failed",
                "resolved_at": "2026-07-01T00:00:00+00:00",
                "resolution_summary": "fixed by adding retry",
                "resolution_diff_url": "https://example.com/diff/1",
            }
        ],
        "token_usage": {
            "prompt_tokens": 200, "completion_tokens": 100,
            "total_cost_usd": 0.05,
        },
    }
    return json.dumps(payload)


@pytest.fixture()
def sanitizer() -> LogSanitizer:
    return LogSanitizer(SanitizerConfig(
        enabled=True, patterns=["api_key", "password", "token"],
        replacement="[REDACTED_{kind}]",
    ))


@pytest.fixture()
def cache() -> MagicMock:
    c = MagicMock(spec=RedisCache)
    c.get.return_value = None
    return c


@pytest.fixture()
def llm_client() -> AsyncMock:
    client = AsyncMock(spec=LLMClient)
    client.complete.return_value = _make_llm_response()
    return client


@pytest.fixture()
def analyzer(
    sanitizer: LogSanitizer, cache: MagicMock, llm_client: AsyncMock
) -> DeepAnalyzer:
    return DeepAnalyzer(
        llm_client=llm_client,
        cache=cache,
        sanitizer=sanitizer,
        config=Phase2Config(
            model_name="claude-opus-4",
            max_iterations=5,
            cache_ttl_seconds=86400,
        ),
    )


# ---- AC-7: 上下文组装 ----

class TestContextAssembly:
    """AC-7: 上下文含 4 部分。"""

    def test_assemble_context_contains_all_four_parts(
        self, analyzer: DeepAnalyzer
    ) -> None:
        """装配 prompt 含：选定日志原文 + M1 LogPoint + M1 CallContext + Phase 1 摘要。"""
        entry = _make_entry()
        log_point = _make_log_point()
        call_ctx = _make_call_context()
        report = _make_phase1_report()

        prompt = analyzer._assemble_prompt(
            entries=[entry],
            log_points=[log_point],
            call_contexts=[call_ctx],
            phase1_report=report,
        )

        # AC-7: 4 部分全在 prompt 中
        assert entry.raw_text in prompt  # 选定日志原文
        assert log_point.function_signature in prompt  # M1 LogPoint
        assert log_point.file_path in prompt
        assert call_ctx.callers[0] in prompt  # M1 CallContext
        assert call_ctx.enclosing_community in prompt
        assert report.system_summary in prompt  # Phase 1 摘要
        assert report.anomaly_localization[0].summary in prompt

    def test_assemble_context_with_no_log_point(self, analyzer: DeepAnalyzer) -> None:
        """无 LogPoint 匹配（fallback）→ 仍可装配（只少 LogPoint 部分）。"""
        entry = _make_entry()
        report = _make_phase1_report()

        prompt = analyzer._assemble_prompt(
            entries=[entry],
            log_points=[],  # 无匹配
            call_contexts=[],
            phase1_report=report,
        )
        assert entry.raw_text in prompt
        assert report.system_summary in prompt

    def test_assemble_context_with_parent_record(self, analyzer: DeepAnalyzer) -> None:
        """AC-10: iteration > 1 时含 parent_record_id 链上下文。"""
        entry = _make_entry()
        report = _make_phase1_report()
        parent = DeepAnalysisRecord(
            id="da-parent", report_id="rpt-1", line_ids=["le-1"],
            log_point_ids=["lp-1"], call_contexts=[],
            root_cause_hypothesis="parent: maybe pool",
            fix_suggestion="check pool",
            related_evidence=[], model_name="claude-opus-4",
            prompt_hash="sha256:p1", iteration=1, parent_record_id=None,
            generated_at=datetime(2026, 7, 27, tzinfo=UTC),
            token_usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_cost_usd=0.0),
        )

        prompt = analyzer._assemble_prompt(
            entries=[entry], log_points=[], call_contexts=[],
            phase1_report=report, parent_record=parent,
        )
        assert "parent: maybe pool" in prompt
        assert "iteration=1" in prompt.lower()


# ---- AC-8: DeepAnalysisRecord 产出 ----

async def test_produces_deep_analysis_record(analyzer: DeepAnalyzer) -> None:
    """AC-8: 输出含 root_cause_hypothesis + fix_suggestion + related_evidence。"""
    entry = _make_entry()
    log_point = _make_log_point()
    call_ctx = _make_call_context()
    report = _make_phase1_report()

    record = await analyzer.analyze(
        report_id="rpt-1",
        entries=[entry],
        log_points=[log_point],
        call_contexts=[call_ctx],
        phase1_report=report,
    )

    assert isinstance(record, DeepAnalysisRecord)
    assert record.root_cause_hypothesis == "db pool exhausted"
    assert record.fix_suggestion == "increase pool size to 20"
    assert len(record.related_evidence) == 1
    assert record.related_evidence[0].case_id == "case-1"
    assert record.model_name == "claude-opus-4"
    assert record.iteration == 1
    assert record.parent_record_id is None
    assert record.token_usage.prompt_tokens == 200
    assert record.token_usage.total_cost_usd == 0.05


# ---- AC-10: 迭代性 ----

class TestIteration:
    """AC-10: 同 line 多次 deep_analyze 累积上下文（iteration 递增 + parent 链）。"""

    async def test_iteration_1_first_call(
        self, analyzer: DeepAnalyzer, llm_client: AsyncMock
    ) -> None:
        """首次调用 iteration=1, parent_record_id=None。"""
        report = _make_phase1_report()
        record = await analyzer.analyze(
            report_id="rpt-1",
            entries=[_make_entry()],
            log_points=[], call_contexts=[], phase1_report=report,
        )
        assert record.iteration == 1
        assert record.parent_record_id is None

    async def test_iteration_2_with_parent(
        self, analyzer: DeepAnalyzer, llm_client: AsyncMock
    ) -> None:
        """第 2 次调用 iteration=2, parent_record_id 指向前次。"""
        report = _make_phase1_report()
        parent = await analyzer.analyze(
            report_id="rpt-1",
            entries=[_make_entry()],
            log_points=[], call_contexts=[], phase1_report=report,
        )

        # 第 2 次：传入 parent_record
        record = await analyzer.analyze(
            report_id="rpt-1",
            entries=[_make_entry()],
            log_points=[], call_contexts=[], phase1_report=report,
            parent_record=parent,
        )
        assert record.iteration == 2
        assert record.parent_record_id == parent.id


# ---- AC-11: 累积上限 ----

class TestIterationLimit:
    """AC-11: phase2_max_iterations（默认 5）触发时拒绝 + 提示归档重启。"""

    async def test_iteration_at_limit_raises(
        self, analyzer: DeepAnalyzer
    ) -> None:
        """iteration 达 max_iterations → 抛 IterationLimitExceeded + 提示归档。"""
        from packages.m2.deep_analyzer import IterationLimitExceeded

        report = _make_phase1_report()
        # 构造 parent（iteration=4）+ grandparent（iteration=3）链
        parent = DeepAnalysisRecord(
            id="da-4", report_id="rpt-1", line_ids=["le-1"],
            log_point_ids=[], call_contexts=[],
            root_cause_hypothesis="iter4", fix_suggestion=None,
            related_evidence=[], model_name="claude-opus-4",
            prompt_hash="h", iteration=4, parent_record_id="da-3",
            generated_at=datetime(2026, 7, 27, tzinfo=UTC),
            token_usage=TokenUsage(0, 0, 0.0),
        )

        # 第 5 次调用允许（iteration=5 = max_iterations）
        record = await analyzer.analyze(
            report_id="rpt-1", entries=[_make_entry()],
            log_points=[], call_contexts=[], phase1_report=report,
            parent_record=parent,
        )
        assert record.iteration == 5

        # 第 6 次调用必须抛异常
        with pytest.raises(IterationLimitExceeded) as exc_info:
            await analyzer.analyze(
                report_id="rpt-1", entries=[_make_entry()],
                log_points=[], call_contexts=[], phase1_report=report,
                parent_record=record,  # iteration=5 → 第 6 次会超
            )
        assert "archive" in str(exc_info.value).lower()

    async def test_iteration_limit_message_mentions_archive(self) -> None:
        """异常 message 含 archive 提示（spec AC-11 措辞）。"""
        from packages.m2.deep_analyzer import IterationLimitExceeded

        err = IterationLimitExceeded(current=5, limit=5, report_id="rpt-1")
        msg = str(err)
        assert "archive" in msg.lower()
        assert "rpt-1" in msg


# ---- AC-5: 脱敏 ----

async def test_prompt_sanitized_before_llm(
    analyzer: DeepAnalyzer, llm_client: AsyncMock
) -> None:
    """AC-5: LLM 调用前 prompt 经 LogSanitizer 脱敏。"""
    entry = _make_entry(
        raw_text='2026-07-27 08:30:00 ERROR api_key=sk-abcdefghijklmno12345 leaked',
    )
    report = _make_phase1_report()
    await analyzer.analyze(
        report_id="rpt-1", entries=[entry],
        log_points=[], call_contexts=[], phase1_report=report,
    )
    called_prompt = llm_client.complete.call_args.args[0]
    assert "sk-abcdefghijklmno12345" not in called_prompt
    assert "REDACTED" in called_prompt.upper() or "REDACTED" in called_prompt


# ---- AC-6: 缓存 ----

class TestCache:
    """AC-6: 缓存 key 含 phase2 + report_id + line_ids + model_name。"""

    def test_cache_key_contains_required_parts(self, analyzer: DeepAnalyzer) -> None:
        entry = _make_entry()
        key = analyzer._cache_key("rpt-1", [entry], iteration=1)
        assert "phase2" in key
        assert "claude-opus-4" in key
        assert "rpt-1" in key

    async def test_cache_hit_skips_llm(
        self, analyzer: DeepAnalyzer, llm_client: AsyncMock,
        cache: MagicMock,
    ) -> None:
        """缓存命中不调 LLM。"""
        cache.get.return_value = _make_llm_response()
        report = _make_phase1_report()
        record = await analyzer.analyze(
            report_id="rpt-1", entries=[_make_entry()],
            log_points=[], call_contexts=[], phase1_report=report,
        )
        llm_client.complete.assert_not_called()
        assert record.root_cause_hypothesis == "db pool exhausted"
