from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.core.enums import UserProvisionedSource, UserRole
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import AuditEvent, Tenant, TenantOIDCConfig, User
from app.security.browser_sessions import SESSION_COOKIE_NAME
from app.schemas.auth import TokenResponse
from app.services.oidc_provider import OIDCIdentity
from app.services.oidc_service import OIDC_FAILURE_EVENT, OIDC_SUCCESS_EVENT, OIDCService


class FakeOIDCProvider:
    def __init__(self) -> None:
        self.identities: dict[str, OIDCIdentity] = {}
        self.last_authorization_state: str | None = None
        self.last_authorization_nonce: str | None = None
        self.last_exchange_nonce: str | None = None

    def get_authorization_url(self, config, *, state: str, nonce: str) -> str:
        self.last_authorization_state = state
        self.last_authorization_nonce = nonce
        return (
            "https://oidc.example/authorize"
            f"?client_id={config.client_id}&state={state}&nonce={nonce}"
        )

    def exchange_code_for_identity(self, config, *, code: str, expected_nonce: str) -> OIDCIdentity:
        self.last_exchange_nonce = expected_nonce
        if code not in self.identities:
            raise AppError("OIDC code exchange failed.", status_code=401, code="oidc_code_exchange_failed")
        return self.identities[code]


@pytest.fixture()
def fake_oidc_provider(monkeypatch):
    monkeypatch.setenv("AGENTGATE_TEST_OIDC_SECRET", "test-oidc-secret")
    provider = FakeOIDCProvider()
    service = OIDCService(provider_factory=lambda _: provider)
    monkeypatch.setattr(auth_routes, "oidc_service", service)
    return provider


def _create_oidc_config(
    db_session,
    *,
    tenant,
    provider_name: str = "ExampleSSO",
    enabled: bool = True,
    allowed_email_domains: list[str] | None = None,
    role_mapping: dict | None = None,
):
    config = TenantOIDCConfig(
        tenant_id=tenant.id,
        provider_name=provider_name,
        issuer_url="https://issuer.example",
        client_id="oidc-client-123",
        client_secret_env_var="AGENTGATE_TEST_OIDC_SECRET",
        redirect_uri=f"http://localhost:8000/v1/auth/oidc/{tenant.slug}/callback",
        scopes=["openid", "profile", "email"],
        enabled=enabled,
        allowed_email_domains=allowed_email_domains or [],
        role_mapping=role_mapping or {},
    )
    db_session.add(config)
    db_session.commit()
    return config


def _extract_ticket_from_redirect(location: str) -> str:
    parsed = urlparse(location)
    return parse_qs(parsed.fragment).get("oidc_ticket", [""])[0]


def test_local_login_still_works(client, db_session):
    tenant = Tenant(name="Login Tenant", slug="login-tenant", plan="enterprise")
    db_session.add(tenant)
    db_session.flush()
    user = User(
        tenant_id=tenant.id,
        email="owner@login-tenant.example.com",
        full_name="Login Owner",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    login_response = client.post(
        "/v1/auth/login",
        json={
            "email": "owner@login-tenant.example.com",
            "password": "AgentGate123!",
            "tenant_slug": "login-tenant",
        },
    )

    assert login_response.status_code == 200
    payload = TokenResponse.model_validate(login_response.json())
    assert payload.access_token


def test_oidc_login_url_generation(client, db_session, seeded_tenants, fake_oidc_provider):
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_a"])

    response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )

    location = response.headers["location"]
    parsed = urlparse(location)
    params = parse_qs(parsed.query)

    assert response.status_code == 302
    assert parsed.netloc == "oidc.example"
    assert params["client_id"] == ["oidc-client-123"]
    assert params["state"][0]
    assert params["nonce"][0]
    assert fake_oidc_provider.last_authorization_state == params["state"][0]
    assert fake_oidc_provider.last_authorization_nonce == params["nonce"][0]


