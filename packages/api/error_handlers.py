"""统一错误处理 — {code, message, details} 格式（spec §五 + §八 + AC-5）。"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from packages.api.schemas.common import ErrorResponse
from packages.m1.unit_a_repo_registrar import UnsafePathError, UnsafeUrlError


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理器（spec §五 + AC-5）。"""

    @app.exception_handler(UnsafePathError)
    async def handle_unsafe_path(request: Request, exc: UnsafePathError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                code="M1_INVALID_PATH",
                message=str(exc),
                details={},
            ).model_dump(),
        )

    @app.exception_handler(UnsafeUrlError)
    async def handle_unsafe_url(request: Request, exc: UnsafeUrlError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ErrorResponse(
                code="M1_INVALID_URL",
                message=str(exc),
                details={},
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code="GENERIC_VALIDATION_ERROR",
                message="Request validation failed",
                details={"errors": exc.errors()},
            ).model_dump(),
        )

    @app.exception_handler(ValidationError)
    async def handle_pydantic_validation(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code="GENERIC_VALIDATION_ERROR",
                message="Pydantic validation failed",
                details={"errors": exc.errors()},
            ).model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # exc.detail 可能是 dict (含 code/message/details) 或 str
        if isinstance(exc.detail, dict) and "code" in exc.detail:
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.detail,
            )
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                code="GENERIC_INTERNAL_ERROR",
                message=str(exc.detail) if exc.detail else "HTTP error",
                details={},
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                code="GENERIC_INTERNAL_ERROR",
                message=str(exc),
                details={},
            ).model_dump(),
        )
