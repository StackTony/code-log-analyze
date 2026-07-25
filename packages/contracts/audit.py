"""AuditLog dataclass（spec 第 319-329 行）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class AuditLog:
    id: str
    actor: str  # user_id
    action: str  # ACTION_* 常量
    target_repo_id: str | None
    target_log_point_ids: list[str] | None
    timestamp: datetime
    extra: dict = field(default_factory=dict)
