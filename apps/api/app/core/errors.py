from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.redaction import redact_sensitive_data, redact_sensitive_string

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        detail: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        code: str = "app_error",
        extra: dict | None = None,
    ) -> None:
        self.detail = detail
        self.status_code = status_code
        self.code = code
        self.extra = extra or {}
        super().__init__(detail)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    validation_status = getattr(
        status,
        "HTTP_422_UNPROCESSABLE_CONTENT",
        422,
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        request_id = _request_id(request)
        request.state.error_code = exc.code
        safe_detail = redact_sensitive_string(exc.detail)
        safe_extra = redact_sensitive_data(exc.extra)
        logger.warning(
            "app_error",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": exc.status_code,
                "request_id": request_id,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "error_code": exc.code,
            },
        )
        headers = {}
        retry_after = safe_extra.get("retry_after_seconds") if isinstance(safe_extra, dict) else None
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "detail": safe_detail,
                    "extra": safe_extra,
                    "request_id": request_id,
                }
            },
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = _request_id(request)
        request.state.error_code = "validation_error"
        serialized_errors = jsonable_encoder(_sanitize_validation_errors(exc.errors()))
        logger.info(
            "validation_error",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": validation_status,
                "request_id": request_id,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "error_code": "validation_error",
            },
        )
        return JSONResponse(
            status_code=validation_status,
            content={
                "error": {
                    "code": "validation_error",
                    "detail": "Request validation failed.",
                    "request_id": request_id,
                    "extra": {"errors": serialized_errors},
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = _request_id(request)
        request.state.error_code = "http_error"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "detail": exc.detail,
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(request: Request, __: IntegrityError) -> JSONResponse:
        request_id = _request_id(request)
        request.state.error_code = "integrity_error"
        logger.warning(
            "database_integrity_error",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": status.HTTP_409_CONFLICT,
                "request_id": request_id,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "error_code": "integrity_error",
            },
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "error": {
                    "code": "integrity_error",
                    "detail": "The request conflicts with an existing record or constraint.",
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, __: SQLAlchemyError) -> JSONResponse:
        request_id = _request_id(request)
        request.state.error_code = "database_error"
        logger.error(
            "database_error",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
                "request_id": request_id,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "error_code": "database_error",
            },
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "database_error",
                    "detail": "The database is temporarily unavailable.",
                    "request_id": request_id,
                }
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, __: Exception) -> JSONResponse:
        request_id = _request_id(request)
        request.state.error_code = "internal_server_error"
        logger.exception(
            "unexpected_error",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "request_id": request_id,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "error_code": "internal_server_error",
            },
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "code": "internal_server_error",
                    "detail": "The server could not process the request.",
                    "request_id": request_id,
                }
            },
        )


def _sanitize_validation_errors(errors: list[dict]) -> list[dict]:
    sanitized: list[dict] = []
    for item in errors:
        cleaned = {key: value for key, value in item.items() if key != "input"}
        sanitized.append(redact_sensitive_data(cleaned))
    return sanitized
