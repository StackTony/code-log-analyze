"""F003 M3 — Storage 三张表（spec §五 + AC-14）。

复用 M2 模式（独立 Base metadata，避免与 M1 Base 冲突）。
JSON 字段用 _json 后缀（SQLite 不原生支持 JSON，用 Text 存）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """M3 SQLAlchemy Base（独立 metadata）。"""
    pass


class LogStreamSourceModel(Base):
    """M3 数据源配置表（spec §三 LogStreamSource）。"""
    __tablename__ = "m3_log_stream_source"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # file_tail | http_webhook
    config_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-encoded dict
    repo_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class LogStreamEventModel(Base):
    """M3 流式日志事件表（spec §三 LogStreamEvent）。"""
    __tablename__ = "m3_log_stream_event"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("m3_log_stream_source.id"), nullable=False,
        index=True,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    level: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    log_message_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    variables_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    log_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class ScanTriggerModel(Base):
    """M3 触发记录表（spec §三 ScanTrigger）。"""
    __tablename__ = "m3_scan_trigger"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("m3_log_stream_source.id"), nullable=False,
        index=True,
    )
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False)  # time_window | anomaly_density | manual
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    triggered_report_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    triggered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
