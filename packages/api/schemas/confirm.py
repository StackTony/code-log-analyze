"""Confirm / Revoke / CallContext request schemas（spec §三）。"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ConfirmRequest(BaseModel):
    """POST /confirm/{repo_id} body。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    log_point_ids: list[str] = Field(min_length=1)
    confirmer: str


class RevokeRequest(BaseModel):
    """POST /revoke/{repo_id} body。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    log_point_ids: list[str] = Field(min_length=1)
    revoker: str


class CallContextRequest(BaseModel):
    """POST /call-context/{repo_id} body — POST body 传 function_signature（云长 OQ-1 修订）。"""
    model_config = ConfigDict(strict=True, extra="forbid")

    function_signature: str
