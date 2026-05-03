from __future__ import annotations

from app.tests.conftest import make_token


def test_security_reviewer_can_approve_and_execute_pending_mock_call(client, seeded_tenants):
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
            "arguments": {
                "recipient": "buyer@acme.com",
                "attachment": "internal_pricing_sheet.xlsx",
                "body": "Attached is pricing.",
            },
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    approval_id = approvals_response.json()[0]["id"]

    decision_response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approved for demo flow.", "execute_now": True},
    )

    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"


def test_rejection_requires_comment(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])

    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "PricingDB",
            "action_name": "apply_discount",
            "arguments": {"discount_percent": 30, "sku": "renewal-pro"},
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    approval_id = approvals_response.json()[0]["id"]

    reject_response = client.post(
        f"/v1/approvals/{approval_id}/reject",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"execute_now": False},
    )

    assert reject_response.status_code in {400, 422}


def test_approval_without_immediate_execution_reopens_trace_for_resume(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])

    trace_response = client.post(
        "/v1/traces",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "metadata": {"scenario": "approval_resume"},
        },
    )
    trace_id = trace_response.json()["id"]

    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {admin_token}"},
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
    assert gateway_response.status_code == 200

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    approval_id = approvals_response.json()[0]["id"]

    decision_response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approved, continue the run.", "execute_now": False},
    )
    assert decision_response.status_code == 200

    trace_replay = client.get(
        f"/v1/traces/{trace_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert trace_replay.status_code == 200
    assert trace_replay.json()["status"] == "running"

    resumed_step = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "trace_id": trace_id,
            "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_acme_001"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert resumed_step.status_code == 200
