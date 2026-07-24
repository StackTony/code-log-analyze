"""AuditLogger — 写 audit_log 表。"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from packages.m1.storage.models import AuditLogModel


class AuditLogger:
    def __init__(self, session: Session) -> None:
        self._session = session

    def log(
        self,
        actor: str,
        action: str,
        target_repo_id: str | None = None,
        target_log_point_ids: list[str] | None = None,
        extra: dict | None = None,
    ) -> None:
        entry = AuditLogModel(
            id=f"audit-{uuid.uuid4().hex[:12]}",
            actor=actor,
            action=action,
            target_repo_id=target_repo_id,
            target_log_point_ids_json=json.dumps(target_log_point_ids) if target_log_point_ids else None,
            timestamp=datetime.now(UTC),
            extra_json=json.dumps(extra or {}),
        )
        self._session.add(entry)
        self._session.commit()
