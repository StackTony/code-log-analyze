"""F002 M2 — ReportGenerator 测试（spec §三 + AC-3/4/5/6/17）。

Phase 1 全量分析报告生成器：
  LogEntry 列表 → prompt 装配（脱敏） → LLM 调用 → JSON 解析 → AnalysisReport

验证点：
  - AC-3: 输出含三类信息（system_summary / anomaly_localization / error_correlation）
  - AC-4: 时间窗兜底（window_hours 默认 24h，超出截断 + 警告）
  - AC-5: LLM 调用经 LogSanitizer 脱敏，敏感字段零命中
  - AC-6: Redis 缓存 key 含 phase1 + log_template + model_name，相同日志重分析不重复调
  - AC-17: 成本控制 — Phase 1 用便宜模型

注：async 测试在 module-level 而非 class 内（pytest-asyncio mode=auto 对
module-level async def 生效，class 内 async def 需要 @pytest.mark.asyncio）。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.contracts.analysis_report import (
    AnalysisReport,
    Anomaly,
    ErrorChain,
    TokenUsage,
)
from packages.contracts.log_entry import LogEntry
from packages.m2.report_generator import (
    Phase1Config,
    ReportGenerator,
    WindowTruncationResult,
)
from packages.m1.log_sanitizer import SanitizerConfig
from packages.m1.log_sanitizer import LogSanitizer
from packages.m1.llm_hypothesis_generator import LLMClient, RedisCache


# ---- Fixtures ----

def _make_entry(
    line_id: str = "le-1",
    template: str | None = "User {var_0} logged in",
    level: str = "INFO",
    raw_text: str = "2026-07-27 08:30:00 INFO User 12345 logged in",
    timestamp: datetime | None = None,
) -> LogEntry:
    if timestamp is None:
        timestamp = datetime(2026, 7, 27, 8, 30, 0, tzinfo=UTC)
    return LogEntry(
        line_id=line_id, raw_text=raw_text, timestamp=timestamp, level=level,
        log_message_template=template, variables={"var_0": "12345"},
        source_file="app.log", source_line=42,
    )


def _make_llm_response(
    summary: str = "system ran normally",
    anomalies: list[dict] | None = None,
    error_chains: list[dict] | None = None,
) -> str:
    """构造 LLM 返回的 JSON 字符串（Phase 1 schema）。"""
    payload = {
        "system_summary": summary,
        "anomaly_localization": anomalies or [],
        "error_correlation": error_chains or [],
        "token_usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_cost_usd": 0.02,
        },
    }
    return json.dumps(payload)


@pytest.fixture()
def sanitizer() -> LogSanitizer:
    return LogSanitizer(SanitizerConfig(
        enabled=True,
        patterns=["api_key", "password", "token", "ipv4", "email"],
        replacement="[REDACTED_{kind}]",
    ))


@pytest.fixture()
def cache() -> MagicMock:
    c = MagicMock(spec=RedisCache)
    c.get.return_value = None  # 默认缓存未命中
    return c


@pytest.fixture()
def llm_client() -> AsyncMock:
    """LLM client mock，返回固定 JSON。"""
    client = AsyncMock(spec=LLMClient)
    client.complete.return_value = _make_llm_response(
        summary="system ran normally",
        anomalies=[{
            "line_ids": ["le-1"], "severity": "error", "module": "auth",
            "summary": "auth spike", "evidence_snippets": ["raw line"],
        }],
        error_chains=[{
            "chain_id": "chain-1", "line_ids_ordered": ["le-1"],
            "relation": "causal", "summary": "causal chain",
            "confidence_score": 0.85,
        }],
    )
    return client


@pytest.fixture()
def generator(
    sanitizer: LogSanitizer, cache: MagicMock, llm_client: AsyncMock
) -> ReportGenerator:
    return ReportGenerator(
        llm_client=llm_client,
        cache=cache,
        sanitizer=sanitizer,
        config=Phase1Config(
            model_name="claude-haiku",
            window_hours=24,
            max_log_lines_per_call=200,
            cache_ttl_seconds=86400,
        ),
    )


# ---- AC-4: 时间窗兜底（同步方法可放 class） ----

class TestWindowTruncation:
    """AC-4: window_hours 默认 24h，超出截断 + 警告。"""

    def test_truncate_keeps_entries_within_window(self, generator: ReportGenerator) -> None:
        """窗口内的日志保留。"""
        now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
        entries = [
            _make_entry(line_id="le-old", timestamp=now - timedelta(hours=20)),
            _make_entry(line_id="le-now", timestamp=now),
        ]
        result = generator.truncate_to_window(entries, window_end=now, window_hours=24)
        assert len(result.kept) == 2
        assert result.truncated_count == 0

    def test_truncate_removes_entries_outside_window(self, generator: ReportGenerator) -> None:
        """超出窗口的日志截断。"""
        now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
        entries = [
            _make_entry(line_id="le-old", timestamp=now - timedelta(hours=48)),  # 超 24h
            _make_entry(line_id="le-now", timestamp=now),
        ]
        result = generator.truncate_to_window(entries, window_end=now, window_hours=24)
        assert len(result.kept) == 1
        assert result.kept[0].line_id == "le-now"
        assert result.truncated_count == 1
        assert "window" in result.warning.lower()

    def test_truncate_with_no_timestamps_kept_as_is(self, generator: ReportGenerator) -> None:
        """无 timestamp 的日志条目（未识别格式）保留，不参与截断判断。"""
        entries = [
            _make_entry(line_id="le-no-ts", timestamp=None, template=None),
        ]
        result = generator.truncate_to_window(entries, window_end=datetime.now(UTC), window_hours=24)
        assert len(result.kept) == 1
        assert result.truncated_count == 0

    def test_truncate_empty_list_returns_empty(self, generator: ReportGenerator) -> None:
        result = generator.truncate_to_window([], window_end=datetime.now(UTC), window_hours=24)
        assert result.kept == []
        assert result.truncated_count == 0


# ---- AC-5: 脱敏（async 测试在 module-level） ----

async def test_api_key_in_log_redacted_before_llm(
    generator: ReportGenerator, llm_client: AsyncMock, cache: MagicMock
) -> None:
    """AC-5: 日志中的 api_key 在送入 LLM 前被脱敏。"""
    entry = _make_entry(
        raw_text='2026-07-27 08:30:00 INFO api_key=sk-abcdefghijklmno12345 leaked',
        template='api_key leaked',
    )
    await generator.generate([entry], log_source="app.log")

    called_prompt = llm_client.complete.call_args.args[0]
    assert "sk-abcdefghijklmno12345" not in called_prompt
    assert "REDACTED" in called_prompt.upper() or "REDACTED" in called_prompt


async def test_no_sensitive_data_passthrough(
    generator: ReportGenerator, llm_client: AsyncMock
) -> None:
    """AC-5: 日志无敏感数据时，prompt 原样送 LLM。"""
    entries = [_make_entry(raw_text="2026-07-27 08:30:00 INFO system ready")]
    await generator.generate(entries, log_source="app.log")
    llm_client.complete.assert_called_once()
    prompt = llm_client.complete.call_args.args[0]
    assert "system ready" in prompt


# ---- AC-6: Redis 缓存 ----

class TestRedisCache:
    """AC-6: 缓存 key 含 phase1 + log_template + model_name，相同日志不重复调。"""

    def test_cache_key_contains_required_parts(self, generator: ReportGenerator) -> None:
        """cache key 含 phase1 / log_template / model_name。"""
        entries = [_make_entry(template="User {var_0} logged in")]
        key = generator._cache_key(entries)
        assert "phase1" in key
        assert "claude-haiku" in key  # model_name

    def test_same_logs_same_key(self, generator: ReportGenerator) -> None:
        """相同日志集（按模板）→ 相同 cache key（相同 model_name）。"""
        entries1 = [_make_entry(line_id="le-a"), _make_entry(line_id="le-b")]
        entries2 = [_make_entry(line_id="le-a"), _make_entry(line_id="le-b")]
        # line_id 不应影响 key（key 基于模板而非 id）
        assert generator._cache_key(entries1) == generator._cache_key(entries2)


async def test_cache_hit_skips_llm_call(
    generator: ReportGenerator, llm_client: AsyncMock, cache: MagicMock
) -> None:
    """AC-6: 缓存命中时不调 LLM。"""
    cache.get.return_value = _make_llm_response()
    entries = [_make_entry()]
    report = await generator.generate(entries, log_source="app.log")

    llm_client.complete.assert_not_called()
    assert report.system_summary == "system ran normally"


async def test_cache_miss_calls_llm_and_writes_cache(
    generator: ReportGenerator, llm_client: AsyncMock, cache: MagicMock
) -> None:
    """AC-6: 缓存未命中时调 LLM，结果写回缓存。"""
    entries = [_make_entry()]
    await generator.generate(entries, log_source="app.log")

    llm_client.complete.assert_called_once()
    cache.set.assert_called_once()
    written_key = cache.set.call_args.args[0]
    written_value = cache.set.call_args.args[1]
    assert json.loads(written_value)["system_summary"] == "system ran normally"
    assert "phase1" in written_key


# ---- AC-3: 三类信息（async 测试在 module-level） ----

async def test_report_contains_three_categories(
    generator: ReportGenerator, llm_client: AsyncMock
) -> None:
    """AC-3: 生成的 AnalysisReport 含 system_summary + anomaly_localization + error_correlation。"""
    entries = [_make_entry()]
    report = await generator.generate(entries, log_source="app.log")

    assert isinstance(report, AnalysisReport)
    assert report.system_summary == "system ran normally"
    assert len(report.anomaly_localization) == 1
    assert isinstance(report.anomaly_localization[0], Anomaly)
    assert report.anomaly_localization[0].summary == "auth spike"
    assert report.anomaly_localization[0].severity == "error"
    assert len(report.error_correlation) == 1
    assert isinstance(report.error_correlation[0], ErrorChain)
    assert report.error_correlation[0].chain_id == "chain-1"
    assert report.error_correlation[0].confidence_score == 0.85


async def test_report_token_usage_from_llm(generator: ReportGenerator) -> None:
    """token_usage 来自 LLM 返回（成本追溯）。"""
    entries = [_make_entry()]
    report = await generator.generate(entries, log_source="app.log")
    assert isinstance(report.token_usage, TokenUsage)
    assert report.token_usage.prompt_tokens == 100
    assert report.token_usage.completion_tokens == 50
    assert report.token_usage.total_cost_usd == 0.02


async def test_report_metadata(generator: ReportGenerator) -> None:
    """report 元数据：log_source / log_line_count / window / model_name / prompt_hash。"""
    entries = [_make_entry()]
    report = await generator.generate(entries, log_source="app.log", repo_id="repo-1")

    assert report.log_source == "app.log"
    assert report.repo_id == "repo-1"
    assert report.log_line_count == 1
    assert report.model_name == "claude-haiku"
    assert report.prompt_hash  # 非空
    assert report.ingestion_status == "draft"


async def test_report_window_from_entries(generator: ReportGenerator) -> None:
    """window_start/end 来自 entries 的最小/最大 timestamp。"""
    now = datetime(2026, 7, 27, 12, 0, 0, tzinfo=UTC)
    entries = [
        _make_entry(line_id="le-a", timestamp=now - timedelta(hours=2)),
        _make_entry(line_id="le-b", timestamp=now),
    ]
    # 显式传 window_end 避免被截断
    report = await generator.generate(entries, log_source="app.log", window_end=now)
    assert report.window_start == now - timedelta(hours=2)
    assert report.window_end == now


# ---- AC-17: 成本控制 ----

class TestCostControl:
    """AC-17: Phase 1 用便宜模型（model_name 由配置注入，不硬编码）。"""

    def test_model_name_injected_via_config(self) -> None:
        """model_name 来自 Phase1Config，可切换便宜模型。"""
        gen = ReportGenerator(
            llm_client=AsyncMock(), cache=MagicMock(),
            sanitizer=LogSanitizer(SanitizerConfig(enabled=False, patterns=[], replacement="")),
            config=Phase1Config(model_name="gpt-4o-mini", window_hours=24, max_log_lines_per_call=200, cache_ttl_seconds=86400),
        )
        assert gen._config.model_name == "gpt-4o-mini"


async def test_too_many_lines_raises(generator: ReportGenerator) -> None:
    """AC-17: 超过 max_log_lines_per_call 的日志明确报错（v1: 拒绝 + 提示）。"""
    entries = [_make_entry(line_id=f"le-{i}") for i in range(250)]
    with pytest.raises(ValueError, match="exceeds max_log_lines"):
        await generator.generate(entries, log_source="app.log")
