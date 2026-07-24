"""Initial migration — 4 张表。

Revision ID: 0001
Revises:
Create Date: 2026-07-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "log_point",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("repo_id", sa.String(64), nullable=False, index=True),
        sa.Column("git_commit_sha", sa.String(64), nullable=False),
        sa.Column("extractor_version", sa.String(16), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False),
        sa.Column("function_signature", sa.Text, nullable=False),
        sa.Column("line_start", sa.Integer, nullable=False),
        sa.Column("line_end", sa.Integer, nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("log_level", sa.String(16), nullable=False),
        sa.Column("log_message_template", sa.Text, nullable=False),
        sa.Column("log_message_variables", sa.JSON, nullable=False),
        sa.Column("framework_hint", sa.String(32), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("enclosing_class", sa.String(256), nullable=True),
        sa.Column("call_chain_to_entry", sa.JSON, nullable=False),
        sa.Column("enclosing_community", sa.String(64), nullable=True),
        sa.Column("evidence_refs_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("llm_hypothesis_json", sa.Text, nullable=True),
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_top_n", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("ingestion_status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_log_point_repo_file_line", "log_point",
                    ["repo_id", "file_path", "line_start"], unique=True)

    # CandidateStagingModel: 23 字段与 LogPointModel 对齐（云长 MF-4 修复）
    op.create_table(
        "candidate_staging",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("repo_id", sa.String(64), nullable=False, index=True),
        # 完整 LogPoint 字段
        sa.Column("git_commit_sha", sa.String(64), nullable=False),
        sa.Column("extractor_version", sa.String(16), nullable=False),
        sa.Column("file_path", sa.String(512), nullable=False, index=True),
        sa.Column("function_signature", sa.String(512), nullable=False),
        sa.Column("line_start", sa.Integer, nullable=False),
        sa.Column("line_end", sa.Integer, nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("log_level", sa.String(16), nullable=False),
        sa.Column("log_message_template", sa.Text, nullable=False),
        sa.Column("log_message_variables_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("framework_hint", sa.String(32), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column("enclosing_class", sa.String(256), nullable=True),
        sa.Column("call_chain_to_entry_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("enclosing_community", sa.String(64), nullable=True),
        sa.Column("evidence_refs_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("llm_hypothesis_json", sa.Text, nullable=True),
        # 频次 + 状态
        sa.Column("occurrence_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_top_n", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("ingestion_status", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "repo_ingest_lock",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("repo_id", sa.String(64), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("ingester", sa.String(64), nullable=False),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("actor", sa.String(64), nullable=False, index=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_repo_id", sa.String(64), nullable=True, index=True),
        sa.Column("target_log_point_ids_json", sa.Text, nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("extra_json", sa.Text, nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("repo_ingest_lock")
    op.drop_table("candidate_staging")
    op.drop_index("ix_log_point_repo_file_line", table_name="log_point")
    op.drop_table("log_point")
