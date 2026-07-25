"""GET /log-points/{repo_id} — 查主表（spec §三 + AC-1 + AC-13）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from packages.api.deps import get_service
from packages.api.mappers.log_point import log_point_to_response
from packages.api.schemas.log_point import LogPointAPI
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.unit_d_candidate_staging import LogPointFilter

router = APIRouter(tags=["query"])


@router.get("/log-points/{repo_id}", response_model=list[LogPointAPI])
def query_log_points(
    repo_id: str,
    file_path: str | None = Query(default=None),
    function_signature: str | None = Query(default=None),
    log_level: str | None = Query(default=None),
    service: RepoLogGraphService = Depends(get_service),  # noqa: B008
) -> list[LogPointAPI]:
    """GET /log-points/{repo_id}?file_path=&function_signature=&log_level=。"""
    q = service.query_log_points(
        repo_id,
        LogPointFilter(
            file_path=file_path,
            function_signature=function_signature,
            log_level=log_level,
        ),
    )
    return [log_point_to_response(p) for p in q]
