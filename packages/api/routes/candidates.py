"""GET /candidates/{repo_id} — 列候选池（spec §三 + AC-1）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from packages.api.deps import get_service
from packages.api.mappers.log_point import log_point_to_response
from packages.api.schemas.log_point import LogPointAPI
from packages.m1.repo_log_graph_service import RepoLogGraphService
from packages.m1.unit_d_candidate_staging import CandidateFilter

router = APIRouter(tags=["query"])


@router.get("/candidates/{repo_id}", response_model=list[LogPointAPI])
def list_candidates(
    repo_id: str,
    include_all: bool = Query(default=False),
    service: RepoLogGraphService = Depends(get_service),  # noqa: B008
) -> list[LogPointAPI]:
    """GET /candidates/{repo_id}?include_all=false。"""
    cands = service.list_candidates(repo_id, CandidateFilter(include_all=include_all))
    return [log_point_to_response(c) for c in cands]
