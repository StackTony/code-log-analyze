"""Ingest request/response schemas（spec §三）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IngestUserAPI(BaseModel):
    """ingester 子结构。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str
    name: str


class IngestRequest(BaseModel):
    """POST /ingest body — local_path 或 github_url 二选一（spec §三）。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    local_path: str | None = None
    github_url: str | None = None
    ingester: IngestUserAPI

    @model_validator(mode="after")
    def check_at_least_one_source(self) -> IngestRequest:
        if not self.local_path and not self.github_url:
            raise ValueError("必须提供 local_path 或 github_url")
        return self


class IngestResponse(BaseModel):
    """POST /ingest response — 返回新 repo_id。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    repo_id: str = Field(min_length=1)
