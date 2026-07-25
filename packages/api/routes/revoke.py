"""POST /revoke/{repo_id} — 主表 → 候选（MF-2 不删记录）（spec §三 + AC-1 + AC-9）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from packages.api.deps import get_service
from packages.api.schemas.confirm import RevokeRequest
from packages.m1.repo_log_graph_service import RepoLogGraphService

router = APIRouter(tags=["ingestion"])


@router.post("/revoke/{repo_id}", status_code=204)
def revoke_ingestion(
    repo_id: str,
    req: RevokeRequest,
    service: RepoLogGraphService = Depends(get_service),  # noqa: B008
) -> None:
    """POST /revoke/{repo_id} body={log_point_ids, revoker}。

    MF-2 铁律：M1 service 内部 revoke 不删主表记录，仅状态回退 candidate。
    """
    service.revoke_ingestion(repo_id, req.log_point_ids, revoker=req.revoker)
