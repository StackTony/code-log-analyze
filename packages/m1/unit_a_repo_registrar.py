"""Unit A: Repo Registrar — clone/gitnexus analyze/候选池构建 + 安全 + 并发锁。"""
from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.contracts.enums import ACTION_FORCE_RELEASE_LOCK, ACTION_INGEST_REPO
from packages.m1.gitnexus_client import GitNexusClient
from packages.m1.storage.models import RepoIngestLockModel

if TYPE_CHECKING:
    from packages.m1.audit_log import AuditLogger

# 路径越权防护
_DOTDOT_PATTERN = re.compile(r"\.\.")
_URL_HTTPS_ONLY = re.compile(r"^https://")


class UnsafePathError(ValueError):
    pass


class UnsafeUrlError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class User:
    id: str
    name: str
    is_admin: bool = False


@dataclasses.dataclass(frozen=True)
class RepoSource:
    url: str | None = None
    local_path: str | None = None


class RepoRegistrar:
    def __init__(
        self,
        gitnexus: GitNexusClient,
        session: Session,
        audit: AuditLogger | None = None,
    ) -> None:
        self._gitnexus = gitnexus
        self._session = session
        # 避免循环 import：延迟 import
        from packages.m1.audit_log import AuditLogger

        self._audit = audit or AuditLogger(session)

    def _compute_repo_id(self, source: RepoSource) -> str:
        key = source.url or str(pathlib.Path(source.local_path or "").resolve())
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
        return f"repo-{h}"

    def _validate_source(self, source: RepoSource) -> None:
        if source.url:
            if not _URL_HTTPS_ONLY.match(source.url):
                raise UnsafeUrlError(f"非 https URL 被拒绝: {source.url}")
        elif source.local_path:
            if _DOTDOT_PATTERN.search(source.local_path):
                raise UnsafePathError(f"路径含 .. 被拒绝: {source.local_path}")
            p = pathlib.Path(source.local_path)
            if not p.exists():
                raise UnsafePathError(f"local_path 不存在: {source.local_path}")
        else:
            raise ValueError("RepoSource 必须有 url 或 local_path")

    def ingest(self, source: RepoSource, ingester: User, incremental: bool = False) -> str:
        """clone+gitnexus analyze+候选池构建。incremental=True 时 raise NotImplementedError（AC-20）。"""
        if incremental:
            raise NotImplementedError("incremental mode in F001 v1.1")

        self._validate_source(source)
        repo_id = self._compute_repo_id(source)

        # 并发锁检查（AC-14）
        existing = self._session.scalar(
            select(RepoIngestLockModel)
            .where(RepoIngestLockModel.repo_id == repo_id)
            .order_by(RepoIngestLockModel.id.desc())
        )
        if existing and existing.status == "running":
            # 已在解析中，返回 repo_id 但不再建图
            self._audit.log(
                actor=ingester.id, action=ACTION_INGEST_REPO,
                target_repo_id=repo_id, extra={"already_running": True, "ingester": ingester.id},
            )
            return repo_id

        # 新建 lock
        lock = RepoIngestLockModel(
            repo_id=repo_id, status="running",
            started_at=datetime.now(UTC), finished_at=None,
            error_msg=None, ingester=ingester.id,
        )
        self._session.add(lock)
        self._session.commit()

        try:
            # gitnexus analyze
            alias = repo_id
            repo_path = source.local_path or self._clone_url(source.url, repo_id)
            self._gitnexus.analyze(repo_path=repo_path, alias=alias)
            lock.status = "done"
            lock.finished_at = datetime.now(UTC)
        except Exception as e:
            lock.status = "failed"
            lock.finished_at = datetime.now(UTC)
            lock.error_msg = str(e)
            self._session.commit()
            raise

        self._session.commit()
        self._audit.log(
            actor=ingester.id, action=ACTION_INGEST_REPO,
            target_repo_id=repo_id, extra={"incremental": False, "ingester": ingester.id},
        )
        return repo_id

    def _clone_url(self, url: str, repo_id: str) -> str:
        """clone 远程仓到临时工作目录。"""
        work_dir = pathlib.Path(tempfile.gettempdir()) / "codefly-repos" / repo_id
        work_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            if work_dir.exists():
                result = subprocess.run(
                    ["git", "-C", str(work_dir), "pull", "--ff-only"],
                    capture_output=True, text=True, check=False, encoding="utf-8", errors="replace",
                )
            else:
                result = subprocess.run(
                    ["git", "clone", url, str(work_dir)],
                    capture_output=True, text=True, check=False, encoding="utf-8", errors="replace",
                )
            if result.returncode != 0:
                raise RuntimeError(f"git operation failed for {repo_id}: {result.stderr}")
        except FileNotFoundError as e:
            raise RuntimeError(f"git binary not found: {e}") from e
        return str(work_dir)

    def force_release_lock(self, repo_id: str, admin: User) -> None:
        if not admin.is_admin:
            raise PermissionError("force_release_lock 需要 admin 权限")
        lock = self._session.scalar(
            select(RepoIngestLockModel)
            .where(RepoIngestLockModel.repo_id == repo_id)
            .order_by(RepoIngestLockModel.id.desc())
        )
        if lock and lock.status == "running":
            lock.status = "failed"
            lock.finished_at = datetime.now(UTC)
            lock.error_msg = "force released by admin"
            self._session.commit()
            self._audit.log(
                actor=admin.id, action=ACTION_FORCE_RELEASE_LOCK,
                target_repo_id=repo_id, extra={"admin": admin.id},
            )
