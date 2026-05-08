from __future__ import annotations

import logging
import math

import pytest
from cryptography.fernet import Fernet

from app.api.routes import health as health_routes
from app.core.config import Settings, get_settings
from app.core.enums import JobStatus, JobType, UserRole
from app.core.security import hash_password
from app.models import Tenant, User
from app.security.key_management import get_key_provider
from app.services.readiness_service import ComponentStatus
from app.services.job_service import JobService
from app.services.rate_limit_service import InMemoryRateLimiter, RateLimitService, RedisRateLimiter
from app.tests.conftest import make_token


def _production_settings_kwargs() -> dict:
    return {
        "environment": "production",
        "debug": False,
        "secret_key": "0123456789abcdef0123456789abcdef",
        "cors_origins": ["https://console.example.com"],
        "public_app_url": "https://app.example.com",
        "public_api_url": "https://api.example.com",
        "key_provider": "env",
        "payload_encryption_key": Fernet.generate_key().decode("utf-8"),
        "job_dispatch_mode": "worker",
        "job_broker": "database",
        "rate_limit_provider": "redis",
        "redis_url": "redis://redis.example.internal:6379/0",
    }


class _FakeRedisPipeline:
    def __init__(self, client) -> None:
        self.client = client
        self.commands: list[tuple] = []

    def incr(self, key: str, amount: int = 1):
        self.commands.append(("incr", key, amount))
        return self

    def expire(self, key: str, ttl: int):
        self.commands.append(("expire", key, ttl))
        return self

    def ttl(self, key: str):
        self.commands.append(("ttl", key))
        return self

    def execute(self):
        if self.client.raise_on_execute:
            raise RuntimeError("redis unavailable")
        results = []
        for command in self.commands:
            name = command[0]
            if name == "incr":
                _, key, amount = command
                results.append(self.client.incr(key, amount))
            elif name == "expire":
                _, key, ttl = command
                results.append(self.client.expire(key, ttl))
            elif name == "ttl":
                _, key = command
                results.append(self.client.ttl(key))
        self.commands.clear()
        return results


class _FakeRedisClient:
    def __init__(self, *, time_source) -> None:
        self.time_source = time_source
        self.raise_on_execute = False
        self.raise_on_ping = False
        self._data: dict[str, dict[str, float | int | None]] = {}

    def pipeline(self, transaction: bool = True):  # noqa: ARG002 - mirrors redis-py
        return _FakeRedisPipeline(self)

    def ping(self) -> bool:
        if self.raise_on_ping:
            raise RuntimeError("redis unreachable")
        return True

    def incr(self, key: str, amount: int = 1) -> int:
        self._purge_expired(key)
        entry = self._data.setdefault(key, {"value": 0, "expires_at": None})
        entry["value"] = int(entry["value"] or 0) + amount
        return int(entry["value"])

    def expire(self, key: str, ttl: int) -> bool:
        self._purge_expired(key)
        if key not in self._data:
            return False
        self._data[key]["expires_at"] = float(self.time_source()) + float(ttl)
        return True

    def ttl(self, key: str) -> int:
        self._purge_expired(key)
        entry = self._data.get(key)
        if entry is None:
            return -2
        expires_at = entry["expires_at"]
        if expires_at is None:
            return -1
        remaining = math.ceil(float(expires_at) - float(self.time_source()))
        return max(-2, int(remaining))

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self._data.pop(key, None) is not None:
                deleted += 1
        return deleted

    def _purge_expired(self, key: str | None = None) -> None:
        keys = [key] if key else list(self._data.keys())
        now = float(self.time_source())
        for current_key in keys:
            entry = self._data.get(current_key)
            if not entry:
                continue
            expires_at = entry["expires_at"]
            if expires_at is not None and float(expires_at) <= now:
                self._data.pop(current_key, None)


class _FakeKmsStatusClient:
    def __init__(self, *, fail_describe: bool = False) -> None:
        self.fail_describe = fail_describe

    def describe_key(self, *, KeyId: str) -> dict[str, object]:
        if self.fail_describe:
            raise RuntimeError("kms unavailable")
        return {"KeyMetadata": {"KeyId": KeyId, "Enabled": True}}


def test_production_config_rejects_weak_or_default_jwt_secret():
    with pytest.raises(ValueError):
        Settings(
            **(_production_settings_kwargs() | {"secret_key": "change-me"})
        )


def test_production_config_rejects_wildcard_cors():
    with pytest.raises(ValueError):
        Settings(
            **(_production_settings_kwargs() | {"cors_origins": ["*"]})
        )


