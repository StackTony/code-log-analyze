"""CallContext dataclass → CallContextAPI Pydantic 转换。"""
from __future__ import annotations

import dataclasses

from packages.api.mappers.log_point import log_point_to_response
from packages.api.schemas.call_context import CallContextAPI
from packages.contracts.log_point import CallContext


def call_context_to_response(ctx: CallContext) -> CallContextAPI:
    """CallContext dataclass → CallContextAPI。"""
    return CallContextAPI(
        function_signature=ctx.function_signature,
        callers=ctx.callers, callees=ctx.callees,
        enclosing_community=ctx.enclosing_community,
        related_log_points=[log_point_to_response(lp) for lp in ctx.related_log_points],
        evidence_refs=[dataclasses.asdict(c) for c in ctx.evidence_refs],
    )
