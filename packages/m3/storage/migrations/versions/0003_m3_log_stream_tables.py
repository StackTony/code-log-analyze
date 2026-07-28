"""M3 — 新增 3 张表（m3_log_stream_source / m3_log_stream_event / m3_scan_trigger）。

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28

F003 spec §五 + §三：M3 三张 P0 持久化表（TTL=0 默认）。
不动 M1/M2 已有表（AC-16 字节级稳定）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "m3_log_stream_source",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("config_json", sa.Text, nullable=False),
        sa.Column("repo_id", sa.String(64), nullable=True),
        sa.Column("ingestion_status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "m3_log_stream_event",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("m3_log_stream_source.id"), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime, nullable=True),
        sa.Column("level", sa.String(16), nullable=True),
        sa.Column("log_message_template", sa.Text, nullable=True),
        sa.Column("variables_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("log_point_id", sa.String(64), nullable=True),
        sa.Column("ingested_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_m3_log_stream_event_source_id", "m3_log_stream_event", ["source_id"])
    op.create_index("ix_m3_log_stream_event_level", "m3_log_stream_event", ["level"])
    op.create_index("ix_m3_log_stream_event_log_point_id", "m3_log_stream_event", ["log_point_id"])
    op.create_index("ix_m3_log_stream_event_ingested_at", "m3_log_stream_event", ["ingested_at"])
    op.create_table(
        "m3_scan_trigger",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64),
                  sa.ForeignKey("m3_log_stream_source.id"), nullable=False),
        sa.Column("trigger_kind", sa.String(32), nullable=False),
        sa.Column("event_count", sa.Integer, nullable=False),
        sa.Column("window_start", sa.DateTime, nullable=False),
        sa.Column("window_end", sa.DateTime, nullable=False),
        sa.Column("triggered_report_id", sa.String(64), nullable=True),
        sa.Column("triggered_at", sa.DateTime, nullable=False),
        sa.Column("triggered_by", sa.String(64), nullable=False, server_default="system"),
    )
    op.create_index("ix_m3_scan_trigger_source_id", "m3_scan_trigger", ["source_id"])
    op.create_index("ix_m3_scan_trigger_triggered_report_id", "m3_scan_trigger", ["triggered_report_id"])


def downgrade() -> None:
    op.drop_table("m3_scan_trigger")
    op.drop_table("m3_log_stream_event")
    op.drop_table("m3_log_stream_source")
