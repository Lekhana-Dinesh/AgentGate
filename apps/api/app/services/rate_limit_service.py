from __future__ import annotations

import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

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


class RateLimitBackendError(RuntimeError):
    """Raised when the configured rate limiter backend is unavailable."""


@dataclass(frozen=True, slots=True)
class RateLimiterBackendHealth:
    status: str
    details: dict[str, object]


class RateLimiterBackend(Protocol):
    provider_name: str

    def consume(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision: ...

    def reset(self) -> None: ...

    def check_health(self) -> RateLimiterBackendHealth: ...


class InMemoryRateLimiter:
    provider_name = "in_memory"

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

    def check_health(self) -> RateLimiterBackendHealth:
        return RateLimiterBackendHealth(
            status="ok",
            details={"backend_status": "process_local"},
        )


def _build_redis_client(redis_url: str):
    import redis

    return redis.Redis.from_url(redis_url, decode_responses=True)


class RedisRateLimiter:
    provider_name = "redis"

    def __init__(
        self,
        *,
        redis_url: str,
        redis_client=None,
        time_source=None,
        key_prefix: str = "agentgate:rate_limit",
    ) -> None:
        self.redis_url = redis_url
        self.redis_client = redis_client
        self.time_source = time_source or time.time
        self.key_prefix = key_prefix
        self._tracked_keys: set[str] = set()
        self._lock = Lock()

    def consume(self, *, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
        redis_key, ttl_seconds, fallback_retry_after = self._window_key(
            key=key,
            window_seconds=window_seconds,
        )
        client = self._get_client()
        try:
            pipeline = client.pipeline(transaction=True)
            pipeline.incr(redis_key, 1)
            pipeline.expire(redis_key, ttl_seconds)
            pipeline.ttl(redis_key)
            current_count, _, effective_ttl = pipeline.execute()
        except Exception as exc:
            raise RateLimitBackendError("Redis rate limiter backend is unavailable.") from exc

        with self._lock:
            self._tracked_keys.add(redis_key)

        count = int(current_count)
        remaining = max(0, limit - count)
        if count > limit:
            retry_after = int(effective_ttl) if int(effective_ttl) > 0 else fallback_retry_after
            return RateLimitDecision(
                allowed=False,
                retry_after_seconds=max(1, retry_after),
                remaining=0,
            )
        return RateLimitDecision(
            allowed=True,
            retry_after_seconds=0,
            remaining=remaining,
        )

    def reset(self) -> None:
        client = self.redis_client
        with self._lock:
            tracked_keys = list(self._tracked_keys)
            self._tracked_keys.clear()
        if not client or not tracked_keys:
            return
        try:
            client.delete(*tracked_keys)
        except Exception:
            with self._lock:
                self._tracked_keys.update(tracked_keys)

    def check_health(self) -> RateLimiterBackendHealth:
        try:
            self._get_client().ping()
            return RateLimiterBackendHealth(
                status="ok",
                details={"backend_status": "reachable"},
            )
        except RateLimitBackendError:
            return RateLimiterBackendHealth(
                status="unavailable",
                details={"backend_status": "unavailable"},
            )

    def _get_client(self):
        if self.redis_client is None:
            if not str(self.redis_url or "").strip():
                raise RateLimitBackendError("Redis URL is not configured.")
            try:
                self.redis_client = _build_redis_client(self.redis_url)
            except Exception as exc:
                raise RateLimitBackendError("Redis client initialization failed.") from exc
        return self.redis_client

    def _window_key(self, *, key: str, window_seconds: int) -> tuple[str, int, int]:
        normalized_window = max(1, window_seconds)
        now = int(self.time_source())
        window_id = now // normalized_window
        window_end = (window_id + 1) * normalized_window
        retry_after = max(1, window_end - now)
        ttl_seconds = retry_after + 1
        return f"{self.key_prefix}:{key}:{window_id}", ttl_seconds, retry_after


@dataclass(frozen=True, slots=True)
class RateLimitSettings:
    enabled: bool
    limit: int
    window_seconds: int
    fail_closed_on_backend_error: bool = True


def _rate_limit_enabled(settings) -> bool:
    enabled = settings.rate_limit_enabled
    if enabled is None:
        enabled = settings.environment not in {"development", "test"}
    return bool(enabled)


class RateLimitService:
    def __init__(self, *, backend: RateLimiterBackend | None = None) -> None:
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
        try:
            decision = self.backend.consume(
                key=self._hash_key(scope=scope, key_parts=key_parts),
                limit=max(1, settings.limit),
                window_seconds=max(1, settings.window_seconds),
            )
        except RateLimitBackendError:
            self.metrics.increment(
                "agentgate_rate_limit_backend_errors_total",
                provider=self.provider_name,
                scope=scope,
            )
            if not settings.fail_closed_on_backend_error:
                self.metrics.increment(
                    "agentgate_rate_limit_requests_total",
                    provider=self.provider_name,
                    scope=scope,
                    outcome="backend_error_allowed",
                )
                return
            if audit_on_exhaustion and db is not None and tenant_id:
                self.audit_service.create_event(
                    db,
                    tenant_id=tenant_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    event_type="security.rate_limit.unavailable",
                    resource_type=resource_type,
                    resource_id=resource_id or scope,
                    metadata={"scope": scope, **(metadata or {})},
                    ip_address=ip_address,
                )
                db.commit()
            raise AppError(
                "Request throttling is temporarily unavailable.",
                status_code=503,
                code="rate_limiter_unavailable",
            )
        self.metrics.increment(
            "agentgate_rate_limit_requests_total",
            provider=self.provider_name,
            scope=scope,
            outcome="allowed" if decision.allowed else "blocked",
        )
        if decision.allowed:
            return

        self.metrics.increment("agentgate_rate_limit_exceeded_total", provider=self.provider_name, scope=scope)
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

    @property
    def provider_name(self) -> str:
        return self.backend.provider_name

    def get_status(self) -> dict[str, object]:
        settings = get_settings()
        enabled = _rate_limit_enabled(settings)
        details = {
            "provider": self.provider_name,
            "enabled": enabled,
        }
        if not enabled:
            return {"status": "disabled", **details}

        backend_health = self.backend.check_health()
        if self.provider_name == "in_memory":
            status = "ok"
            if settings.environment not in {"development", "test"} and settings.allow_in_memory_rate_limit_in_production:
                status = "warning"
                backend_health = RateLimiterBackendHealth(
                    status=backend_health.status,
                    details=backend_health.details | {"warning": "process_local_only"},
                )
            return {"status": status, **details, **backend_health.details}

        return {"status": backend_health.status, **details, **backend_health.details}

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
    enabled = _rate_limit_enabled(settings)

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
        "jobs_retry": (
            settings.rate_limit_jobs_retry_limit,
            settings.rate_limit_jobs_retry_window_seconds,
        ),
        "audit_integrity": (
            settings.rate_limit_audit_integrity_limit,
            settings.rate_limit_audit_integrity_window_seconds,
        ),
        "scim": (
            settings.rate_limit_scim_limit,
            settings.rate_limit_scim_window_seconds,
        ),
    }
    limit, window_seconds = limits[scope]
    return RateLimitSettings(
        enabled=bool(enabled),
        limit=limit,
        window_seconds=window_seconds,
        fail_closed_on_backend_error=not settings.rate_limit_fail_open_on_backend_error,
    )


def get_rate_limiter() -> RateLimitService:
    settings = get_settings()
    signature = (
        settings.rate_limit_provider,
        str(settings.redis_url or "").strip(),
        settings.rate_limit_fail_open_on_backend_error,
        settings.allow_in_memory_rate_limit_in_production,
        settings.environment,
    )
    cached_signature = getattr(get_rate_limiter, "_signature", None)
    cached_service = getattr(get_rate_limiter, "_service", None)
    if cached_service is not None and cached_signature == signature:
        return cached_service

    if settings.rate_limit_provider == "redis":
        backend: RateLimiterBackend = RedisRateLimiter(redis_url=str(settings.redis_url or "").strip())
    else:
        backend = InMemoryRateLimiter()

    service = RateLimitService(backend=backend)
    get_rate_limiter._signature = signature
    get_rate_limiter._service = service
    return service
