"""M2 — 新增 3 张表（analysis_report / deep_analysis / log_entry）。

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-27

F002 spec §五 + §三：M2 三张 P0 持久化表（TTL=0 默认）。
不动 M1 已有 4 张表（AC-18 字节级稳定）。
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # analysis_report: Phase 1 全量分析报告（M2 主输出）
    op.create_table(
        "analysis_report",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("repo_id", sa.String(64), nullable=True, index=True),
        sa.Column("log_source", sa.Text, nullable=False),
        sa.Column("log_line_count", sa.Integer, nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(128), nullable=False),
        sa.Column("system_summary", sa.Text, nullable=False),
        sa.Column("anomaly_localization_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("error_correlation_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("duration_seconds", sa.Float, nullable=False),
        sa.Column("token_usage_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("ingestion_status", sa.String(16), nullable=False, server_default="draft"),
    )
    op.create_index(
        "ix_analysis_report_repo_status",
        "analysis_report", ["repo_id", "ingestion_status"],
    )

    # deep_analysis: Phase 2 深入分析记录
    op.create_table(
        "deep_analysis",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("report_id", sa.String(64), nullable=False, index=True),
        sa.Column("line_ids_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("log_point_ids_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("call_contexts_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("root_cause_hypothesis", sa.Text, nullable=False),
        sa.Column("fix_suggestion", sa.Text, nullable=True),
        sa.Column("related_evidence_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(128), nullable=False),
        sa.Column("iteration", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_record_id", sa.String(64), nullable=True, index=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("token_usage_json", sa.Text, nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_deep_analysis_report_iteration",
        "deep_analysis", ["report_id", "iteration"],
    )

    # log_entry: 解析后的日志条目
    op.create_table(
        "log_entry",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("report_id", sa.String(64), nullable=True, index=True),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("level", sa.String(16), nullable=True, index=True),
        sa.Column("log_message_template", sa.Text, nullable=True, index=True),
        sa.Column("variables_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("source_file", sa.String(512), nullable=True),
        sa.Column("source_line", sa.Integer, nullable=True),
    )
    op.create_index(
        "ix_log_entry_report_level",
        "log_entry", ["report_id", "level"],
    )


def downgrade() -> None:
    op.drop_index("ix_log_entry_report_level", table_name="log_entry")
    op.drop_table("log_entry")
    op.drop_index("ix_deep_analysis_report_iteration", table_name="deep_analysis")
    op.drop_table("deep_analysis")
    op.drop_index("ix_analysis_report_repo_status", table_name="analysis_report")
    op.drop_table("analysis_report")
