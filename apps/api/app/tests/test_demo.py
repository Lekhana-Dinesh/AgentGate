from __future__ import annotations

from app.tests.conftest import make_token


def test_demo_scenario_auto_approves_discount_and_pauses_on_email(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])

    response = client.post(
        "/v1/demo/run-sales-agent-risk-scenario",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["trace_status"] == "pending_approval"
    assert len(payload["results"]) == 4
    assert payload["results"][2]["status"] == "pending_approval"
    assert payload["results"][3]["status"] == "pending_approval"
    assert len(payload["approval_actions"]) == 1
    assert payload["approval_actions"][0]["status"] == "approved"
