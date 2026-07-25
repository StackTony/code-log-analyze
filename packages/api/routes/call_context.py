"""POST /call-context/{repo_id} — 取调用上下文（spec §三 + 云长 OQ-1 修订 — POST body 传 signature）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from packages.api.deps import get_service
from packages.api.mappers.call_context import call_context_to_response
from packages.api.schemas.call_context import CallContextAPI
from packages.api.schemas.confirm import CallContextRequest
from packages.m1.repo_log_graph_service import RepoLogGraphService

router = APIRouter(tags=["query"])


@router.post("/call-context/{repo_id}", response_model=CallContextAPI)
def get_call_context(
    repo_id: str,
    req: CallContextRequest,
    service: RepoLogGraphService = Depends(get_service),  # noqa: B008
) -> CallContextAPI:
    """POST /call-context/{repo_id} body={function_signature: "..."}。"""
    ctx = service.get_call_context(repo_id, req.function_signature)
    return call_context_to_response(ctx)
