"""Unit E: Metrics Emitter — Prometheus 指标（AC-18）。"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import REGISTRY

# Module-level singletons to avoid re-registration
_metrics_singleton: dict[str, object] = {}


class MetricsEmitter:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        # Use global singletons to avoid Prometheus re-registration errors
        global _metrics_singleton

        if "candidate_pool" not in _metrics_singleton:
            _metrics_singleton["candidate_pool"] = Gauge(
                "m1_candidate_pool_size",
                "候选池规模", labelnames=["repo_id"],
                registry=self._registry,
            )
        self._candidate_pool = _metrics_singleton["candidate_pool"]

        if "llm_call" not in _metrics_singleton:
            _metrics_singleton["llm_call"] = Counter(
                "m1_llm_call_total", "LLM 调用次数",
                labelnames=["result"], registry=self._registry,
            )
        self._llm_call = _metrics_singleton["llm_call"]

        if "cache_hit" not in _metrics_singleton:
            _metrics_singleton["cache_hit"] = Counter(
                "m1_llm_cache_hit_total", "LLM 缓存命中",
                labelnames=["hit"], registry=self._registry,
            )
        self._cache_hit = _metrics_singleton["cache_hit"]

        if "ingest_duration" not in _metrics_singleton:
            _metrics_singleton["ingest_duration"] = Histogram(
                "m1_ingest_repo_duration_seconds",
                "ingest_repo 耗时", registry=self._registry,
            )
        self._ingest_duration = _metrics_singleton["ingest_duration"]

        if "extracted" not in _metrics_singleton:
            _metrics_singleton["extracted"] = Counter(
                "m1_log_points_extracted_total",
                "已提取 LogPoint 总数", labelnames=["language"],
                registry=self._registry,
            )
        self._extracted = _metrics_singleton["extracted"]

    def inc_candidate_pool(self, repo_id: str, delta: int = 1) -> None:
        self._candidate_pool.labels(repo_id=repo_id).inc(delta)

    def record_llm_call(self, success: bool) -> None:
        self._llm_call.labels(result="success" if success else "failure").inc()

    def record_cache_hit(self, hit: bool) -> None:
        self._cache_hit.labels(hit="true" if hit else "false").inc()

    def observe_ingest_duration(self, seconds: float) -> None:
        self._ingest_duration.observe(seconds)

    def inc_log_points_extracted(self, language: str, delta: int = 1) -> None:
        self._extracted.labels(language=language).inc(delta)

    def render(self) -> str:
        return generate_latest(self._registry).decode("utf-8")
