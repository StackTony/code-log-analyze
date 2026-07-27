"""F002 M2 — 5 HTTP endpoints（spec §六 + AC-12/13）。

| Method | Path | Body | Response | service method |
|--------|------|------|----------|----------------|
| POST | /analyze | AnalyzeRequest | AnalysisReportAPI 201 | analyze_logs |
| POST | /analyze/deep | DeepAnalyzeRequest | DeepAnalysisAPI 201 | deep_analyze |
| GET  | /reports/{report_id} | — | AnalysisReportAPI 200 | get_report |
| GET  | /reports/{report_id}/deep-analyses | ?line_id | list[DeepAnalysisAPI] 200 | list_deep_analyses |
| POST | /reports/{report_id}/archive | — | 204 No Content | archive_report |

错误格式：复用 F001.1 error_handlers（{code, message, details}），M2 错误码前缀 M2_*。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse

from packages.api.deps import get_log_analysis_service
from packages.api.mappers.analysis import (
    analysis_report_to_response,
    deep_analysis_to_response,
)
from packages.api.schemas.analysis import (
    AnalysisReportAPI,
    AnalyzeRequest,
    DeepAnalysisAPI,
    DeepAnalyzeRequest,
)
from packages.contracts.log_entry import LogSource
from packages.m2.log_analysis_service import LogAnalysisService
from packages.m1.unit_a_repo_registrar import User

router = APIRouter(tags=["analysis"])


# ---- POST /analyze ----

@router.post("/analyze", response_model=AnalysisReportAPI, status_code=201)
async def analyze(
    req: AnalyzeRequest,
    service: LogAnalysisService = Depends(get_log_analysis_service),  # noqa: B008
) -> AnalysisReportAPI:
    """POST /analyze — Phase 1 全量分析（spec §四 + AC-3）。"""
    # 三字段互斥校验
    if not (req.log_text or req.log_file_path or req.log_stream_id):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "M2_ANALYZE_NO_SOURCE",
                "message": "must provide one of log_text / log_file_path / log_stream_id",
            },
        )

    log_source = LogSource(
        text=req.log_text,
        file_path=req.log_file_path,
        stream_id=req.log_stream_id,
    )
    analyzer = User(id=req.analyzer.id, name=req.analyzer.name)

    try:
        report = await service.analyze_logs(
            log_source=log_source,
            analyzer=analyzer,
            repo_id=req.repo_id,
            window_hours=req.window_hours,
        )
    except ValueError as e:
        # LogSource.resolve_text 失败（文件不存在 / 三字段都空）
        raise HTTPException(
            status_code=400,
            detail={
                "code": "M2_ANALYZE_INVALID_SOURCE",
                "message": str(e),
            },
        )

    return analysis_report_to_response(report)


# ---- POST /analyze/deep ----

@router.post("/analyze/deep", response_model=DeepAnalysisAPI, status_code=201)
async def deep_analyze(
    req: DeepAnalyzeRequest,
    service: LogAnalysisService = Depends(get_log_analysis_service),  # noqa: B008
) -> DeepAnalysisAPI:
    """POST /analyze/deep — Phase 2 深入分析（spec §四 + AC-7/8/10/11）。"""
    analyzer = User(id=req.analyzer.id, name=req.analyzer.name)

    try:
        record = await service.deep_analyze(
            report_id=req.report_id,
            line_ids=req.line_ids,
            analyzer=analyzer,
            iteration_context=req.iteration_context,
        )
    except ValueError as e:
        # report_id 或 line_ids 不存在
        raise HTTPException(
            status_code=404,
            detail={
                "code": "M2_DEEP_ANALYZE_NOT_FOUND",
                "message": str(e),
            },
        )
    except Exception as e:
        # IterationLimitExceeded 等业务异常
        from packages.m2.deep_analyzer import IterationLimitExceeded
        if isinstance(e, IterationLimitExceeded):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "M2_DEEP_ANALYZE_ITERATION_LIMIT",
                    "message": str(e),
                    "details": {
                        "current": e.current, "limit": e.limit,
                        "report_id": e.report_id,
                    },
                },
            )
        raise

    return deep_analysis_to_response(record)


# ---- GET /reports/{report_id} ----

@router.get(
    "/reports/{report_id}",
    response_model=AnalysisReportAPI,
    status_code=200,
)
def get_report(
    report_id: str,
    service: LogAnalysisService = Depends(get_log_analysis_service),  # noqa: B008
) -> AnalysisReportAPI:
    """GET /reports/{report_id} — 查 Phase 1 报告。"""
    report = service.get_report(report_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "M2_REPORT_NOT_FOUND",
                "message": f"report {report_id} not found",
            },
        )
    return analysis_report_to_response(report)


# ---- GET /reports/{report_id}/deep-analyses ----

@router.get(
    "/reports/{report_id}/deep-analyses",
    response_model=list[DeepAnalysisAPI],
    status_code=200,
)
def list_deep_analyses(
    report_id: str,
    line_id: str | None = Query(default=None),
    service: LogAnalysisService = Depends(get_log_analysis_service),  # noqa: B008
) -> list[DeepAnalysisAPI]:
    """GET /reports/{report_id}/deep-analyses — 列 Phase 2 深入分析。"""
    records = service.list_deep_analyses(report_id, line_id=line_id)
    return [deep_analysis_to_response(r) for r in records]


# ---- POST /reports/{report_id}/archive ----

@router.post("/reports/{report_id}/archive", status_code=204)
def archive_report(
    report_id: str,
    archiver_id: str = Query(..., description="archiver user id"),
    archiver_name: str = Query(..., description="archiver user name"),
    service: LogAnalysisService = Depends(get_log_analysis_service),  # noqa: B008
) -> Response:
    """POST /reports/{report_id}/archive — draft → archived。"""
    try:
        service.archive_report(
            report_id=report_id,
            archiver=User(id=archiver_id, name=archiver_name),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "M2_REPORT_NOT_FOUND",
                "message": str(e),
            },
        )
    return Response(status_code=204)
