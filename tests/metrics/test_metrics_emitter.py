"""Metrics Emitter 测试 — AC-18。"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry

from packages.m1.metrics_emitter import MetricsEmitter


@pytest.fixture()
def emitter() -> MetricsEmitter:
    return MetricsEmitter(registry=CollectorRegistry())


def test_candidate_pool_size_metric(emitter: MetricsEmitter) -> None:
    emitter.inc_candidate_pool(repo_id="repo-1", delta=5)
    emitter.inc_candidate_pool(repo_id="repo-1", delta=3)
    # 取值验证
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_candidate_pool_size" in output


def test_llm_call_success_rate(emitter: MetricsEmitter) -> None:
    emitter.record_llm_call(success=True)
    emitter.record_llm_call(success=False)
    emitter.record_llm_call(success=True)
    # 应该有 counter
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_llm_call_total" in output


def test_cache_hit_rate(emitter: MetricsEmitter) -> None:
    emitter.record_cache_hit(hit=True)
    emitter.record_cache_hit(hit=False)
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_llm_cache_hit_total" in output
    # 验证 label 区分 hit=true 和 hit=false
    assert 'hit="true"' in output
    assert 'hit="false"' in output


def test_ingest_duration_histogram(emitter: MetricsEmitter) -> None:
    emitter.observe_ingest_duration(seconds=5.2)
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_ingest_repo_duration_seconds" in output


def test_log_points_extracted_total(emitter: MetricsEmitter) -> None:
    emitter.inc_log_points_extracted(language="python", delta=10)
    from prometheus_client import generate_latest
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m1_log_points_extracted_total" in output
    assert "python" in output
