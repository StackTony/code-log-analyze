"""F002 M2 — MetricsEmitter 测试（spec §八 + AC-14）。

5 个 m2_* 指标验证：
  - m2_analysis_report_total (counter, label repo_id)
  - m2_deep_analysis_total (counter, label repo_id)
  - m2_llm_call_duration_seconds (histogram, label phase)
  - m2_llm_cost_usd_total (counter, 累计 LLM 成本)
  - m2_log_point_match_rate (gauge, Phase 1 匹配率)
"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from packages.m2.metrics_emitter import M2MetricsEmitter


@pytest.fixture()
def emitter() -> M2MetricsEmitter:
    """独立 registry 避免全局污染。"""
    return M2MetricsEmitter(registry=CollectorRegistry())


def test_analysis_report_total(emitter: M2MetricsEmitter) -> None:
    """m2_analysis_report_total counter + repo_id 标签。"""
    emitter.inc_analysis_report(repo_id="repo-1")
    emitter.inc_analysis_report(repo_id="repo-1")
    emitter.inc_analysis_report(repo_id="repo-2")
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m2_analysis_report_total" in output
    assert 'repo_id="repo-1"' in output
    assert 'repo_id="repo-2"' in output


def test_deep_analysis_total(emitter: M2MetricsEmitter) -> None:
    """m2_deep_analysis_total counter + repo_id 标签。"""
    emitter.inc_deep_analysis(repo_id="repo-1", delta=2)
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m2_deep_analysis_total" in output
    assert 'repo_id="repo-1"' in output


def test_llm_call_duration_histogram(emitter: M2MetricsEmitter) -> None:
    """m2_llm_call_duration_seconds histogram + phase 标签。"""
    emitter.observe_llm_call_duration(phase="phase1", seconds=1.2)
    emitter.observe_llm_call_duration(phase="phase2", seconds=3.5)
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m2_llm_call_duration_seconds" in output
    assert 'phase="phase1"' in output
    assert 'phase="phase2"' in output


def test_llm_cost_usd_total(emitter: M2MetricsEmitter) -> None:
    """m2_llm_cost_usd_total counter — 累计 LLM 成本。"""
    emitter.inc_llm_cost(usd=0.02)
    emitter.inc_llm_cost(usd=0.05)
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m2_llm_cost_usd_total" in output


def test_log_point_match_rate_gauge(emitter: M2MetricsEmitter) -> None:
    """m2_log_point_match_rate gauge — Phase 1 匹配率。"""
    emitter.set_log_point_match_rate(rate=0.75)
    output = generate_latest(emitter._registry).decode("utf-8")
    assert "m2_log_point_match_rate" in output


def test_set_log_point_match_rate_clamped_to_0_1(emitter: M2MetricsEmitter) -> None:
    """匹配率 clamp 到 [0.0, 1.0]。"""
    emitter.set_log_point_match_rate(rate=1.5)
    output = generate_latest(emitter._registry).decode("utf-8")
    # 验证 gauge 值为 1.0（clamped）
    # Prometheus exposition 格式：m2_log_point_match_rate 1.0
    assert "m2_log_point_match_rate 1.0" in output

    emitter2 = M2MetricsEmitter(registry=CollectorRegistry())
    emitter2.set_log_point_match_rate(rate=-0.2)
    output2 = generate_latest(emitter2._registry).decode("utf-8")
    assert "m2_log_point_match_rate 0.0" in output2
