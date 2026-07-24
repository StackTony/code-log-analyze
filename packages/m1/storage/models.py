"""SQLAlchemy ORM models — LogPoint 主表 / 候选池 / 锁 / 审计（spec 第 100-181 行 + 319-329 行）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _posix_path(value: str) -> str:
    """存储前统一转 POSIX 风格（AC-15）。"""
    return value.replace("\\", "/")


class LogPointModel(Base):
    __tablename__ = "log_point"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(64), index=True)
    git_commit_sha: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(16))
    file_path: Mapped[str] = mapped_column(String(512))  # 存时转 POSIX
    function_signature: Mapped[str] = mapped_column(Text)
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(16))
    log_level: Mapped[str] = mapped_column(String(16))
    log_message_template: Mapped[str] = mapped_column(Text)
    log_message_variables: Mapped[list[str]] = mapped_column(JSON)
    framework_hint: Mapped[str] = mapped_column(String(32))
    confidence_score: Mapped[float] = mapped_column(Float)
    enclosing_class: Mapped[str | None] = mapped_column(String(256), nullable=True)
    call_chain_to_entry: Mapped[list[str]] = mapped_column(JSON)
    enclosing_community: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    llm_hypothesis_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    is_top_n: Mapped[bool] = mapped_column(default=False)
    ingestion_status: Mapped[str] = mapped_column(String(16), default="candidate")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def __init__(self, **kwargs: Any) -> None:
        # file_path 统一 POSIX（AC-15）
        if "file_path" in kwargs:
            kwargs["file_path"] = _posix_path(kwargs["file_path"])
        super().__init__(**kwargs)


class CandidateStagingModel(Base):
    """候选池 — 不进主表，用户 confirm 后才入 log_point。

    云长 MF-4 修复：候选池必须存完整 LogPoint 字段，否则 list_candidates()
    返回假数据，用户筛选 UI 看不到真实日志内容无法做决策（违反 C-5）。
    方案 A：字段级可查询、可索引、可过滤，比 JSON blob 更适合企业内部平台。
    """
    __tablename__ = "candidate_staging"

    # 主键 + 仓维度索引
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(64), index=True)

    # 完整 LogPoint 字段（与 LogPointModel 对齐，confirm 时复制到主表）
    git_commit_sha: Mapped[str] = mapped_column(String(64))
    extractor_version: Mapped[str] = mapped_column(String(16))
    file_path: Mapped[str] = mapped_column(String(512), index=True)
    function_signature: Mapped[str] = mapped_column(String(512))
    line_start: Mapped[int] = mapped_column(Integer)
    line_end: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(16))
    log_level: Mapped[str] = mapped_column(String(16))
    log_message_template: Mapped[str] = mapped_column(Text)
    log_message_variables_json: Mapped[str] = mapped_column(Text, default="[]")
    framework_hint: Mapped[str] = mapped_column(String(32))
    confidence_score: Mapped[float] = mapped_column(Float)
    enclosing_class: Mapped[str | None] = mapped_column(String(256), nullable=True)
    call_chain_to_entry_json: Mapped[str] = mapped_column(Text, default="[]")
    enclosing_community: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_refs_json: Mapped[str] = mapped_column(Text, default="[]")
    llm_hypothesis_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 频次 + 状态
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    is_top_n: Mapped[bool] = mapped_column(default=False)
    ingestion_status: Mapped[str] = mapped_column(String(16), default="candidate")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RepoIngestLockModel(Base):
    __tablename__ = "repo_ingest_lock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repo_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))  # running/done/failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingester: Mapped[str] = mapped_column(String(64))


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    target_repo_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    target_log_point_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}")
