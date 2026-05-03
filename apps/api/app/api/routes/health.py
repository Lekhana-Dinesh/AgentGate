from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.services.readiness_service import ReadinessService

router = APIRouter()
readiness_service = ReadinessService()


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "agentgate-api"}


@router.get("/ready")
def ready() -> dict:
    status_code, payload = readiness_service.get_ready_payload()
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=payload)
    return payload
