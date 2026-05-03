from __future__ import annotations

from datetime import timedelta

from app.core.security import generate_api_key
from app.models import AgentAPIKey
from app.models.base import utcnow
from app.tests.conftest import make_token


def test_safe_tool_call_is_allowed_and_executed(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_acme_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["executed"] is True
    assert payload["status"] == "executed"


def test_multistep_trace_remains_open_across_safe_tool_calls(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])

    trace_response = client.post(
        "/v1/traces",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "metadata": {"scenario": "multi_step"},
        },
    )
    assert trace_response.status_code == 201
    trace_id = trace_response.json()["id"]

    first_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "trace_id": trace_id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert first_response.status_code == 200

    second_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "trace_id": trace_id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "PricingDB",
            "action_name": "read_pricing",
            "arguments": {"sku": "renewal-pro"},
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )
    assert second_response.status_code == 200

    replay_response = client.get(
        f"/v1/traces/{trace_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert replay_response.status_code == 200
    assert replay_response.json()["status"] == "running"


def test_risky_external_email_requires_approval(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Email",
            "action_name": "send_external_email",
            "arguments": {
                "recipient": "buyer@acme.com",
                "attachment": "internal_pricing_sheet.xlsx",
                "body": "Attached is pricing.",
            },
            "data_classifications": ["internal_pricing", "customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "require_approval"
    assert payload["status"] == "pending_approval"


def test_trace_pending_approval_blocks_new_steps_until_reviewed(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])

    trace_response = client.post(
        "/v1/traces",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "metadata": {"scenario": "pending_lock"},
        },
    )
    assert trace_response.status_code == 201
    trace_id = trace_response.json()["id"]

    first_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "trace_id": trace_id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "PricingDB",
            "action_name": "apply_discount",
            "arguments": {"discount_percent": 30, "sku": "renewal-pro"},
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )
    assert first_response.status_code == 200
    assert first_response.json()["status"] == "pending_approval"

    second_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "trace_id": trace_id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Email",
            "action_name": "send_external_email",
            "arguments": {"recipient": "buyer@acme.com"},
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )

    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "trace_pending_approval"


def test_critical_database_export_is_blocked(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Postgres",
            "action_name": "export_rows",
            "arguments": {"row_count": 10000, "query": "SELECT * FROM pricing"},
            "data_classifications": ["confidential"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "block"
    assert payload["status"] == "blocked"


def test_non_admin_cannot_delegate_gateway_execution_to_another_user(client, seeded_tenants):
    token = make_token(seeded_tenants["developer_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_acme_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 403


def test_viewer_cannot_invoke_gateway_directly(client, seeded_tenants):
    token = make_token(seeded_tenants["viewer_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["viewer_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_acme_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 403


def test_api_key_can_invoke_gateway_without_user_context(client, db_session, seeded_tenants):
    raw_key, prefix, hashed_key = generate_api_key()
    api_key = AgentAPIKey(
        tenant_id=seeded_tenants["tenant_a"].id,
        agent_id=seeded_tenants["agent_a"].id,
        created_by_user_id=seeded_tenants["admin_a"].id,
        name="Gateway worker",
        prefix=prefix,
        hashed_key=hashed_key,
        scopes=["gateway:invoke"],
        expires_at=utcnow() + timedelta(days=30),
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

    assert response.status_code == 200
    assert response.json()["decision"] == "allow"
