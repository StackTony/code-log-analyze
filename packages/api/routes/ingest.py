"""POST /ingest — IngestRequest → RepoLogGraphService.ingest_repo（spec §三 + §四 + 云长 C-1 修订）。"""
from __future__ import annotations

import hashlib
import pathlib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from packages.api.deps import get_service
from packages.api.mappers.log_point import (
    log_point_to_response,  # noqa: F401 — 下个 task list_candidates 会用
)
from packages.api.schemas.ingest import IngestRequest, IngestResponse
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.storage.models import RepoIngestLockModel
from packages.m1.unit_a_repo_registrar import RepoSource, User

router = APIRouter(tags=["ingestion"])


def _compute_repo_id_preview(req: IngestRequest) -> str:
    """预计算 repo_id（与 M1 _compute_repo_id 一致）— 用于查 lock 表 running 状态。"""
    key = req.github_url or str(pathlib.Path(req.local_path or "").resolve())
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"repo-{h}"


@router.post("/ingest", response_model=IngestResponse, status_code=201)
def ingest(
    req: IngestRequest,
    service: RepoLogGraphService = Depends(get_service),  # noqa: B008
) -> IngestResponse:
    """POST /ingest — 串 M1 ingest_repo（云长 C-1 修订：先查 lock 表 running）。"""
    # 先查 lock 表 running 状态（云长 C-1 修订 — M1 service 内部静默 return repo_id）
    repo_id_preview = _compute_repo_id_preview(req)
    existing = service._session.scalar(
        select(RepoIngestLockModel)
        .where(RepoIngestLockModel.repo_id == repo_id_preview)
        .where(RepoIngestLockModel.status == "running")
        .order_by(RepoIngestLockModel.id.desc())
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "M1_INGEST_LOCK_RUNNING",
                "message": f"repo {existing.repo_id} is being ingested",
                "details": {"repo_id": existing.repo_id, "status": "running"},
            },
        )

    # 构造 RepoSource + User
    source = RepoSource(
        url=req.github_url,
        local_path=req.local_path,
    )
    ingester = User(id=req.ingester.id, name=req.ingester.name)

    repo_id = service.ingest_repo(source, ingester)
    return IngestResponse(repo_id=repo_id)
