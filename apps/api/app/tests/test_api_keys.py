from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.enums import AgentEnvironment, AgentStatus, RiskBand
from app.core.security import generate_api_key
from app.models import Agent, AgentAPIKey, AuditEvent
from app.models.base import utcnow
from app.tests.conftest import make_token


def test_expired_api_key_is_rejected(client, db_session, seeded_tenants):
    raw_key, prefix, hashed_key = generate_api_key()
    api_key = AgentAPIKey(
        tenant_id=seeded_tenants["tenant_a"].id,
        agent_id=seeded_tenants["agent_a"].id,
        created_by_user_id=seeded_tenants["admin_a"].id,
        name="Expired key",
        prefix=prefix,
        hashed_key=hashed_key,
        scopes=["gateway:invoke"],
        expires_at=utcnow() - timedelta(minutes=1),
    )
    db_session.add(api_key)
    db_session.commit()

    response = client.post(
        "/v1/gateway/tool-call",
        headers={"X-API-Key": raw_key},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_acme_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "api_key_expired"


def test_agent_api_key_listing_returns_metadata_only(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    create_response = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Integration key", "expires_in_days": 30},
    )
    assert create_response.status_code == 201
    assert "api_key" in create_response.json()

    list_response = client.get(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert create_response.json()["api_key"]
    assert "api_key" not in list_response.json()[0]
    assert "hashed_key" not in list_response.json()[0]
    assert list_response.json()[0]["created_by_user_id"] == seeded_tenants["admin_a"].id
    assert list_response.json()[0]["is_active"] is True


def test_security_reviewer_can_list_but_not_create_or_revoke_agent_api_keys(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    create_response = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Reviewable key", "expires_in_days": 30},
    )
    assert create_response.status_code == 201

    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    list_response = client.get(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1
    assert "api_key" not in list_response.json()[0]

    create_attempt = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"name": "Forbidden key", "expires_in_days": 30},
    )
    assert create_attempt.status_code == 403

    revoke_attempt = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys/{create_response.json()['id']}/revoke",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert revoke_attempt.status_code == 403


def test_viewer_cannot_list_agent_api_keys(client, seeded_tenants):
    token = make_token(seeded_tenants["viewer_a"])
    response = client.get(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_developer_can_manage_only_owned_agent_api_keys(client, db_session, seeded_tenants):
    developer_agent = Agent(
        tenant_id=seeded_tenants["tenant_a"].id,
        name="DeveloperOwnedAgent",
        description="Owned by developer",
        owner_user_id=seeded_tenants["developer_a"].id,
        environment=AgentEnvironment.DEVELOPMENT,
        status=AgentStatus.ACTIVE,
        purpose="Developer testing",
        allowed_tools=["Salesforce"],
        allowed_data_classes=["customer_data"],
        risk_level=RiskBand.MEDIUM,
    )
    db_session.add(developer_agent)
    db_session.commit()
    db_session.refresh(developer_agent)

    token = make_token(seeded_tenants["developer_a"])
    own_create = client.post(
        f"/v1/agents/{developer_agent.id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Own key", "expires_in_days": 30},
    )
    assert own_create.status_code == 201

    own_list = client.get(
        f"/v1/agents/{developer_agent.id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert own_list.status_code == 200
    assert len(own_list.json()) == 1

    other_list = client.get(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert other_list.status_code == 403

    other_create = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Forbidden key", "expires_in_days": 30},
    )
    assert other_create.status_code == 403


def test_revoke_agent_api_key_is_audited(client, db_session, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    create_response = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Rotating key", "expires_in_days": 30},
    )
    assert create_response.status_code == 201
    created_payload = create_response.json()

    revoke_response = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys/{created_payload['id']}/revoke",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert revoke_response.status_code == 200

    db_session.expire_all()
    audit_event = db_session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == seeded_tenants["tenant_a"].id,
            AuditEvent.event_type == "agent.api_key.revoked",
            AuditEvent.resource_id == created_payload["id"],
        )
        .order_by(AuditEvent.created_at.desc())
    )
    assert audit_event is not None
    assert audit_event.metadata_json["agent_id"] == seeded_tenants["agent_a"].id
    assert audit_event.metadata_json["prefix"] == created_payload["prefix"]
    assert audit_event.metadata_json["revoked_at"] is not None


def test_tenant_isolation_is_preserved_for_agent_api_key_routes(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    create_response = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"name": "Tenant A key", "expires_in_days": 30},
    )
    assert create_response.status_code == 201

    other_tenant_token = make_token(seeded_tenants["admin_b"])
    list_response = client.get(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )
    assert list_response.status_code == 404

    revoke_response = client.post(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys/{create_response.json()['id']}/revoke",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )
    assert revoke_response.status_code == 404


def test_expired_and_revoked_keys_are_reported_inactive(client, db_session, seeded_tenants):
    expired_key = AgentAPIKey(
        tenant_id=seeded_tenants["tenant_a"].id,
        agent_id=seeded_tenants["agent_a"].id,
        created_by_user_id=seeded_tenants["admin_a"].id,
        name="Expired summary key",
        prefix="expired-key",
        hashed_key="hashed-expired",
        scopes=["gateway:invoke"],
        expires_at=utcnow() - timedelta(days=1),
    )
    revoked_key = AgentAPIKey(
        tenant_id=seeded_tenants["tenant_a"].id,
        agent_id=seeded_tenants["agent_a"].id,
        created_by_user_id=seeded_tenants["admin_a"].id,
        name="Revoked summary key",
        prefix="revoked-key",
        hashed_key="hashed-revoked",
        scopes=["gateway:invoke"],
        expires_at=utcnow() + timedelta(days=30),
        revoked_at=utcnow(),
    )
    db_session.add_all([expired_key, revoked_key])
    db_session.commit()

    token = make_token(seeded_tenants["admin_a"])
    response = client.get(
        f"/v1/agents/{seeded_tenants['agent_a'].id}/api-keys",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    by_name = {item["name"]: item for item in response.json()}
    assert by_name["Expired summary key"]["is_active"] is False
    assert by_name["Revoked summary key"]["is_active"] is False