def test_production_config_requires_payload_encryption_key():
    with pytest.raises(ValueError):
        Settings(
            **(
                _production_settings_kwargs()
                | {
                    "payload_encryption_key": None,
                    "payload_encryption_key_secret_ref": None,
                }
            )
        )


def test_production_config_requires_aws_kms_region_when_provider_selected():
    with pytest.raises(ValueError):
        Settings(
            **(
                _production_settings_kwargs()
                | {
                    "key_provider": "aws_kms",
                    "payload_encryption_key": None,
                    "aws_region": None,
                    "aws_kms_key_id": "alias/agentgate/payload",
                }
            )
        )


def test_production_config_requires_aws_kms_key_id_when_provider_selected():
    with pytest.raises(ValueError):
        Settings(
            **(
                _production_settings_kwargs()
                | {
                    "key_provider": "aws_kms",
                    "payload_encryption_key": None,
                    "aws_region": "us-east-1",
                    "aws_kms_key_id": None,
                }
            )
        )


def test_production_config_requires_redis_url_when_redis_provider_selected():
    with pytest.raises(ValueError):
        Settings(
            **(_production_settings_kwargs() | {"redis_url": None})
        )


def test_production_config_rejects_in_memory_rate_limiter_without_explicit_allow():
    with pytest.raises(ValueError):
        Settings(
            **(
                _production_settings_kwargs()
                | {
                    "rate_limit_provider": "in_memory",
                    "allow_in_memory_rate_limit_in_production": False,
                }
            )
        )


def test_production_config_rejects_insecure_cookie_session_settings():
    with pytest.raises(ValueError):
        Settings(
            **(
                _production_settings_kwargs()
                | {
                    "auth_session_mode": "cookie",
                    "cookie_secure": False,
                }
            )
        )


def test_cookie_samesite_none_requires_secure_cookie_setting():
    with pytest.raises(ValueError):
        Settings(auth_session_mode="cookie", cookie_secure=False, cookie_samesite="none")


def test_scim_tenant_token_refs_reject_literal_secret_values():
    with pytest.raises(ValueError):
        Settings(scim_tenant_token_refs={"tenant-a": "super-secret-scim-token"})


def test_production_config_requires_csrf_when_cookie_mode_enabled():
    with pytest.raises(ValueError):
        Settings(
            **(
                _production_settings_kwargs()
                | {
                    "auth_session_mode": "cookie",
                    "cookie_secure": True,
                    "csrf_enabled": False,
                }
            )
        )


def test_in_memory_rate_limiter_still_allows_then_blocks():
    service = RateLimitService(backend=InMemoryRateLimiter())
    settings = service.backend.consume(key="login:test", limit=1, window_seconds=60)
    blocked = service.backend.consume(key="login:test", limit=1, window_seconds=60)

    assert settings.allowed is True
    assert blocked.allowed is False
    assert blocked.retry_after_seconds >= 1


