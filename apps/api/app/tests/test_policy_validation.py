from __future__ import annotations

from sqlalchemy import select

from app.api.routes import policies as policy_routes
from app.models import ApprovalRequest, AuditEvent, Job, Policy, ToolCall
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


def _simulation_payload(seeded_tenants, **overrides):
    payload = {
        "agent_id": seeded_tenants["agent_a"].id,
        "original_intent": "Review internal account data for a routine sales follow-up.",
        "tool_name": "Salesforce",
        "tool_type": "crm",
        "action_name": "read_account",
        "arguments": {"account_id": "acc_acme_001"},
        "data_classifications": ["customer_data"],
        "metadata": {},
        "dry_run": True,
    }
    payload.update(overrides)
    return payload


def _tenant_count(db_session, model, tenant_id: str) -> int:
    return len(list(db_session.scalars(select(model).where(model.tenant_id == tenant_id))))


def test_policy_simulation_allow_is_dry_run_only(client, db_session, seeded_tenants, monkeypatch):
    token = make_token(seeded_tenants["admin_a"])
    tenant_id = seeded_tenants["tenant_a"].id
    before_counts = {
        "tool_calls": _tenant_count(db_session, ToolCall, tenant_id),
        "approvals": _tenant_count(db_session, ApprovalRequest, tenant_id),
        "jobs": _tenant_count(db_session, Job, tenant_id),
        "audit_events": _tenant_count(db_session, AuditEvent, tenant_id),
    }

    def _unexpected_call(*args, **kwargs):  # pragma: no cover - assertion path only
        raise AssertionError("policy simulation must not execute tools")

    monkeypatch.setattr(policy_routes.gateway_service.tool_executor, "supports", _unexpected_call)
    monkeypatch.setattr(policy_routes.gateway_service.tool_executor, "execute", _unexpected_call)

    response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {token}"},
        json=_simulation_payload(seeded_tenants),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["approval_required"] is False
    assert payload["no_external_action_executed"] is True
    assert payload["no_job_enqueued"] is True
    assert payload["no_approval_created"] is True
    after_counts = {
        "tool_calls": _tenant_count(db_session, ToolCall, tenant_id),
        "approvals": _tenant_count(db_session, ApprovalRequest, tenant_id),
        "jobs": _tenant_count(db_session, Job, tenant_id),
        "audit_events": _tenant_count(db_session, AuditEvent, tenant_id),
    }
    assert after_counts == before_counts


def test_policy_simulation_returns_saved_policy_match_without_creating_approval(client, db_session, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    tenant_id = seeded_tenants["tenant_a"].id
    before_tool_calls = _tenant_count(db_session, ToolCall, tenant_id)
    before_approvals = _tenant_count(db_session, ApprovalRequest, tenant_id)
    before_jobs = _tenant_count(db_session, Job, tenant_id)

    response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {token}"},
        json=_simulation_payload(
            seeded_tenants,
            tool_name="PricingDB",
            tool_type="mock",
            action_name="apply_discount",
            original_intent="Review pricing guidance for an internal renewal proposal.",
            arguments={"discount_percent": 30, "sku": "renewal-pro"},
            data_classifications=["internal_pricing"],
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "require_approval"
    assert payload["approval_required"] is True
    assert payload["matched_policies"]
    assert payload["matched_policies"][0]["name"] == "Require approval for discount above 20 percent"
    assert payload["matched_policies"][0]["source"] == "saved"
    assert _tenant_count(db_session, ToolCall, tenant_id) == before_tool_calls
    assert _tenant_count(db_session, ApprovalRequest, tenant_id) == before_approvals
    assert _tenant_count(db_session, Job, tenant_id) == before_jobs


def test_policy_simulation_represents_block_outcome(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {token}"},
        json=_simulation_payload(
            seeded_tenants,
            tool_name="Postgres",
            tool_type="mock",
            action_name="export_rows",
            original_intent="Review internal reporting output before a finance sync.",
            arguments={"row_count": 10000, "query": "SELECT * FROM pricing"},
            data_classifications=["confidential"],
        ),
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "block"


def test_policy_simulation_can_include_proposed_policies(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {token}"},
        json=_simulation_payload(
            seeded_tenants,
            proposed_policies=[
                {
                    "name": "Block Salesforce reads during freeze",
                    "description": "Temporary simulation-only freeze policy.",
                    "enabled": True,
                    "severity": "critical",
                    "decision": "block",
                    "conditions": {
                        "match": "all",
                        "rules": [
                            {"field": "tool_name", "operator": "equals", "value": "Salesforce"},
                        ],
                    },
                }
            ],
        ),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "block"
    assert payload["matched_policies"][0]["name"] == "Block Salesforce reads during freeze"
    assert payload["matched_policies"][0]["source"] == "proposed"
    assert payload["matched_policies"][0]["policy_id"] is None


def test_policy_simulation_respects_tenant_isolation(client, db_session, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    other_tenant_token = make_token(seeded_tenants["admin_b"])
    tenant_policy_id = db_session.scalar(
        select(Policy.id).where(Policy.tenant_id == seeded_tenants["tenant_a"].id).limit(1)
    )

    response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
        json=_simulation_payload(
            seeded_tenants,
            agent_id=seeded_tenants["agent_b"].id,
            policy_ids=[tenant_policy_id],
        ),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "policy_not_found"

    allowed_response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=_simulation_payload(seeded_tenants, policy_ids=[tenant_policy_id]),
    )
    assert allowed_response.status_code == 200


def test_policy_simulation_requires_operator_roles(client, seeded_tenants):
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    approver_token = make_token(seeded_tenants["approver_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])

    reviewer_response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json=_simulation_payload(seeded_tenants),
    )
    developer_response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {developer_token}"},
        json=_simulation_payload(seeded_tenants),
    )
    approver_response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {approver_token}"},
        json=_simulation_payload(seeded_tenants),
    )
    viewer_response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json=_simulation_payload(seeded_tenants),
    )

    assert reviewer_response.status_code == 200
    assert developer_response.status_code == 403
    assert approver_response.status_code == 403
    assert viewer_response.status_code == 403


def test_policy_simulation_response_does_not_leak_secret_like_payloads(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/policies/simulate",
        headers={"Authorization": f"Bearer {token}"},
        json=_simulation_payload(
            seeded_tenants,
            arguments={
                "account_id": "acc_acme_001",
                "secret_token": "super-secret-token",
                "nested": {"password": "TopSecret!"},
            },
            metadata={"api_key": "hidden-value"},
        ),
    )

    assert response.status_code == 200
    response_text = response.text
    assert "super-secret-token" not in response_text
    assert "TopSecret!" not in response_text
    assert "hidden-value" not in response_text
