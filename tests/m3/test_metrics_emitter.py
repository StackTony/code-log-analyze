"""F003 M3 — MetricsEmitter 5 个 m3_* 指标（spec §八 + AC-12）。"""
from __future__ import annotations

import pytest
from prometheus_client import CollectorRegistry, generate_latest

from packages.m3.metrics_emitter import M3MetricsEmitter


@pytest.fixture()
def registry() -> CollectorRegistry:
    """独立 CollectorRegistry（避免污染全局 registry）。"""
    return CollectorRegistry()


@pytest.fixture()
def emitter(registry: CollectorRegistry) -> M3MetricsEmitter:
    return M3MetricsEmitter(registry=registry)


class TestMetricsEmitter:
    def test_event_ingested_counter(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.observe_event_ingested(source_id="src-1", repo_id="repo-1")
        emitter.observe_event_ingested(source_id="src-1", repo_id="repo-1")
        out = generate_latest(registry).decode()
        assert "m3_events_ingested_total" in out
        assert 'source_id="src-1"' in out

    def test_trigger_counter_by_kind(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.observe_trigger(source_id="src-1", trigger_kind="time_window")
        emitter.observe_trigger(source_id="src-1", trigger_kind="manual")
        out = generate_latest(registry).decode()
        assert "m3_triggers_total" in out
        assert 'trigger_kind="time_window"' in out
        assert 'trigger_kind="manual"' in out

    def test_match_rate_gauge(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.set_match_rate(source_id="src-1", rate=0.85)
        out = generate_latest(registry).decode()
        assert "m3_match_rate" in out
        assert "0.85" in out

    def test_file_tail_lag_gauge(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.set_file_tail_lag(source_id="src-1", seconds=2.5)
        out = generate_latest(registry).decode()
        assert "m3_file_tail_lag_seconds" in out

    def test_webhook_ingest_duration_histogram(self, emitter: M3MetricsEmitter, registry: CollectorRegistry) -> None:
        emitter.observe_webhook_ingest_duration(seconds=0.05)
        out = generate_latest(registry).decode()
        assert "m3_webhook_ingest_duration_seconds" in out
