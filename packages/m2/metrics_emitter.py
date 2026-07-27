"""F002 M2 — Prometheus 指标 emitter（spec §八 + AC-14）。

5 个 m2_* 指标（复用 prometheus_client default REGISTRY，与 M1 共存）：
  - m2_analysis_report_total (counter, label repo_id)
    每次 Phase 1 完成 AnalysisReport 时 +1
  - m2_deep_analysis_total (counter, label repo_id)
    每次 Phase 2 完成 DeepAnalysisRecord 时 +1
  - m2_llm_call_duration_seconds (histogram, label phase)
    LLM 调用耗时，按 phase1/phase2 分维度
  - m2_llm_cost_usd_total (counter)
    累计 LLM 成本（TokenUsage.total_cost_usd 累加）
  - m2_log_point_match_rate (gauge)
    Phase 1 日志条目匹配 M1 LogPoint 的比例（每次 analyze_logs 更新）
"""
from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.core import REGISTRY


class M2MetricsEmitter:
    """M2 Prometheus 指标 emitter（spec §八 + AC-14）。

    与 M1 MetricsEmitter 并存（不同 metric name，共享 default REGISTRY）。
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self._registry = registry or REGISTRY
        self._analysis_report = Counter(
            "m2_analysis_report_total",
            "Phase 1 AnalysisReport 生成总数",
            labelnames=["repo_id"],
            registry=self._registry,
        )
        self._deep_analysis = Counter(
            "m2_deep_analysis_total",
            "Phase 2 DeepAnalysisRecord 生成总数",
            labelnames=["repo_id"],
            registry=self._registry,
        )
        self._llm_call_duration = Histogram(
            "m2_llm_call_duration_seconds",
            "LLM 调用耗时（秒）",
            labelnames=["phase"],
            registry=self._registry,
        )
        self._llm_cost = Counter(
            "m2_llm_cost_usd_total",
            "累计 LLM 成本（USD）",
            registry=self._registry,
        )
        self._match_rate = Gauge(
            "m2_log_point_match_rate",
            "Phase 1 日志条目匹配 M1 LogPoint 的比例",
            registry=self._registry,
        )

    # ---- Counters ----

    def inc_analysis_report(self, repo_id: str, delta: int = 1) -> None:
        """Phase 1 完成 +1。"""
        self._analysis_report.labels(repo_id=repo_id).inc(delta)

    def inc_deep_analysis(self, repo_id: str, delta: int = 1) -> None:
        """Phase 2 完成 +1。"""
        self._deep_analysis.labels(repo_id=repo_id).inc(delta)

    def inc_llm_cost(self, usd: float) -> None:
        """累计 LLM 成本（TokenUsage.total_cost_usd）。"""
        self._llm_cost.inc(usd)

    # ---- Histogram ----

    def observe_llm_call_duration(self, phase: str, seconds: float) -> None:
        """记录 LLM 调用耗时（phase=phase1/phase2）。"""
        self._llm_call_duration.labels(phase=phase).observe(seconds)

    # ---- Gauge ----

    def set_log_point_match_rate(self, rate: float) -> None:
        """设置 Phase 1 LogPoint 匹配率（clamp 到 [0.0, 1.0]）。

        rate = matched_log_points / total_log_entries
        无 repo_id 时为 0.0（log_point_index 未实现或 LogPoint 全 fallback None）
        """
        clamped = max(0.0, min(1.0, rate))
        self._match_rate.set(clamped)

    # ---- Render ----

    def render(self) -> str:
        """Prometheus exposition 格式输出（spec §八 + AC-14 端口 9464 抓取）。"""
        return generate_latest(self._registry).decode("utf-8")
