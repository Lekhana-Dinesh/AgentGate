from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.common import ORMModel


class WorkerResponse(ORMModel):
    id: str
    worker_id: str
    hostname: str
    process_id: int | None
    status: Literal["running", "stale", "stopped"]
    last_heartbeat_at: datetime
    started_at: datetime
    stopped_at: datetime | None
    metadata: dict
    created_at: datetime
    updated_at: datetime


class WorkerStatusResponse(ORMModel):
    total_workers: int
    running_workers: int
    stale_workers: int
    stopped_workers: int
    latest_heartbeat_at: datetime | None = None

