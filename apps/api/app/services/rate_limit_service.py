from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from functools import lru_cache
from threading import Lock

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AuditActorType
from app.core.errors import AppError
from app.core.metrics import get_metrics_registry
from app.services.audit_service import AuditService


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    remaining: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._windows: dict[str, deque[float]] = defaultdict(deque)

    def consume(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.monotonic()
        cutoff = now - max(1, window_seconds)
        with self._lock:
            window = self._windows[key]
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= limit:
                retry_after = max(1, int(window_seconds - (now - window[0])))
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after,
                    remaining=0,
                )
            window.append(now)
            remaining = max(0, limit - len(window))
            return RateLimitDecision(
                allowed=True,
                retry_after_seconds=0,
                remaining=remaining,
            )

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()


@dataclass(frozen=True, slots=True)
class RateLimitSettings:
    enabled: bool
    limit: int
    window_seconds: int


class RateLimitService:
    def __init__(self, *, backend: InMemoryRateLimiter | None = None) -> None:
        self.backend = backend or InMemoryRateLimiter()
        self.audit_service = AuditService()
        self.metrics = get_metrics_registry()

    def enforce(
        self,
        *,
        scope: str,
        key_parts: list[str | None],
        settings: RateLimitSettings,
        db: Session | None = None,
        tenant_id: str | None = None,
        actor_type: AuditActorType = AuditActorType.SYSTEM,
        actor_id: str | None = None,
        ip_address: str | None = None,
        audit_on_exhaustion: bool = False,
        resource_type: str = "rate_limit",
        resource_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if not settings.enabled:
            return
        decision = self.backend.consume(
            key=self._hash_key(scope=scope, key_parts=key_parts),
            limit=max(1, settings.limit),
            window_seconds=max(1, settings.window_seconds),
        )
        if decision.allowed:
            return

        self.metrics.increment("agentgate_rate_limit_exceeded_total", scope=scope)
        if audit_on_exhaustion and db is not None and tenant_id:
            self.audit_service.create_event(
                db,
                tenant_id=tenant_id,
                actor_type=actor_type,
                actor_id=actor_id,
                event_type="security.rate_limit.exceeded",
                resource_type=resource_type,
                resource_id=resource_id or scope,
                metadata={
                    "scope": scope,
                    "retry_after_seconds": decision.retry_after_seconds,
                    **(metadata or {}),
                },
                ip_address=ip_address,
            )
            db.commit()

        raise AppError(
            "Too many requests. Try again later.",
            status_code=429,
            code="rate_limited",
            extra={
                "scope": scope,
                "retry_after_seconds": decision.retry_after_seconds,
            },
        )

    def reset(self) -> None:
        self.backend.reset()

    def _hash_key(self, *, scope: str, key_parts: list[str | None]) -> str:
        normalized = [scope]
        for item in key_parts:
            value = str(item or "").strip().lower()
            if value:
                normalized.append(value)
        digest = hashlib.sha256("::".join(normalized).encode("utf-8")).hexdigest()
        return f"{scope}:{digest}"


def get_rate_limit_settings(scope: str) -> RateLimitSettings:
    settings = get_settings()
    enabled = settings.rate_limit_enabled
    if enabled is None:
        enabled = settings.environment not in {"development", "test"}

    limits = {
        "login": (settings.rate_limit_login_limit, settings.rate_limit_login_window_seconds),
        "oidc": (settings.rate_limit_oidc_limit, settings.rate_limit_oidc_window_seconds),
        "gateway": (settings.rate_limit_gateway_limit, settings.rate_limit_gateway_window_seconds),
        "approval": (settings.rate_limit_approval_limit, settings.rate_limit_approval_window_seconds),
        "audit_export": (
            settings.rate_limit_audit_export_limit,
            settings.rate_limit_audit_export_window_seconds,
        ),
        "retention": (
            settings.rate_limit_retention_limit,
            settings.rate_limit_retention_window_seconds,
        ),
    }
    limit, window_seconds = limits[scope]
    return RateLimitSettings(enabled=bool(enabled), limit=limit, window_seconds=window_seconds)


@lru_cache(maxsize=1)
def get_rate_limiter() -> RateLimitService:
    return RateLimitService()
