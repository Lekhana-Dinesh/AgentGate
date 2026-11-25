from __future__ import annotations

from sqlalchemy import select
import pytest

from app.core.config import get_settings
from app.models import Tool
from app.services.job_service import JobService
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


def test_sales_worker_completion_preserves_later_pending_approval(
    client, session_factory, seeded_tenants, monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_JOB_BROKER", "database")
    get_settings.cache_clear()
    headers = {"Authorization": f"Bearer {make_token(seeded_tenants['admin_a'])}"}
    run = client.post("/v1/demo/run-sales-agent-risk-scenario", headers=headers)
    assert run.status_code == 200
    assert run.json()["trace_status"] == "pending_approval"

    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1
    trace = client.get(f"/v1/traces/{run.json()['trace_id']}", headers=headers).json()
    assert trace["status"] == "pending_approval"
    assert any("Approved execution completed for PricingDB" in step["content"] for step in trace["steps"])


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


@pytest.mark.parametrize("remove_mock_after_approval", [False, True])
def test_governed_github_demo_queues_and_worker_requires_mock(
    client, db_session, session_factory, seeded_tenants, monkeypatch, remove_mock_after_approval,
):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_JOB_BROKER", "database")
    get_settings.cache_clear()
    headers = {"Authorization": f"Bearer {make_token(seeded_tenants['admin_a'])}"}
    route = "/v1/demo/run-governed-github-workflow"
    tool = db_session.scalar(
        select(Tool).where(Tool.tenant_id == seeded_tenants["tenant_a"].id, Tool.name == "GitHub")
    )
    assert tool is not None
    tool.config = {**(tool.config or {}), "demo_safe_mock": False}
    db_session.commit()
    refused = client.post(route, headers=headers)
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "demo_safe_connector_required"

    tool.config = {**tool.config, "demo_safe_mock": True}
    db_session.commit()
    submitted = client.post(route, headers=headers)
    assert submitted.status_code == 200
    payload = submitted.json()
    assert payload["execution_mode"] == "queued"
    assert payload["trace_status"] == "running"
    assert payload["no_live_external_call"] is True
    assert any(event["event_type"] == "demo.scenario.submitted" for event in payload["audit_events"])

    if remove_mock_after_approval:
        tool.config = {**tool.config, "demo_safe_mock": False}
        db_session.commit()

    def unexpected_client(*args, **kwargs):
        pytest.fail("The seeded demo must never open a live GitHub client.")

    monkeypatch.setattr(GitHubToolAdapter, "_build_client", unexpected_client)
    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1
    trace = client.get(f"/v1/traces/{payload['trace_id']}", headers=headers).json()
    assert trace["status"] == ("failed" if remove_mock_after_approval else "completed")
