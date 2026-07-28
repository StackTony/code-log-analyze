"""F003 M3 — MetricsEmitter 5 个 m3_* 指标（spec §八 + AC-12）。

模式复用 M2 MetricsEmitter（prometheus_client Counter/Gauge/Histogram）。
"""
from __future__ import annotations

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
)


class M3MetricsEmitter:
    """M3 metrics 指标发射器（spec §八）。"""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._reg = registry or REGISTRY
        self._events_ingested = Counter(
            name="m3_events_ingested_total",
            documentation="Total events ingested by source",
            labelnames=["source_id", "repo_id"],
            registry=self._reg,
        )
        self._triggers = Counter(
            name="m3_triggers_total",
            documentation="Total M2 analyze triggers by source and kind",
            labelnames=["source_id", "trigger_kind"],
            registry=self._reg,
        )
        self._match_rate = Gauge(
            name="m3_match_rate",
            documentation="LogStreamEvent match rate to M1 LogPoint by source",
            labelnames=["source_id"],
            registry=self._reg,
        )
        self._file_tail_lag = Gauge(
            name="m3_file_tail_lag_seconds",
            documentation="file_tail lag in seconds by source",
            labelnames=["source_id"],
            registry=self._reg,
        )
        self._webhook_ingest_duration = Histogram(
            name="m3_webhook_ingest_duration_seconds",
            documentation="HTTP webhook ingest duration",
            labelnames=[],  # global
            registry=self._reg,
        )

    def observe_event_ingested(self, source_id: str, repo_id: str | None) -> None:
        self._events_ingested.labels(
            source_id=source_id, repo_id=repo_id or "none",
        ).inc()

    def observe_trigger(self, source_id: str, trigger_kind: str) -> None:
        self._triggers.labels(
            source_id=source_id, trigger_kind=trigger_kind,
        ).inc()

    def set_match_rate(self, source_id: str, rate: float) -> None:
        self._match_rate.labels(source_id=source_id).set(rate)

    def set_file_tail_lag(self, source_id: str, seconds: float) -> None:
        self._file_tail_lag.labels(source_id=source_id).set(seconds)

    def observe_webhook_ingest_duration(self, seconds: float) -> None:
        self._webhook_ingest_duration.observe(seconds)
