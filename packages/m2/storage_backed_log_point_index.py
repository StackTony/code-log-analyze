"""F002 M2 — StorageBackedLogPointIndex（review OQ-2 修复）。

从 M1 LogPointModel 主表（confirmed 状态）建索引：
  - 初始化时预扫全表 → 对每条 log_message_template 归一化 + sha256 哈希
  - 内存 dict: template_hash → LogPoint dataclass
  - lookup_by_template_hash O(1)

设计选择：
  - 内存索引而非 DB 索引：M1 LogPoint 主表无 template_hash 列，
    且 M1 spec §三不允许 F002 加列（AC-18 字节级稳定）。
    预扫内存是 trade-off：repo 内 LogPoint 一般几百到几千行，可接受。
  - confirmed 状态过滤：只索引已 confirm 的 LogPoint，
    防止 candidate 池污染（M1 spec §五 ingestion_status 语义）。
  - repo_id 维度：单 repo 索引，避免跨仓污染。
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.log_point import LogPoint
from packages.m1.storage.models import LogPointModel
from packages.m1.unit_d_candidate_staging import _dict_to_caseref, _json_to_llm_hyp
from packages.m2.log_point_matcher import (
    LogPointIndex,
    _hash_signature,
    _normalize_to_signature,
)

if TYPE_CHECKING:
    pass


class StorageBackedLogPointIndex(LogPointIndex):
    """从 M1 LogPointModel 主表（confirmed）建索引（review OQ-2）。"""

    def __init__(self, repo_id: str, session: Session) -> None:
        self._repo_id = repo_id
        self._index: dict[str, LogPoint] = {}
        self._build_index(session)

    def _build_index(self, session: Session) -> None:
        """预扫 confirmed LogPoint 主表，归一化 + 哈希建索引。"""
        stmt = select(LogPointModel).where(
            LogPointModel.repo_id == self._repo_id,
            LogPointModel.ingestion_status == "confirmed",
        )
        for row in session.scalars(stmt).all():
            sig = _normalize_to_signature(row.log_message_template)
            h = _hash_signature(sig)
            # 同 hash 多条时取第一条（罕见，等价模板）
            if h not in self._index:
                self._index[h] = self._model_to_log_point(row)

    @staticmethod
    def _model_to_log_point(r: LogPointModel) -> LogPoint:
        """ORM Model → LogPoint dataclass（复用 M1 unit_d 的转换逻辑）。"""
        return LogPoint(
            id=r.id, repo_id=r.repo_id, git_commit_sha=r.git_commit_sha,
            extractor_version=r.extractor_version, file_path=r.file_path,
            function_signature=r.function_signature,
            line_start=r.line_start, line_end=r.line_end,
            language=r.language, log_level=r.log_level,
            log_message_template=r.log_message_template,
            log_message_variables=r.log_message_variables,
            framework_hint=r.framework_hint, confidence_score=r.confidence_score,
            enclosing_class=r.enclosing_class,
            call_chain_to_entry=r.call_chain_to_entry,
            enclosing_community=r.enclosing_community,
            evidence_refs=[
                _dict_to_caseref(d)
                for d in json.loads(r.evidence_refs_json)
            ] if r.evidence_refs_json else [],
            llm_hypothesis=_json_to_llm_hyp(r.llm_hypothesis_json),
            occurrence_count=r.occurrence_count, is_top_n=r.is_top_n,
            ingestion_status=r.ingestion_status,
            first_seen_at=r.first_seen_at, last_seen_at=r.last_seen_at,
        )

    def lookup_by_template_hash(self, template_hash: str) -> LogPoint | None:
        """O(1) 内存查 LogPoint，未命中返回 None。"""
        return self._index.get(template_hash)


class LogPointIndexFactory:
    """按 repo_id 动态构造 StorageBackedLogPointIndex（review OQ-2）。

    场景：M2 HTTP API 的 analyze_logs 入参 repo_id 可选，
    deps 工厂层无法预先知道请求维度 repo_id，
    service 内部收到 repo_id 后调 factory.get_index(repo_id) 构造对应 repo 的 index。

    内部 cache：同 session 生命周期内同 repo_id 不重复扫表。
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._cache: dict[str, StorageBackedLogPointIndex] = {}

    def get_index(self, repo_id: str) -> StorageBackedLogPointIndex:
        """返回或构造指定 repo 的 LogPointIndex。"""
        if repo_id not in self._cache:
            self._cache[repo_id] = StorageBackedLogPointIndex(
                repo_id=repo_id, session=self._session,
            )
        return self._cache[repo_id]
