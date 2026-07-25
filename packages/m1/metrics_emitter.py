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


class MetricsEmitter:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._candidate_pool = Gauge(
            "m1_candidate_pool_size",
            "候选池规模", labelnames=["repo_id"],
            registry=self._registry,
        )
        self._llm_call = Counter(
            "m1_llm_call_total", "LLM 调用次数",
            labelnames=["result"], registry=self._registry,
        )
        self._cache_hit = Counter(
            "m1_llm_cache_hit_total", "LLM 缓存命中",
            labelnames=["hit"], registry=self._registry,
        )
        self._ingest_duration = Histogram(
            "m1_ingest_repo_duration_seconds",
            "ingest_repo 耗时", registry=self._registry,
        )
        self._extracted = Counter(
            "m1_log_points_extracted_total",
            "已提取 LogPoint 总数", labelnames=["language"],
            registry=self._registry,
        )

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
