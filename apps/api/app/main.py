from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.api.router import api_router
from app.core.metrics import get_metrics_registry
from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.init_db import init_db

settings = get_settings()
configure_logging()
logger = get_logger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path not in {"/docs", "/redoc", "/openapi.json"} and not request.url.path.startswith("/docs/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        request.state.tenant_id = getattr(request.state, "tenant_id", None)
        request.state.user_id = getattr(request.state, "user_id", None)
        request.state.error_code = getattr(request.state, "error_code", "")
        started_at = perf_counter()
        response: Response = await call_next(request)
        duration_ms = round((perf_counter() - started_at) * 1000, 2)
        duration_seconds = max(0.0, duration_ms / 1000.0)
        response.headers["X-Request-ID"] = request_id
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or request.url.path or "unmatched"
        error_code = str(getattr(request.state, "error_code", "") or "")
        metrics = get_metrics_registry()
        metrics.increment(
            "agentgate_http_requests_total",
            method=request.method,
            route=route_path,
            status_code=str(response.status_code),
            error_code=error_code or "none",
        )
        metrics.observe(
            "agentgate_http_request_duration_seconds",
            duration_seconds,
            method=request.method,
            route=route_path,
        )
        logger.info(
            "request_completed",
            extra={
                "path": route_path,
                "method": request.method,
                "status_code": response.status_code,
                "request_id": request_id,
                "duration_ms": duration_ms,
                "tenant_id": getattr(request.state, "tenant_id", None),
                "user_id": getattr(request.state, "user_id", None),
                "error_code": error_code or None,
            },
        )
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    current_settings = get_settings()
    if current_settings.auto_create_schema:
        init_db()
    logger.info("agentgate_api_started", extra={"environment": current_settings.environment})
    yield


app = FastAPI(
    title="AgentGate API",
    version="0.1.0",
    description=(
        "AgentGate is a runtime security and governance platform for enterprise AI agents."
    ),
    lifespan=lifespan,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(api_router)
register_exception_handlers(app)
