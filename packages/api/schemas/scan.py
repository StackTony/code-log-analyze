"""F003 M3 — Pydantic v2 schemas（spec §六）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RegisterSourceRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: str = Field(..., description="file_tail | http_webhook")
    config: dict[str, Any]
    repo_id: str | None = None


class LogStreamSourceAPI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
    kind: str
    config: dict[str, Any]
    repo_id: str | None
    ingestion_status: str
    created_at: datetime
    updated_at: datetime


class IngestEventRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    raw_text: str


class LogStreamEventAPI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
    source_id: str
    raw_text: str
    timestamp: datetime | None
    level: str | None
    log_message_template: str | None
    variables: dict[str, str]
    log_point_id: str | None
    ingested_at: datetime


class ScanTriggerAPI(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
    source_id: str
    trigger_kind: str
    event_count: int
    window_start: datetime
    window_end: datetime
    triggered_report_id: str | None
    triggered_at: datetime
    triggered_by: str


class AnalysisReportStubAPI(BaseModel):
    """M3 scan_now 返回 M2 AnalysisReport stub（仅 id 字段，M2 完整 schema 在 packages.api.schemas.analysis）。"""

    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)
    id: str
