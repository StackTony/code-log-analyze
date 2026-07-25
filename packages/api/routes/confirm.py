"""POST /confirm/{repo_id} — 候选 → 主表（spec §三 + AC-1 + AC-11）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from packages.api.deps import get_service
from packages.api.schemas.confirm import ConfirmRequest
from packages.m1.repo_log_graph_service import RepoLogGraphService

router = APIRouter(tags=["ingestion"])


@router.post("/confirm/{repo_id}", status_code=204)
def confirm_ingestion(
    repo_id: str,
    req: ConfirmRequest,
    service: RepoLogGraphService = Depends(get_service),  # noqa: B008
) -> None:
    """POST /confirm/{repo_id} body={log_point_ids, confirmer}。"""
    service.confirm_ingestion(repo_id, req.log_point_ids, confirmer=req.confirmer)
