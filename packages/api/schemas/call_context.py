"""CallContext + CaseRef schemas（spec §九 + 云长 C-3 修订）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from packages.api.schemas.log_point import LogPointAPI


class CaseRefAPI(BaseModel):
    """历史案例嵌套 schema。"""
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)

    case_id: str
    repo_id: str
    file_path: str
    function_signature: str
    log_template: str
    resolved_at: datetime
    resolution_summary: str
    resolution_diff_url: str | None = None


class CallContextAPI(BaseModel):
    """get_call_context 返回值。"""
    model_config = ConfigDict(strict=True, extra="forbid", from_attributes=True)

    function_signature: str
    callers: list[str]
    callees: list[str]
    enclosing_community: str | None = None
    related_log_points: list[LogPointAPI]
    evidence_refs: list[dict[str, Any]]  # CaseRef dict
