from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.enums import UserRole
from app.core.security import generate_api_key, hash_password
from app.models import AgentAPIKey, ApprovalRequest, AuditEvent, Tenant, User
from app.models.base import utcnow
from app.tests.conftest import make_token


def test_deactivated_user_cannot_login_or_access_protected_endpoints(client, db_session, seeded_tenants):
    inactive_admin = User(
        tenant_id=seeded_tenants["tenant_a"].id,
        email="inactive.admin@tenant-a.example.com",
        full_name="Inactive Admin",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=False,
        deactivated_at=utcnow(),
        deactivation_reason="offboarded",
    )
    db_session.add(inactive_admin)
    db_session.commit()
    token = make_token(inactive_admin)

    login_response = client.post(
        "/v1/auth/login",
        json={
            "email": inactive_admin.email,
            "password": "AgentGate123!",
            "tenant_slug": seeded_tenants["tenant_a"].slug,
        },
    )
    settings_response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {token}"})
    agents_response = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})

    assert login_response.status_code == 403
    assert login_response.json()["error"]["code"] == "inactive_user"
    assert settings_response.status_code == 401
    assert settings_response.json()["error"]["code"] == "inactive_user"
    assert agents_response.status_code == 401
    assert agents_response.json()["error"]["code"] == "inactive_user"


def test_deactivated_reviewer_cannot_approve_requests(client, db_session, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])

    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Email",
            "action_name": "send_external_email",
            "arguments": {"recipient": "buyer@acme.com", "body": "Please review."},
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

    approval = db_session.scalar(select(ApprovalRequest).where(ApprovalRequest.tenant_id == seeded_tenants["tenant_a"].id))
    assert approval is not None

    seeded_tenants["reviewer_a"].is_active = False
    seeded_tenants["reviewer_a"].deactivated_at = utcnow()
    seeded_tenants["reviewer_a"].deactivation_reason = "disabled reviewer"
    db_session.commit()

    response = client.post(
        f"/v1/approvals/{approval.id}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approve", "execute_now": False},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "inactive_user"


def test_user_management_routes_enforce_rbac_and_tenant_isolation(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    tenant_b_token = make_token(seeded_tenants["admin_b"])

    list_response = client.get("/v1/users", headers={"Authorization": f"Bearer {admin_token}"})
    reviewer_response = client.get("/v1/users", headers={"Authorization": f"Bearer {reviewer_token}"})
    developer_response = client.get("/v1/users", headers={"Authorization": f"Bearer {developer_token}"})
    cross_tenant_response = client.get(
        f"/v1/users/{seeded_tenants['admin_a'].id}",
        headers={"Authorization": f"Bearer {tenant_b_token}"},
    )

    assert list_response.status_code == 200
    assert reviewer_response.status_code == 200
    assert developer_response.status_code == 403
    assert cross_tenant_response.status_code == 404
    assert all(item["tenant_id"] == seeded_tenants["tenant_a"].id for item in list_response.json())
    assert all(item["email"] != seeded_tenants["admin_b"].email for item in list_response.json())


def test_user_patch_updates_safe_fields_only(client, db_session, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])

    response = client.patch(
        f"/v1/users/{seeded_tenants['developer_a'].id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"full_name": "Developer A Updated", "role": "viewer"},
    )
    db_session.refresh(seeded_tenants["developer_a"])

    assert response.status_code == 200
    assert response.json()["full_name"] == "Developer A Updated"
    assert response.json()["role"] == "viewer"
    assert response.json()["provisioned_source"] == "local"
    assert seeded_tenants["developer_a"].role == UserRole.VIEWER


def test_deactivate_user_revokes_user_created_agent_api_keys_and_audits(client, db_session, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    raw_key, prefix, hashed_key = generate_api_key()
    api_key = AgentAPIKey(
        tenant_id=seeded_tenants["tenant_a"].id,
        agent_id=seeded_tenants["agent_a"].id,
        created_by_user_id=seeded_tenants["developer_a"].id,
        name="Developer key",
        prefix=prefix,
        hashed_key=hashed_key,
        scopes=["gateway:invoke"],
        expires_at=utcnow() + timedelta(days=30),
    )
    db_session.add(api_key)
    db_session.commit()

    deactivate_response = client.post(
        f"/v1/users/{seeded_tenants['developer_a'].id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "scim deprovisioned"},
    )
    db_session.refresh(api_key)
    audit_event = db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.resource_id == seeded_tenants["developer_a"].id,
            AuditEvent.event_type == "user.deactivated",
        )
        .order_by(AuditEvent.created_at.desc())
    )

    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"X-API-Key": raw_key},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Try a revoked key.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_acme_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["is_active"] is False
    assert deactivate_response.json()["status"] == "deactivated"
    assert deactivate_response.json()["deactivation_reason"] == "scim deprovisioned"
    assert api_key.revoked_at is not None
    assert gateway_response.status_code == 401
    assert gateway_response.json()["error"]["code"] == "invalid_api_key"
    assert audit_event is not None
    assert audit_event.metadata_json["revoked_agent_api_key_count"] == 1


def test_reactivate_user_clears_deactivation_fields(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])

    deactivate_response = client.post(
        f"/v1/users/{seeded_tenants['developer_a'].id}/deactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "temporary hold"},
    )
    reactivate_response = client.post(
        f"/v1/users/{seeded_tenants['developer_a'].id}/reactivate",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert deactivate_response.status_code == 200
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["is_active"] is True
    assert reactivate_response.json()["status"] == "active"
    assert reactivate_response.json()["deactivated_at"] is None
    assert reactivate_response.json()["deactivation_reason"] is None


def test_last_active_owner_cannot_self_lock_out(client, db_session):
    tenant = Tenant(name="Owner Tenant", slug="owner-tenant", plan="enterprise")
    db_session.add(tenant)
    db_session.flush()
    owner = User(
        tenant_id=tenant.id,
        email="owner@owner-tenant.example.com",
        full_name="Tenant Owner",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.OWNER,
        is_active=True,
    )
    db_session.add(owner)
    db_session.commit()
    owner_token = make_token(owner)

    deactivate_response = client.post(
        f"/v1/users/{owner.id}/deactivate",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"reason": "self lockout"},
    )
    demote_response = client.patch(
        f"/v1/users/{owner.id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": "admin"},
    )

    assert deactivate_response.status_code == 409
    assert deactivate_response.json()["error"]["code"] == "last_active_owner_required"
    assert demote_response.status_code == 409
    assert demote_response.json()["error"]["code"] == "last_active_owner_required"
