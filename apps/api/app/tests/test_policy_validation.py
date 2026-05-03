from __future__ import annotations

from app.tests.conftest import make_token


def test_policy_route_rejects_invalid_numeric_threshold_field(client, seeded_tenants):
    token = make_token(seeded_tenants["reviewer_a"])
    response = client.post(
        "/v1/policies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Invalid threshold policy",
            "description": "Should fail validation",
            "enabled": True,
            "severity": "high",
            "decision": "require_approval",
            "conditions": {
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "greater_than", "value": 10},
                ],
            },
        },
    )

    assert response.status_code == 422


def test_policy_route_accepts_explicit_discount_threshold_field(client, seeded_tenants):
    token = make_token(seeded_tenants["reviewer_a"])
    response = client.post(
        "/v1/policies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Discount threshold policy",
            "description": "Uses discount_percent explicitly",
            "enabled": True,
            "severity": "high",
            "decision": "require_approval",
            "conditions": {
                "match": "all",
                "rules": [
                    {"field": "action_name", "operator": "contains", "value": "discount"},
                    {"field": "discount_percent", "operator": "greater_than", "value": 20},
                ],
            },
        },
    )

    assert response.status_code == 201