def test_redis_rate_limiter_allows_then_blocks_with_ttl_window():
    clock = {"now": 120}
    fake_redis = _FakeRedisClient(time_source=lambda: clock["now"])
    backend = RedisRateLimiter(
        redis_url="redis://redis.example.internal:6379/0",
        redis_client=fake_redis,
        time_source=lambda: clock["now"],
    )

    first = backend.consume(key="gateway:test", limit=1, window_seconds=60)
    second = backend.consume(key="gateway:test", limit=1, window_seconds=60)
    clock["now"] += 61
    third = backend.consume(key="gateway:test", limit=1, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is False
    assert second.retry_after_seconds >= 1
    assert third.allowed is True


def test_login_endpoint_rate_limits_with_safe_429_response(client, db_session, monkeypatch):
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_LOGIN_LIMIT", "1")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_LOGIN_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    tenant = Tenant(name="Throttle Tenant", slug="throttle-tenant", plan="enterprise")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email="owner@throttle.example.com",
        full_name="Throttle Owner",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    first_response = client.post(
        "/v1/auth/login",
        json={
            "email": "owner@throttle.example.com",
            "password": "AgentGate123!",
            "tenant_slug": "throttle-tenant",
        },
    )
    second_response = client.post(
        "/v1/auth/login",
        json={
            "email": "owner@throttle.example.com",
            "password": "AgentGate123!",
            "tenant_slug": "throttle-tenant",
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error"]["code"] == "rate_limited"
    assert "AgentGate123!" not in second_response.text
    assert int(second_response.headers["Retry-After"]) >= 1


def test_gateway_tool_call_rate_limits(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_GATEWAY_LIMIT", "1")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_GATEWAY_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    token = make_token(seeded_tenants["admin_a"])
    payload = {
        "agent_id": seeded_tenants["agent_a"].id,
        "user_id": seeded_tenants["admin_a"].id,
        "original_intent": "Read account data safely.",
        "tool_name": "Salesforce",
        "action_name": "read_account",
        "arguments": {"account_id": "acc_rate_limit"},
        "data_classifications": ["customer_data"],
        "metadata": {},
    }

    first_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    second_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error"]["code"] == "rate_limited"


def test_retention_purge_rate_limits(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_RETENTION_LIMIT", "1")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_RETENTION_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    token = make_token(seeded_tenants["admin_a"])
    first_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {token}"},
        json={"dry_run": True, "limit": 1},
    )
    second_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {token}"},
        json={"dry_run": True, "limit": 1},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error"]["code"] == "rate_limited"


def test_job_retry_endpoint_rate_limits(client, seeded_tenants, db_session, monkeypatch):
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_JOBS_RETRY_LIMIT", "1")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_JOBS_RETRY_WINDOW_SECONDS", "60")
    get_settings.cache_clear()

    token = make_token(seeded_tenants["admin_a"])
    job = JobService().enqueue(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        job_type=JobType.APPROVAL_NOTIFICATION_SLACK,
        idempotency_key="job:rate-limit-retry",
        payload={"approval_id": "apr_rate_limit"},
        max_attempts=1,
    )
    job.status = JobStatus.RETRY_EXHAUSTED
    job.dead_letter_reason = "job_processing_failed"
    db_session.commit()

    first_response = client.post(f"/v1/jobs/{job.id}/retry", headers={"Authorization": f"Bearer {token}"})
    db_session.refresh(job)
    job.status = JobStatus.RETRY_EXHAUSTED
    job.dead_letter_reason = "job_processing_failed"
    db_session.commit()
    second_response = client.post(f"/v1/jobs/{job.id}/retry", headers={"Authorization": f"Bearer {token}"})

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error"]["code"] == "rate_limited"


def test_metrics_endpoint_is_safe_and_aggregated(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Read account data safely.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {
                "account_id": "acc_metrics",
                "authorization": "Bearer ghp_super_secret_metrics_token",
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

    metrics_response = client.get("/metrics")

    assert metrics_response.status_code == 200
    assert "agentgate_http_requests_total" in metrics_response.text
    assert "agentgate_gateway_decisions_total" in metrics_response.text
    assert "agentgate_rate_limit_requests_total" in metrics_response.text
    assert "ghp_super_secret_metrics_token" not in metrics_response.text
    assert "Bearer " not in metrics_response.text
    assert seeded_tenants["admin_a"].id not in metrics_response.text


def test_ready_reports_rate_limiter_without_leaking_redis_url(client, monkeypatch):
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_PROVIDER", "redis")
    monkeypatch.setenv("AGENTGATE_REDIS_URL", "redis://user:supersecret@redis.internal:6379/3")
    get_settings.cache_clear()

    fake_redis = _FakeRedisClient(time_source=lambda: 120)
    monkeypatch.setattr("app.services.rate_limit_service._build_redis_client", lambda _: fake_redis)

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    rate_limiter = payload["checks"]["rate_limiter"]
    assert rate_limiter["provider"] == "redis"
    assert rate_limiter["status"] == "ok"
    assert "supersecret" not in response.text
    assert "redis://user" not in response.text


def test_ready_does_not_leak_github_credentials(client, monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "ghp_ready_should_not_leak")
    monkeypatch.setenv("AGENTGATE_GITHUB_APP_PRIVATE_KEY", "private-key-ready-should-not-leak")

    response = client.get("/ready")

    assert response.status_code == 200
    assert "ghp_ready_should_not_leak" not in response.text
    assert "private-key-ready-should-not-leak" not in response.text


def test_ready_warns_when_in_memory_rate_limiter_is_explicitly_allowed_in_production(monkeypatch):
    monkeypatch.setenv("AGENTGATE_ENVIRONMENT", "production")
    monkeypatch.setenv("AGENTGATE_DEBUG", "false")
    monkeypatch.setenv("AGENTGATE_SECRET_KEY", "0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("AGENTGATE_CORS_ORIGINS", '["https://console.example.com"]')
    monkeypatch.setenv("AGENTGATE_PUBLIC_APP_URL", "https://app.example.com")
    monkeypatch.setenv("AGENTGATE_PUBLIC_API_URL", "https://api.example.com")
    monkeypatch.setenv("AGENTGATE_KEY_PROVIDER", "env")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_JOB_BROKER", "database")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "object_storage")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET", "agentgate-audit-ready")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_REGION", "us-east-1")
    monkeypatch.setenv("AGENTGATE_RATE_LIMIT_PROVIDER", "in_memory")
    monkeypatch.setenv("AGENTGATE_ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION", "true")
    get_settings.cache_clear()

    original = health_routes.readiness_service.check_database
    monkeypatch.setattr(
        health_routes.readiness_service,
        "check_database",
        lambda: ComponentStatus(status="ok"),
    )

    try:
        status_code, payload = health_routes.readiness_service.get_ready_payload()
    finally:
        monkeypatch.setattr(health_routes.readiness_service, "check_database", original)

    assert status_code == 200
    assert payload["checks"]["rate_limiter"]["provider"] == "in_memory"
    assert payload["checks"]["rate_limiter"]["status"] == "warning"


def test_ready_reports_database_status(client):
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["checks"]["database"]["status"] == "ok"


def test_ready_returns_503_when_database_check_fails(client, monkeypatch):
    original = health_routes.readiness_service.check_database
    monkeypatch.setattr(
        health_routes.readiness_service,
        "check_database",
        lambda: ComponentStatus(status="unavailable"),
    )

    try:
        response = client.get("/ready")
    finally:
        monkeypatch.setattr(health_routes.readiness_service, "check_database", original)

    assert response.status_code == 503
    assert response.json()["checks"]["database"]["status"] == "unavailable"


def test_ready_reports_aws_kms_provider_status_safely(client, monkeypatch):
    monkeypatch.setenv("AGENTGATE_KEY_PROVIDER", "aws_kms")
    monkeypatch.setenv("AGENTGATE_AWS_REGION", "us-east-1")
    monkeypatch.setenv("AGENTGATE_AWS_KMS_KEY_ID", "alias/agentgate/payload")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", "payload-kms-2026-05")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION", "2026-05")
    monkeypatch.setenv("AGENTGATE_AWS_KMS_ENDPOINT_URL", "http://localhost:4566")
    get_settings.cache_clear()
    get_key_provider.cache_clear()
    monkeypatch.setattr(
        "app.security.key_management._build_aws_kms_client",
        lambda **_: _FakeKmsStatusClient(),
    )

    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    keys = payload["checks"]["keys"]
    assert keys["provider"] == "aws_kms"
    assert keys["region"] == "us-east-1"
    assert keys["status"] == "ok"
    assert keys["readiness"] == "ready"
    assert "encrypted_data_key" not in response.text


def test_ready_returns_503_when_aws_kms_provider_is_unavailable(client, monkeypatch):
    monkeypatch.setenv("AGENTGATE_KEY_PROVIDER", "aws_kms")
    monkeypatch.setenv("AGENTGATE_AWS_REGION", "us-east-1")
    monkeypatch.setenv("AGENTGATE_AWS_KMS_KEY_ID", "alias/agentgate/payload")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", "payload-kms-2026-05")
    get_settings.cache_clear()
    get_key_provider.cache_clear()
    monkeypatch.setattr(
        "app.security.key_management._build_aws_kms_client",
        lambda **_: _FakeKmsStatusClient(fail_describe=True),
    )

    response = client.get("/ready")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "not_ready"
    assert payload["checks"]["keys"]["provider"] == "aws_kms"
    assert payload["checks"]["keys"]["region"] == "us-east-1"
    assert payload["checks"]["keys"]["status"] == "unavailable"
    assert payload["checks"]["keys"]["readiness"] == "unavailable"


def test_security_headers_exist(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_request_logging_includes_safe_context_without_request_body_leakage(client, db_session, caplog):
    tenant = Tenant(name="Logging Tenant", slug="logging-tenant", plan="enterprise")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email="owner@logging.example.com",
        full_name="Logging Owner",
        hashed_password=hash_password("CorrectPassword123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    caplog.clear()
    caplog.set_level(logging.INFO)
    response = client.post(
        "/v1/auth/login",
        headers={"X-Request-ID": "req-hardening-log"},
        json={
            "email": "owner@logging.example.com",
            "password": "WrongSecretPassword!",
            "tenant_slug": "logging-tenant",
        },
    )

    assert response.status_code == 401
    assert "WrongSecretPassword!" not in caplog.text
    request_log = next(record for record in caplog.records if record.getMessage() == "request_completed")
    assert getattr(request_log, "request_id", None) == "req-hardening-log"
    assert getattr(request_log, "method", None) == "POST"
    assert getattr(request_log, "path", None) == "/v1/auth/login"
    assert getattr(request_log, "status_code", None) == 401
    assert getattr(request_log, "error_code", None) == "invalid_credentials"