def test_oidc_callback_success_updates_existing_user_and_audits(
    client,
    db_session,
    seeded_tenants,
    fake_oidc_provider,
):
    _create_oidc_config(
        db_session,
        tenant=seeded_tenants["tenant_a"],
        role_mapping={"groups": {"security-team": "security_reviewer"}},
    )
    existing = seeded_tenants["developer_a"]
    fake_oidc_provider.identities["code-update"] = OIDCIdentity(
        subject="oidc-subject-1",
        email=existing.email,
        full_name="Developer A via SSO",
        issuer="https://issuer.example",
        audience="oidc-client-123",
        groups=["security-team"],
        claims={"email": existing.email, "groups": ["security-team"]},
    )

    login_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        params={"code": "code-update", "state": state},
        follow_redirects=False,
    )

    ticket = _extract_ticket_from_redirect(callback_response.headers["location"])
    exchange_response = client.post("/v1/auth/oidc/exchange", json={"ticket": ticket})
    me_response = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {exchange_response.json()['access_token']}"},
    )
    db_session.refresh(existing)

    assert callback_response.status_code == 302
    assert ticket
    assert exchange_response.status_code == 200
    assert me_response.status_code == 200
    assert existing.full_name == "Developer A via SSO"
    assert existing.auth_provider == "ExampleSSO"
    assert existing.external_subject == "oidc-subject-1"
    assert existing.role == UserRole.SECURITY_REVIEWER
    assert existing.provisioned_source == UserProvisionedSource.OIDC
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == OIDC_SUCCESS_EVENT)) is not None


def test_oidc_exchange_supports_cookie_session_mode(
    client,
    db_session,
    seeded_tenants,
    fake_oidc_provider,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_AUTH_SESSION_MODE", "cookie")
    monkeypatch.setenv("AGENTGATE_COOKIE_SECURE", "false")
    monkeypatch.setenv("AGENTGATE_COOKIE_SAMESITE", "lax")
    monkeypatch.setenv("AGENTGATE_CSRF_ENABLED", "true")
    get_settings.cache_clear()
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_a"])
    fake_oidc_provider.identities["code-cookie"] = OIDCIdentity(
        subject="oidc-cookie-subject",
        email=seeded_tenants["developer_a"].email,
        full_name="Developer Cookie SSO",
        issuer="https://issuer.example",
        audience="oidc-client-123",
        groups=[],
        claims={"email": seeded_tenants["developer_a"].email},
    )

    login_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        params={"code": "code-cookie", "state": state},
        follow_redirects=False,
    )
    ticket = _extract_ticket_from_redirect(callback_response.headers["location"])

    exchange_response = client.post("/v1/auth/oidc/exchange", json={"ticket": ticket})
    me_response = client.get("/v1/auth/me")

    assert exchange_response.status_code == 200
    assert exchange_response.json()["access_token"] is None
    assert exchange_response.json()["session_mode"] == "cookie"
    assert exchange_response.json()["csrf_token"]
    assert SESSION_COOKIE_NAME in exchange_response.headers.get("set-cookie", "")
    assert me_response.status_code == 200


def test_oidc_invalid_state_rejected(client, db_session, seeded_tenants, fake_oidc_provider):
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_a"])
    fake_oidc_provider.identities["code-ok"] = OIDCIdentity(
        subject="oidc-subject-2",
        email="reviewer@tenant-a.example.com",
        full_name="Reviewer Via SSO",
        issuer="https://issuer.example",
        audience="oidc-client-123",
        groups=[],
        claims={"email": "reviewer@tenant-a.example.com"},
    )

    client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        params={"code": "code-ok", "state": "tampered-state"},
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert "sso_error=oidc_invalid_state" in callback_response.headers["location"]
    failure_event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == OIDC_FAILURE_EVENT))
    assert failure_event is not None
    assert failure_event.metadata_json["reason"] == "invalid_state"


