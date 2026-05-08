from __future__ import annotations

import logging

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import UserProvisionedSource, UserRole
from app.core.security import hash_password
from app.models import AuditEvent, User


def _configure_scim(monkeypatch, *, tenant_a_token: str = "scim-token-a", tenant_b_token: str | None = None) -> None:
    mapping: dict[str, str] = {"tenant-a": "env:AGENTGATE_SCIM_TOKEN_TENANT_A"}
    monkeypatch.setenv("AGENTGATE_SCIM_TOKEN_TENANT_A", tenant_a_token)
    if tenant_b_token is not None:
        monkeypatch.setenv("AGENTGATE_SCIM_TOKEN_TENANT_B", tenant_b_token)
        mapping["tenant-b"] = "env:AGENTGATE_SCIM_TOKEN_TENANT_B"
    monkeypatch.setenv("AGENTGATE_SCIM_TENANT_TOKEN_REFS", str(mapping).replace("'", '"'))
    get_settings.cache_clear()


def _scim_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_scim_is_disabled_by_default(client):
    response = client.get("/v1/scim/v2/Users", headers=_scim_headers("unused-token"))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "scim_disabled"


def test_invalid_scim_token_is_rejected(client, monkeypatch):
    _configure_scim(monkeypatch)

    response = client.get("/v1/scim/v2/Users", headers=_scim_headers("wrong-token"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_scim_token"


def test_scim_list_get_create_update_and_deactivate_user(client, db_session, seeded_tenants, monkeypatch):
    _configure_scim(monkeypatch, tenant_b_token="scim-token-b")

    create_response = client.post(
        "/v1/scim/v2/Users",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim.created@tenant-a.example.com",
            "displayName": "SCIM Created User",
            "active": True,
        },
    )
    created_user = db_session.scalar(
        select(User).where(User.email == "scim.created@tenant-a.example.com")
    )
    assert created_user is not None

    list_response = client.get("/v1/scim/v2/Users", headers=_scim_headers("scim-token-a"))
    get_response = client.get(f"/v1/scim/v2/Users/{created_user.id}", headers=_scim_headers("scim-token-a"))
    update_response = client.put(
        f"/v1/scim/v2/Users/{created_user.id}",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim.updated@tenant-a.example.com",
            "name": {"formatted": "SCIM Updated User"},
            "active": True,
        },
    )
    deactivate_response = client.patch(
        f"/v1/scim/v2/Users/{created_user.id}",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "active", "value": False},
            ],
        },
    )

    db_session.refresh(created_user)

    assert create_response.status_code == 201
    assert create_response.json()["userName"] == "scim.created@tenant-a.example.com"
    assert list_response.status_code == 200
    assert list_response.json()["totalResults"] >= 1
    assert all(item["userName"] != seeded_tenants["admin_b"].email for item in list_response.json()["Resources"])
    assert get_response.status_code == 200
    assert get_response.json()["id"] == created_user.id
    assert update_response.status_code == 200
    assert update_response.json()["userName"] == "scim.updated@tenant-a.example.com"
    assert update_response.json()["displayName"] == "SCIM Updated User"
    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["active"] is False
    assert created_user.email == "scim.updated@tenant-a.example.com"
    assert created_user.full_name == "SCIM Updated User"
    assert created_user.is_active is False
    assert created_user.provisioned_source == UserProvisionedSource.SCIM
    assert created_user.role == UserRole.VIEWER


def test_scim_active_false_uses_lifecycle_deactivation_and_blocks_login(client, db_session, seeded_tenants, monkeypatch):
    _configure_scim(monkeypatch)
    login_user = User(
        tenant_id=seeded_tenants["tenant_a"].id,
        email="scim.lifecycle@tenant-a.example.com",
        full_name="SCIM Lifecycle User",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.DEVELOPER,
        is_active=True,
    )
    db_session.add(login_user)
    db_session.commit()

    deactivate_response = client.patch(
        f"/v1/scim/v2/Users/{login_user.id}",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "active", "value": False},
            ],
        },
    )
    login_response = client.post(
        "/v1/auth/login",
        json={
            "email": login_user.email,
            "password": "AgentGate123!",
            "tenant_slug": seeded_tenants["tenant_a"].slug,
        },
    )

    db_session.refresh(login_user)
    assert deactivate_response.status_code == 200
    assert login_user.is_active is False
    assert login_user.deactivation_reason == "scim_active_false"
    assert login_response.status_code == 403
    assert login_response.json()["error"]["code"] == "inactive_user"


def test_scim_owner_escalation_is_blocked(client, seeded_tenants, monkeypatch):
    _configure_scim(monkeypatch)

    response = client.post(
        "/v1/scim/v2/Users",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim.owner@tenant-a.example.com",
            "displayName": "SCIM Owner Attempt",
            "roles": [{"value": "owner"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "scim_role_management_unsupported"


def test_scim_tenant_isolation_is_preserved(client, seeded_tenants, monkeypatch):
    _configure_scim(monkeypatch, tenant_b_token="scim-token-b")

    cross_tenant_response = client.get(
        f"/v1/scim/v2/Users/{seeded_tenants['admin_b'].id}",
        headers=_scim_headers("scim-token-a"),
    )
    tenant_b_response = client.get(
        f"/v1/scim/v2/Users/{seeded_tenants['admin_b'].id}",
        headers=_scim_headers("scim-token-b"),
    )

    assert cross_tenant_response.status_code == 404
    assert cross_tenant_response.json()["error"]["code"] == "user_not_found"
    assert tenant_b_response.status_code == 200
    assert tenant_b_response.json()["id"] == seeded_tenants["admin_b"].id


def test_scim_emits_audit_events(client, db_session, seeded_tenants, monkeypatch):
    _configure_scim(monkeypatch)

    create_response = client.post(
        "/v1/scim/v2/Users",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "scim.audit@tenant-a.example.com",
            "displayName": "SCIM Audit User",
            "active": True,
        },
    )
    user = db_session.scalar(select(User).where(User.email == "scim.audit@tenant-a.example.com"))
    assert user is not None

    client.patch(
        f"/v1/scim/v2/Users/{user.id}",
        headers=_scim_headers("scim-token-a"),
        json={
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "replace", "path": "displayName", "value": "SCIM Audit User Updated"},
                {"op": "replace", "path": "active", "value": False},
            ],
        },
    )

    events = list(
        db_session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_id == user.id)
            .order_by(AuditEvent.created_at.asc())
        )
    )
    event_types = [event.event_type for event in events]

    assert create_response.status_code == 201
    assert "scim.user.created" in event_types
    assert "scim.user.deactivated" in event_types


def test_scim_errors_do_not_leak_secret_values(client, monkeypatch, caplog):
    secret_token = "super-secret-scim-token"
    _configure_scim(monkeypatch, tenant_a_token=secret_token)
    caplog.clear()
    caplog.set_level(logging.INFO)

    response = client.get("/v1/scim/v2/Users", headers=_scim_headers("different-token"))

    assert response.status_code == 401
    assert secret_token not in response.text
    assert secret_token not in caplog.text
    assert "different-token" not in response.text
    assert "different-token" not in caplog.text
