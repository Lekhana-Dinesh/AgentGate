from __future__ import annotations

from app.tests.conftest import make_token


def test_agent_listing_is_tenant_scoped(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert "SalesProposalAgent" in names
    assert "TenantBAgent" not in names


def test_agent_detail_cannot_cross_tenants(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.get(
        f"/v1/agents/{seeded_tenants['agent_b'].id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_trace_creation_cannot_target_cross_tenant_agent(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/traces",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_b"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "metadata": {},
        },
    )

    assert response.status_code == 404
