from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.security import hash_password
from app.core.security import generate_api_key
from app.models import AgentAPIKey, Tenant, User
from app.models.base import utcnow
from app.security.browser_sessions import CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.tests.conftest import make_token


def _enable_cookie_mode(monkeypatch) -> None:
    monkeypatch.setenv("AGENTGATE_AUTH_SESSION_MODE", "cookie")
    monkeypatch.setenv("AGENTGATE_COOKIE_SECURE", "false")
    monkeypatch.setenv("AGENTGATE_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("AGENTGATE_CSRF_ENABLED", "true")
    get_settings.cache_clear()


def _create_login_user(db_session) -> dict[str, str]:
    tenant = Tenant(name="Session Tenant", slug="session-tenant", plan="enterprise")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email="session.admin@tenant-a.example.com",
        full_name="Session Admin",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return {
        "email": user.email,
        "password": "AgentGate123!",
        "tenant_slug": tenant.slug,
    }


def test_token_mode_login_still_returns_bearer_token(client, db_session):
    response = client.post("/v1/auth/login", json=_create_login_user(db_session))

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["session_mode"] == "token"
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_cookie_mode_login_sets_httponly_cookie_and_hides_access_token(client, db_session, monkeypatch):
    _enable_cookie_mode(monkeypatch)

    response = client.post("/v1/auth/login", json=_create_login_user(db_session))

    assert response.status_code == 200
    assert response.json()["access_token"] is None
    assert response.json()["session_mode"] == "cookie"
    assert response.json()["csrf_token"]
    assert SESSION_COOKIE_NAME in response.headers.get("set-cookie", "")
    assert "HttpOnly" in response.headers.get("set-cookie", "")
    assert client.cookies.get(SESSION_COOKIE_NAME)


def test_cookie_mode_current_user_and_csrf_refresh_work(client, db_session, monkeypatch):
    _enable_cookie_mode(monkeypatch)
    login_response = client.post("/v1/auth/login", json=_create_login_user(db_session))

    me_response = client.get("/v1/auth/me")
    csrf_response = client.get("/v1/auth/csrf-token")

    assert me_response.status_code == 200
    assert me_response.json()["email"] == "session.admin@tenant-a.example.com"
    assert csrf_response.status_code == 200
    assert csrf_response.json()["session_mode"] == "cookie"
    assert csrf_response.json()["csrf_token"]
    assert csrf_response.json()["csrf_token"] == login_response.json()["csrf_token"]


def test_logout_clears_cookie_session(client, db_session, monkeypatch):
    _enable_cookie_mode(monkeypatch)
    login_response = client.post("/v1/auth/login", json=_create_login_user(db_session))
    csrf_token = login_response.json()["csrf_token"]

    logout_response = client.post("/v1/auth/logout", headers={CSRF_HEADER_NAME: csrf_token})
    me_response = client.get("/v1/auth/me")

    assert logout_response.status_code == 200
    assert logout_response.json()["logged_out"] is True
    assert client.cookies.get(SESSION_COOKIE_NAME) is None
    assert me_response.status_code == 401
    assert me_response.json()["error"]["code"] == "authentication_required"


def test_cookie_mode_requires_csrf_for_unsafe_requests(client, db_session, monkeypatch):
    _enable_cookie_mode(monkeypatch)
    login_response = client.post("/v1/auth/login", json=_create_login_user(db_session))
    csrf_token = login_response.json()["csrf_token"]

    missing_response = client.post("/v1/retention/purge", json={"dry_run": True, "limit": 1})
    invalid_response = client.post(
        "/v1/retention/purge",
        json={"dry_run": True, "limit": 1},
        headers={CSRF_HEADER_NAME: "tampered"},
    )
    valid_response = client.post(
        "/v1/retention/purge",
        json={"dry_run": True, "limit": 1},
        headers={CSRF_HEADER_NAME: csrf_token},
    )

    assert missing_response.status_code == 403
    assert missing_response.json()["error"]["code"] == "csrf_required"
    assert invalid_response.status_code == 403
    assert invalid_response.json()["error"]["code"] == "csrf_invalid"
    assert valid_response.status_code == 200


def test_bearer_and_api_key_machine_auth_bypass_csrf(client, db_session, seeded_tenants, monkeypatch):
    _enable_cookie_mode(monkeypatch)
    client.post("/v1/auth/login", json=_create_login_user(db_session))
    bearer_token = make_token(seeded_tenants["admin_a"])
    raw_key, prefix, hashed_key = generate_api_key()
    api_key = AgentAPIKey(
        tenant_id=seeded_tenants["tenant_a"].id,
        agent_id=seeded_tenants["agent_a"].id,
        created_by_user_id=seeded_tenants["admin_a"].id,
        name="Gateway machine client",
        prefix=prefix,
        hashed_key=hashed_key,
        scopes=["gateway:invoke"],
        expires_at=utcnow() + timedelta(days=30),
    )
    db_session.add(api_key)
    db_session.commit()

    bearer_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={"dry_run": True, "limit": 1},
    )
    api_key_response = client.post(
        "/v1/gateway/tool-call",
        headers={"X-API-Key": raw_key},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Read account details.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_cookie_csrf_bypass"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert bearer_response.status_code == 200
    assert api_key_response.status_code == 200


def test_deactivated_user_with_cookie_session_is_rejected(client, db_session, seeded_tenants, monkeypatch):
    _enable_cookie_mode(monkeypatch)
    payload = _create_login_user(db_session)
    client.post("/v1/auth/login", json=payload)

    user = db_session.scalar(
        select(User).where(User.email == payload["email"])
    )
    assert user is not None
    user.is_active = False
    user.deactivated_at = utcnow()
    user.deactivation_reason = "disabled after login"
    db_session.commit()

    response = client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "inactive_user"
