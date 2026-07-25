"""LLM Hypothesis Generator 测试 — AC-6 / AC-7 / AC-8。"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from packages.contracts.log_point import LogPoint
from packages.m1.llm_hypothesis_generator import LLMHypothesisGenerator


def _make_log_point() -> LogPoint:
    return LogPoint(
        id="lp-1", repo_id="repo-1", git_commit_sha="abc",
        extractor_version="1.0.0", file_path="src/app.py",
        function_signature="def login()", line_start=10, line_end=10,
        language="python", log_level="ERROR",
        log_message_template="login failed for {uid}",
        log_message_variables=["uid"],
        framework_hint="logging", confidence_score=1.0,
        enclosing_class=None, call_chain_to_entry=[], enclosing_community=None,
        evidence_refs=[], llm_hypothesis=None, occurrence_count=1, is_top_n=False,
        ingestion_status="candidate",
        first_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
        last_seen_at=datetime(2026, 7, 24, tzinfo=UTC),
    )


@pytest.mark.asyncio()
async def test_llm_called_for_log_point() -> None:
    llm_mock = AsyncMock()
    llm_mock.complete.return_value = json.dumps({
        "summary": "uid 可能为空",
        "possible_causes": ["未做 None 校验"],
        "error_kind": "param_error",
        "suggested_check": "检查 uid 是否 None",
    })

    cache = MagicMock()
    cache.get.return_value = None  # 缓存未命中

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=MagicMock(),  # 简化：sanitizer mock
    )
    points = [_make_log_point()]
    # sanitizer 返回无命中
    gen._sanitizer.sanitize.return_value = (points[0].log_message_template, {})
    await gen.generate(points)

    assert points[0].llm_hypothesis is not None
    assert points[0].llm_hypothesis.summary == "uid 可能为空"
    llm_mock.complete.assert_awaited_once()


@pytest.mark.asyncio()
async def test_cache_hit_skips_llm_call() -> None:
    """AC-6：缓存命中不重复调。"""
    llm_mock = AsyncMock()
    cache = MagicMock()
    cached_hypothesis = {
        "summary": "cached", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None, "model_name": "gpt-4", "prompt_hash": "v1",
    }
    cache.get.return_value = json.dumps(cached_hypothesis)

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=MagicMock(),
    )
    gen._sanitizer.sanitize.return_value = ("text", {})

    points = [_make_log_point()]
    await gen.generate(points)

    # LLM 不应被调用
    llm_mock.complete.assert_not_awaited()
    # 但 hypothesis 应从缓存填充
    assert points[0].llm_hypothesis is not None
    assert points[0].llm_hypothesis.summary == "cached"


@pytest.mark.asyncio()
async def test_llm_failure_keeps_hypothesis_none() -> None:
    """AC-7：LLM 失败时不阻塞流水线。"""
    llm_mock = AsyncMock()
    llm_mock.complete.side_effect = RuntimeError("llm down")
    cache = MagicMock()
    cache.get.return_value = None

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="1.0.0",
        sanitizer=MagicMock(),
    )
    gen._sanitizer.sanitize.return_value = ("text", {})

    points = [_make_log_point()]
    await gen.generate(points)
    assert points[0].llm_hypothesis is None


@pytest.mark.asyncio()
async def test_cache_key_includes_extractor_version() -> None:
    """AC-6 v3：缓存 key 含 extractor_version。"""
    llm_mock = AsyncMock()
    llm_mock.complete.return_value = json.dumps({
        "summary": "x", "possible_causes": [], "error_kind": "unknown",
        "suggested_check": None,
    })
    cache = MagicMock()
    cache.get.return_value = None

    gen = LLMHypothesisGenerator(
        llm_client=llm_mock, cache=cache,
        model_name="gpt-4", extractor_version="2.0.0",  # 升级后
        sanitizer=MagicMock(),
    )
    gen._sanitizer.sanitize.return_value = ("text", {})
    points = [_make_log_point()]
    await gen.generate(points)
    # 检查 cache.set 调用的 key 包含 extractor_version=2.0.0
    cache.set.assert_called_once()
    args = cache.set.call_args
    key = args.args[0]
    assert "2.0.0" in key or "extractor_version=2.0.0" in key
