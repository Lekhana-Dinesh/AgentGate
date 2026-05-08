from __future__ import annotations

from app.tests.conftest import make_token


def test_policy_route_rejects_invalid_numeric_threshold_field(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
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
    token = make_token(seeded_tenants["admin_a"])
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


def test_policy_list_response_is_safe_and_viewable_for_reviewer(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])

    admin_response = client.get("/v1/policies", headers={"Authorization": f"Bearer {admin_token}"})
    reviewer_response = client.get("/v1/policies", headers={"Authorization": f"Bearer {reviewer_token}"})

    assert admin_response.status_code == 200
    assert reviewer_response.status_code == 200
    assert admin_response.json()

    first_policy = admin_response.json()[0]
    assert {
        "id",
        "tenant_id",
        "name",
        "description",
        "enabled",
        "severity",
        "conditions",
        "decision",
        "created_by",
        "created_at",
        "updated_at",
    }.issubset(first_policy.keys())
    assert "token_env_var" not in first_policy
    assert "secret_ref" not in first_policy
    assert "private_key" not in admin_response.text
    assert "secret_ref:" not in admin_response.text.lower()


def test_policy_mutation_requires_owner_or_admin(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    approver_token = make_token(seeded_tenants["approver_a"])
    policy_id = client.get("/v1/policies", headers={"Authorization": f"Bearer {admin_token}"}).json()[0]["id"]

    reviewer_create = client.post(
        "/v1/policies",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={
            "name": "Reviewer should not create",
            "description": "Denied",
            "enabled": True,
            "severity": "high",
            "decision": "require_approval",
            "conditions": {
                "match": "all",
                "rules": [{"field": "recipient_domain", "operator": "equals", "value": "external"}],
            },
        },
    )
    reviewer_update = client.put(
        f"/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"enabled": False},
    )
    developer_update = client.put(
        f"/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {developer_token}"},
        json={"enabled": False},
    )
    viewer_create = client.post(
        "/v1/policies",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "name": "Viewer should not create",
            "description": "Denied",
            "enabled": True,
            "severity": "high",
            "decision": "block",
            "conditions": {
                "match": "all",
                "rules": [{"field": "action_name", "operator": "contains", "value": "delete"}],
            },
        },
    )
    approver_update = client.put(
        f"/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"enabled": False},
    )

    assert reviewer_create.status_code == 403
    assert reviewer_update.status_code == 403
    assert developer_update.status_code == 403
    assert viewer_create.status_code == 403
    assert approver_update.status_code == 403


def test_admin_can_toggle_policy_and_cross_tenant_update_is_blocked(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    other_tenant_admin_token = make_token(seeded_tenants["admin_b"])
    policy_id = client.get("/v1/policies", headers={"Authorization": f"Bearer {admin_token}"}).json()[0]["id"]

    update_response = client.put(
        f"/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"enabled": False},
    )
    cross_tenant_response = client.put(
        f"/v1/policies/{policy_id}",
        headers={"Authorization": f"Bearer {other_tenant_admin_token}"},
        json={"enabled": False},
    )

    assert update_response.status_code == 200
    assert update_response.json()["enabled"] is False
    assert cross_tenant_response.status_code == 404
