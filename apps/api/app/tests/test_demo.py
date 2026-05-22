from __future__ import annotations

from sqlalchemy import select

from app.models import Tool
from app.tests.conftest import make_token
from app.tools.github_adapter import GitHubToolAdapter


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


def test_governed_github_demo_runs_end_to_end_without_live_github_call(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    token = make_token(seeded_tenants["admin_a"])
    github_tool = db_session.scalar(
        select(Tool).where(
            Tool.tenant_id == seeded_tenants["tenant_a"].id,
            Tool.name == "GitHub",
        )
    )
    assert github_tool is not None
    github_tool.config = {
        **(github_tool.config or {}),
        "demo_safe_mock": True,
    }
    db_session.commit()

    def _unexpected_client(*args, **kwargs):
        raise AssertionError("Live GitHub client should not be built in demo-safe mode.")

    monkeypatch.setattr(GitHubToolAdapter, "_build_client", _unexpected_client)

    response = client.post(
        "/v1/demo/run-governed-github-workflow",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"] == "github_governed_workflow"
    assert payload["simulation"]["approval_required"] is True
    assert payload["governed_attempt"]["decision"] == "require_approval"
    assert payload["governed_attempt"]["status"] == "pending_approval"
    assert payload["approval"]["status"] == "approved"
    assert payload["tool_call"]["status"] == "executed"
    assert payload["trace_status"] == "completed"
    assert payload["execution_mode"] == "demo_safe_mock"
    assert payload["no_live_external_call"] is True
    assert any(event["event_type"] == "approval.execution.succeeded" for event in payload["audit_events"])

    trace_response = client.get(
        f"/v1/traces/{payload['trace_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_response.status_code == 200
    trace_payload = trace_response.json()
    assert trace_payload["status"] == "completed"
    assert any(step["type"] == "approval" for step in trace_payload["steps"])
    assert any("Approved execution completed" in step["content"] for step in trace_payload["steps"])


def test_governed_github_demo_is_tenant_scoped(client, seeded_tenants):
    tenant_b_token = make_token(seeded_tenants["admin_b"])

    response = client.post(
        "/v1/demo/run-governed-github-workflow",
        headers={"Authorization": f"Bearer {tenant_b_token}"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "demo_agent_missing"
