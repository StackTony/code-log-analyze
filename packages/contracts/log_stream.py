"""F003 M3 — LogStream 数据契约（spec §三）。

LogStreamSource: M3 数据源配置（file_tail / http_webhook）
LogStreamEvent: M3 流式日志事件（解析后，含 M1 LogPoint 关联）
ScanTrigger: M3 触发 M2 分析的记录
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class LogStreamSource:
    """M3 数据源配置（spec §三）。"""
    id: str
    kind: str                              # SOURCE_KIND_FILE_TAIL | SOURCE_KIND_HTTP_WEBHOOK
    config: dict[str, Any]                  # kind-specific
    repo_id: str | None                     # 关联代码仓（None=不匹配 M1 LogPoint）
    ingestion_status: str                  # STATUS_ACTIVE | STATUS_PAUSED | STATUS_STOPPED
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class LogStreamEvent:
    """M3 流式日志事件（解析后，spec §三）。"""
    id: str
    source_id: str
    raw_text: str
    timestamp: datetime | None
    level: str | None
    log_message_template: str | None       # 用于匹配 M1 LogPoint
    variables: dict[str, str] = field(default_factory=dict)
    log_point_id: str | None = None        # 匹配 M1 LogPoint 后填充
    ingested_at: datetime | None = None


@dataclass(frozen=True)
class ScanTrigger:
    """M3 触发 M2 分析的记录（spec §三）。"""
    id: str
    source_id: str
    trigger_kind: str                      # TRIGGER_TIME_WINDOW | TRIGGER_ANOMALY_DENSITY | TRIGGER_MANUAL
    event_count: int
    window_start: datetime
    window_end: datetime
    triggered_report_id: str | None = None  # 调 M2 后回填
    triggered_at: datetime | None = None
    triggered_by: str = "system"            # user_id (manual) 或 "system" (auto)
