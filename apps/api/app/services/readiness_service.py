from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.schemas.security import KeyPurposeStatusResponse
from app.security.key_management import (
    KEY_PURPOSE_PAYLOAD_PROTECTION,
    KeyManagementError,
    get_key_provider,
)
from app.services.notification_service import NotificationService
from app.services.rate_limit_service import get_rate_limiter
from app.core.enums import ScheduledTaskType


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    status: str
    details: dict[str, object] = field(default_factory=dict)


class ReadinessService:
    def __init__(self) -> None:
        self.notification_service = NotificationService()

    def check_database(self) -> ComponentStatus:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return ComponentStatus(status="ok")
        except Exception:
            return ComponentStatus(status="unavailable")

    def check_jobs(self) -> ComponentStatus:
        settings = get_settings()
        details = {
            "dispatch_mode": settings.job_dispatch_mode,
            "broker": settings.job_broker,
        }
        if settings.job_broker != "redis":
            return ComponentStatus(status="ok", details=details | {"broker_status": "database_only"})

        if not settings.redis_url:
            return ComponentStatus(status="unconfigured", details=details | {"broker_status": "missing_redis_url"})

        try:
            import redis

            redis.from_url(settings.redis_url).ping()
            return ComponentStatus(status="ok", details=details | {"broker_status": "reachable"})
        except Exception:
            return ComponentStatus(status="degraded", details=details | {"broker_status": "unavailable"})

    def check_keys(self) -> ComponentStatus:
        provider = get_key_provider()
        try:
            purpose_status = provider.get_purpose_status(KEY_PURPOSE_PAYLOAD_PROTECTION)
        except KeyManagementError as exc:
            purpose_status = KeyPurposeStatusResponse(
                purpose=KEY_PURPOSE_PAYLOAD_PROTECTION,
                provider=provider.provider_name,
                active_key_ref=None,
                active_key_version=None,
                configured_key_refs=[],
                status="unconfigured",
                region=None,
                warnings=[exc.detail],
            )
        return ComponentStatus(
            status="ok" if purpose_status.status == "ready" else purpose_status.status,
            details={
                "provider": provider.provider_name,
                "purpose": purpose_status.purpose,
                "active_key_ref": purpose_status.active_key_ref,
                "active_key_version": purpose_status.active_key_version,
                "region": purpose_status.region,
                "readiness": purpose_status.status,
                "warnings": list(purpose_status.warnings),
            },
        )

    def check_integrations(self) -> ComponentStatus:
        settings = get_settings()
        slack_health = self.notification_service.slack_health(probe=False)
        public_urls = {
            "app_url_configured": bool(settings.public_app_url),
            "api_url_configured": bool(settings.public_api_url),
            "app_url_https": settings.public_app_url.startswith("https://"),
            "api_url_https": settings.public_api_url.startswith("https://"),
        }
        slack_status = {
            "enabled": slack_health.enabled,
            "configured": slack_health.configured,
            "status": slack_health.status,
        }
        status = "ok"
        if slack_health.enabled and slack_health.status in {"unconfigured", "degraded"}:
            status = "degraded"
        return ComponentStatus(
            status=status,
            details={
                "public_urls": public_urls,
                "slack": slack_status,
            },
        )

    def check_rate_limiter(self) -> ComponentStatus:
        status = get_rate_limiter().get_status()
        return ComponentStatus(
            status=str(status.pop("status")),
            details=status,
        )

    def check_scheduler(self) -> ComponentStatus:
        settings = get_settings()
        return ComponentStatus(
            status="ok",
            details={
                "loop_command": "python -m app.scheduler",
                "poll_interval_seconds": settings.scheduler_poll_interval_seconds,
                "batch_size": settings.scheduler_batch_size,
                "cron_timezone": "UTC",
                "supported_task_types": [item.value for item in ScheduledTaskType],
            },
        )

    def get_ready_payload(self) -> tuple[int, dict[str, object]]:
        database = self.check_database()
        jobs = self.check_jobs()
        keys = self.check_keys()
        integrations = self.check_integrations()
        rate_limiter = self.check_rate_limiter()
        scheduler = self.check_scheduler()

        overall_status = "ready"
        http_status = 200
        if database.status != "ok":
            overall_status = "not_ready"
            http_status = 503
        elif keys.status in {"unconfigured", "unavailable"}:
            overall_status = "not_ready"
            http_status = 503
        elif rate_limiter.status == "unavailable":
            overall_status = "not_ready"
            http_status = 503

        return http_status, {
            "status": overall_status,
            "checks": {
                "database": {"status": database.status, **database.details},
                "jobs": {"status": jobs.status, **jobs.details},
                "keys": {"status": keys.status, **keys.details},
                "integrations": {"status": integrations.status, **integrations.details},
                "rate_limiter": {"status": rate_limiter.status, **rate_limiter.details},
                "scheduler": {"status": scheduler.status, **scheduler.details},
            },
        }
