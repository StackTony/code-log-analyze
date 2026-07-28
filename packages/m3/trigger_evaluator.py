"""F003 M3 — TriggerEvaluator（spec §二 + AC-5/6）。

两种触发判定（priority：anomaly_density > time_window）：
- anomaly_density：error 占比 > 阈值（默认 30%）
- time_window：累积事件数 ≥ 阈值（默认 1000 条 / 5 分钟）

不调 M2，不做分析——只判定"该不该 trigger"。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from packages.contracts.enums import (
    TRIGGER_ANOMALY_DENSITY,
    TRIGGER_TIME_WINDOW,
)
from packages.m3.storage.repository import M3Repository


@dataclass(frozen=True)
class TriggerDecision:
    """TriggerEvaluator.evaluate 返回值（spec §二 TriggerDecision）。"""

    should_trigger: bool
    trigger_kind: str | None
    event_count: int
    window_start: datetime
    window_end: datetime


class TriggerEvaluator:
    """M3 触发判定器（spec §二 + AC-5/6）。"""

    def __init__(
        self,
        repository: M3Repository,
        time_window_event_count: int = 1000,
        time_window_seconds: int = 300,
        anomaly_density_threshold: float = 0.30,
    ) -> None:
        self._repo = repository
        self._count_threshold = time_window_event_count
        self._time_window = timedelta(seconds=time_window_seconds)
        self._density_threshold = anomaly_density_threshold

    def evaluate(self, source_id: str) -> TriggerDecision:
        """判定 source 是否应触发扫描。

        Returns:
            TriggerDecision（should_trigger + trigger_kind + 统计上下文）
        """
        now = datetime.now(UTC)
        window_start = now - self._time_window
        window_end = now

        counts_by_level = self._repo.count_events_by_level(
            source_id, window_start=window_start, window_end=window_end,
        )
        total = sum(counts_by_level.values())
        # anomaly = ERROR + CRITICAL（spec §二 anomaly_density 定义）
        error_count = (
            counts_by_level.get("ERROR", 0)
            + counts_by_level.get("CRITICAL", 0)
        )

        # 优先 anomaly_density：异常密度反映紧迫性，优先于纯计数
        if total > 0 and (error_count / total) > self._density_threshold:
            return TriggerDecision(
                should_trigger=True,
                trigger_kind=TRIGGER_ANOMALY_DENSITY,
                event_count=total,
                window_start=window_start,
                window_end=window_end,
            )

        # 其次 time_window：累积事件达阈值
        if total >= self._count_threshold:
            return TriggerDecision(
                should_trigger=True,
                trigger_kind=TRIGGER_TIME_WINDOW,
                event_count=total,
                window_start=window_start,
                window_end=window_end,
            )

        # 未触发
        return TriggerDecision(
            should_trigger=False,
            trigger_kind=None,
            event_count=total,
            window_start=window_start,
            window_end=window_end,
        )
