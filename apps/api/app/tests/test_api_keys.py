from __future__ import annotations

from datetime import timedelta

from app.core.security import generate_api_key
from app.models import AgentAPIKey
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
    assert "api_key" not in list_response.json()[0]
    assert list_response.json()[0]["is_active"] is True
