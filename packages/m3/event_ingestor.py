"""F003 M3 — EventIngestor（spec §十 + AC-3/4）。

复用 M2 LogParser + LogPointMatcher，不重新实现解析/匹配逻辑。
仅做：raw_text → LogEntry → 匹配 M1 LogPoint → LogStreamEvent 持久化。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from packages.contracts.enums import ACTION_M3_INGEST_EVENT
from packages.contracts.log_stream import LogStreamEvent
from packages.m1.audit_log import AuditLogger
from packages.m2.log_parser import LogParser
from packages.m2.log_point_matcher import LogPointMatcher
from packages.m3.storage.repository import M3Repository


class EventIngestor:
    """M3 流式日志事件入库（spec §二 EventIngestor + §十 关联机制）。"""

    def __init__(
        self,
        repository: M3Repository,
        log_parser: LogParser,
        log_point_matcher: LogPointMatcher,
        audit: AuditLogger,
    ) -> None:
        self._repo = repository
        self._parser = log_parser
        self._matcher = log_point_matcher
        self._audit = audit

    def ingest(self, source_id: str, raw_text: str) -> LogStreamEvent:
        """解析 + 匹配 + 持久化单条日志事件。

        Returns:
            LogStreamEvent（含 log_point_id 或 None）
        """
        # M2 LogParser 解析 raw_text → list[LogEntry]
        log_entries = self._parser.parse(raw_text)
        # M3 单条 ingest（取第一条；batch 是 future work）
        entry = log_entries[0] if log_entries else None

        # 字段提取（来自 M2 LogEntry）
        timestamp = entry.timestamp if entry else None
        level = entry.level if entry else None
        template = entry.log_message_template if entry else None
        variables = entry.variables if entry else {}

        # M2 LogPointMatcher.match 接受 list[LogEntry] 返回 list[MatchResult]
        # 取第一条 result 的 log_point（None = 未匹配）
        log_point_id: str | None = None
        if entry is not None:
            results = self._matcher.match([entry])
            if results and results[0].log_point is not None:
                log_point_id = results[0].log_point.id

        # 构造 LogStreamEvent
        now = datetime.now(UTC)
        event = LogStreamEvent(
            id=f"evt-{uuid.uuid4().hex[:12]}",
            source_id=source_id,
            raw_text=raw_text,
            timestamp=timestamp,
            level=level,
            log_message_template=template,
            variables=variables,
            log_point_id=log_point_id,
            ingested_at=now,
        )

        # 持久化
        self._repo.save_event(event)

        # 审计（AuditLogger.log 签名：actor, action, target_repo_id, target_log_point_ids, extra）
        self._audit.log(
            actor="system",
            action=ACTION_M3_INGEST_EVENT,
            extra={"source_id": source_id, "event_id": event.id, "log_point_id": log_point_id},
        )

        return event
