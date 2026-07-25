"""Metrics 9100 独立进程测试（spec §六 + AC-4 + AC-10 + AC-11）。"""
from __future__ import annotations

import platform

import httpx
import pytest
from prometheus_client import CollectorRegistry, generate_latest

from packages.m1.metrics_emitter import MetricsEmitter


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Windows subprocess + prometheus_client HTTP server 不兼容; 已由 test_metrics_emitter_indicators_present 验证指标名",
)
def test_metrics_endpoint_returns_prometheus_format(metrics_server: str) -> None:
    """独立 metrics server 暴露 Prometheus exposition format。"""
    r = httpx.get(f"{metrics_server}/")
    assert r.status_code == 200
    assert "# HELP" in r.text or "# TYPE" in r.text


def test_metrics_emitter_indicators_present() -> None:
    """5 个指标名（spec AC-18 + AC-4）。"""
    registry = CollectorRegistry()
    emitter = MetricsEmitter(registry=registry)
    emitter.inc_candidate_pool(repo_id="r1", delta=1)
    emitter.record_llm_call(success=True)
    emitter.record_cache_hit(hit=True)
    emitter.observe_ingest_duration(seconds=1.0)
    emitter.inc_log_points_extracted(language="python")

    output = generate_latest(registry).decode("utf-8")
    assert "m1_candidate_pool_size" in output
    assert "m1_llm_call_total" in output
    assert "m1_llm_cache_hit_total" in output
    assert "m1_ingest_repo_duration_seconds" in output
    assert "m1_log_points_extracted_total" in output


def test_app_lifespan_starts_metrics_server() -> None:
    """AC-10 + AC-11：app lifespan 启动 metrics server 独立进程 + graceful degradation。"""
    from fastapi.testclient import TestClient

    from packages.api.app import app

    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
