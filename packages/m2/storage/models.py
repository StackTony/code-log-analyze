"""F002 M2 — SQLAlchemy ORM models（spec §五 + §三）。

三张表（继承 M1 Base，保证 `Base.metadata.create_all()` 一把建所有表）：
  - analysis_report：Phase 1 全量分析报告（P0 持久化，TTL=0）
  - deep_analysis：Phase 2 深入分析记录（P0 持久化，TTL=0）
  - log_entry：解析后的日志条目（P0 持久化，TTL=0）

设计原则（AC-18 字节级稳定）：
  - 不修改 M1 已有 4 张表（log_point / candidate_staging / repo_ingest_lock / audit_log）
  - 复杂结构字段（Anomaly/ErrorChain/CallContext/CaseRef）用 JSON Text 存
  - dataclass ↔ JSON 转换在 service 层做（不在 model 层做）

P0 持久化铁律（AC-16）：所有表 TTL=0 默认持久化，不加 TTL 字段。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from packages.m1.storage.models import Base  # 复用 M1 Base，保证 metadata 共享


class AnalysisReportModel(Base):
    """Phase 1 全量分析报告 — M2 主输出（spec §三 + AC-16）。

    P0 持久化：用户可见产物，TTL=0 默认持久化。
    """
    __tablename__ = "analysis_report"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    log_source: Mapped[str] = mapped_column(Text, nullable=False)
    log_line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # 三类核心信息（系统行为总结 + 异常定位 + 错误关联）
    system_summary: Mapped[str] = mapped_column(Text, nullable=False)
    anomaly_localization_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error_correlation_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 元数据
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    token_usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    ingestion_status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class DeepAnalysisModel(Base):
    """Phase 2 深入分析记录（spec §三 + AC-16）。

    P0 持久化：用户可见产物，TTL=0 默认持久化。
    迭代性：iteration 递增 + parent_record_id 链（累积上下文）。
    """
    __tablename__ = "deep_analysis"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # 选定日志条目 + 关联 LogPoint
    line_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    log_point_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 上下文快照（M1 get_call_context 结果）
    call_contexts_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # LLM 输出
    root_cause_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    fix_suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    related_evidence_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 元数据
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    iteration: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_record_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    token_usage_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class LogEntryModel(Base):
    """解析后的日志条目（spec §三 + AC-16）。

    P0 持久化：日志原文 + 解析字段都要保留，用户可见可追溯。
    用于 Phase 2 选 line 时回查原始日志内容。
    """
    __tablename__ = "log_entry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    report_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    level: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    log_message_template: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    variables_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    source_file: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_line: Mapped[int | None] = mapped_column(Integer, nullable=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
