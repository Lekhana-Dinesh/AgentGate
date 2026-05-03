from __future__ import annotations

import logging

import pytest
from cryptography.fernet import Fernet

from app.api.routes import health as health_routes
from app.core.config import Settings, get_settings
from app.core.enums import UserRole
from app.core.security import hash_password
from app.models import Tenant, User
from app.services.readiness_service import ComponentStatus
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
    }


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
    assert "ghp_super_secret_metrics_token" not in metrics_response.text
    assert "Bearer " not in metrics_response.text


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