def test_oidc_email_domain_mismatch_rejected(client, db_session, seeded_tenants, fake_oidc_provider):
    _create_oidc_config(
        db_session,
        tenant=seeded_tenants["tenant_a"],
        allowed_email_domains=["tenant-a.example.com"],
    )
    fake_oidc_provider.identities["code-domain"] = OIDCIdentity(
        subject="oidc-subject-3",
        email="user@outside.example",
        full_name="Outside User",
        issuer="https://issuer.example",
        audience="oidc-client-123",
        groups=[],
        claims={"email": "user@outside.example"},
    )

    login_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        params={"code": "code-domain", "state": state},
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert "sso_error=oidc_email_domain_forbidden" in callback_response.headers["location"]
    assert db_session.scalar(select(User).where(User.external_subject == "oidc-subject-3")) is None


def test_oidc_cross_tenant_login_rejected(client, db_session, seeded_tenants, fake_oidc_provider):
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_a"], provider_name="TenantASSO")
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_b"], provider_name="TenantBSSO")
    fake_oidc_provider.identities["code-cross"] = OIDCIdentity(
        subject="oidc-subject-4",
        email="admin@tenant-a.example.com",
        full_name="Admin A via SSO",
        issuer="https://issuer.example",
        audience="oidc-client-123",
        groups=[],
        claims={"email": "admin@tenant-a.example.com"},
    )

    login_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_b'].slug}/callback",
        params={"code": "code-cross", "state": state},
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert "sso_error=oidc_invalid_state" in callback_response.headers["location"]


def test_oidc_role_mapping_assigns_default_viewer_when_no_match(
    client,
    db_session,
    seeded_tenants,
    fake_oidc_provider,
):
    _create_oidc_config(
        db_session,
        tenant=seeded_tenants["tenant_a"],
        role_mapping={"default_role": "viewer", "claims": {"department": {"security": "security_reviewer"}}},
    )
    fake_oidc_provider.identities["code-new"] = OIDCIdentity(
        subject="oidc-subject-5",
        email="new.user@tenant-a.example.com",
        full_name="New User",
        issuer="https://issuer.example",
        audience="oidc-client-123",
        groups=[],
        claims={"email": "new.user@tenant-a.example.com", "department": "sales"},
    )

    login_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )
    state = parse_qs(urlparse(login_response.headers["location"]).query)["state"][0]
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        params={"code": "code-new", "state": state},
        follow_redirects=False,
    )
    ticket = _extract_ticket_from_redirect(callback_response.headers["location"])
    exchange_response = client.post("/v1/auth/oidc/exchange", json={"ticket": ticket})
    me_response = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {exchange_response.json()['access_token']}"},
    )

    user = db_session.scalar(select(User).where(User.external_subject == "oidc-subject-5"))
    assert me_response.status_code == 200
    assert user is not None
    assert user.role == UserRole.VIEWER
    assert user.provisioned_source == UserProvisionedSource.OIDC


def test_oidc_config_status_and_errors_do_not_expose_secrets_or_tokens(
    client,
    db_session,
    seeded_tenants,
    fake_oidc_provider,
    caplog,
):
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_a"])
    status_response = client.get(f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/config-status")

    assert status_response.status_code == 200
    assert "client_secret_env_var" not in status_response.text
    assert "AGENTGATE_TEST_OIDC_SECRET" not in status_response.text

    caplog.clear()
    caplog.set_level(logging.INFO, logger="app.main")
    caplog.set_level(logging.WARNING, logger="app.core.errors")
    callback_response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        params={"code": "super-secret-code", "state": "wrong-state"},
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert "super-secret-code" not in callback_response.text
    assert "super-secret-code" not in caplog.text
    assert "AGENTGATE_TEST_OIDC_SECRET" not in caplog.text


def test_disabled_oidc_provider_rejects_login(client, db_session, seeded_tenants):
    _create_oidc_config(db_session, tenant=seeded_tenants["tenant_a"], enabled=False)

    response = client.get(
        f"/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/login",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "sso_error=oidc_provider_disabled" in response.headers["location"]
