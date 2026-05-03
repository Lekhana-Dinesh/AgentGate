from __future__ import annotations

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import JobStatus, PayloadRetentionClass, ToolCallStatus
from app.core.retention import PAYLOAD_REDACTION_STATUS_PROTECTED, PAYLOAD_REDACTION_STATUS_PURGED, PURGED_PAYLOAD_MARKER
from app.models import AuditEvent, Job, ToolCall
from app.models.base import utcnow
from app.services.approved_execution_service import APPROVAL_EXECUTION_FAILED_EVENT
from app.services.job_service import JobService
from app.services.retention_service import RETENTION_PAYLOAD_PURGED_EVENT
from app.tests.conftest import make_token
from app.tools.github_adapter import GitHubToolAdapter


@pytest.fixture(autouse=True)
def clear_retention_settings(monkeypatch):
    for env_key in (
        "AGENTGATE_JOB_DISPATCH_MODE",
        "AGENTGATE_JOB_BROKER",
        "AGENTGATE_GITHUB_TOKEN",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _install_github_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_client(self, *, base_url: str, auth_headers: dict[str, str], timeout: httpx.Timeout):
        return httpx.Client(
            base_url=base_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "AgentGate/0.1.0",
                "X-GitHub-Api-Version": "2022-11-28",
                **auth_headers,
            },
            timeout=timeout,
            transport=transport,
        )

    monkeypatch.setattr(GitHubToolAdapter, "_build_client", _build_client)


def _create_protected_salesforce_tool_call(client, seeded_tenants, *, token: str, secret: str = "ghp-retention-secret"):
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Read the customer account safely.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {
                "account_id": "acc_retention_001",
                "access_token": secret,
                "authorization": f"Bearer {secret}",
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert response.status_code == 200
    return response


def _create_pending_github_comment_approval(client, seeded_tenants, *, token: str):
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Review the repository and leave notes if needed.",
            "tool_name": "GitHub",
            "action_name": "comment_on_issue_or_pr",
            "arguments": {
                "repository": "octocat/hello-world",
                "repository_visibility": "public",
                "number": 14,
                "body": "Security review approved for posting.",
            },
            "data_classifications": ["internal_pricing"],
            "metadata": {},
        },
    )
    assert response.status_code == 200
    return response


def _get_tool_call(db_session, tool_call_id: str) -> ToolCall:
    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == tool_call_id))
    assert tool_call is not None
    return tool_call


def test_expired_payload_is_purged_without_exposing_sensitive_values(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    secret = "ghp-retention-expired"
    gateway_response = _create_protected_salesforce_tool_call(
        client,
        seeded_tenants,
        token=admin_token,
        secret=secret,
    )
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=2)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    db_session.refresh(tool_call)
    assert purge_response.status_code == 200
    assert secret not in purge_response.text
    assert purge_response.json()["job"]["status"] == "succeeded"
    assert purge_response.json()["result"]["purged"] == 1
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGED
    assert tool_call.request_payload["execution_arguments"][PURGED_PAYLOAD_MARKER] is True

    tool_calls_response = client.get(
        "/v1/gateway/tool-calls",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert tool_calls_response.status_code == 200
    serialized = json.dumps(tool_calls_response.json())
    assert secret not in serialized
    assert "execution_arguments" not in serialized


def test_non_expired_payload_is_not_purged(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    gateway_response = _create_protected_salesforce_tool_call(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    db_session.refresh(tool_call)
    assert purge_response.status_code == 200
    assert purge_response.json()["result"]["purged"] == 0
    assert purge_response.json()["result"]["skipped_non_expired"] == 1
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PROTECTED


def test_legal_hold_payload_is_never_purged(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    gateway_response = _create_protected_salesforce_tool_call(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_retention_class = PayloadRetentionClass.LEGAL_HOLD.value
    tool_call.payload_expires_at = utcnow() - timedelta(days=30)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    db_session.refresh(tool_call)
    assert purge_response.status_code == 200
    assert purge_response.json()["result"]["purged"] == 0
    assert purge_response.json()["result"]["skipped_legal_hold"] == 1
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PROTECTED


def test_retention_dry_run_does_not_mutate_data(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    gateway_response = _create_protected_salesforce_tool_call(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": True, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    db_session.refresh(tool_call)
    assert purge_response.status_code == 200
    assert purge_response.json()["result"]["dry_run"] is True
    assert purge_response.json()["result"]["eligible"] == 1
    assert purge_response.json()["result"]["purged"] == 0
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PROTECTED


def test_retention_purge_creates_audit_event(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    gateway_response = _create_protected_salesforce_tool_call(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    assert purge_response.status_code == 200
    audit_event = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == RETENTION_PAYLOAD_PURGED_EVENT,
            AuditEvent.resource_id == tool_call.id,
        )
    )
    assert audit_event is not None


def test_retention_purge_is_idempotent(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    gateway_response = _create_protected_salesforce_tool_call(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    first_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )
    second_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["result"]["already_purged"] == 1
    purge_events = list(
        db_session.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == RETENTION_PAYLOAD_PURGED_EVENT,
                AuditEvent.resource_id == tool_call.id,
            )
        )
    )
    assert len(purge_events) == 1


def test_cross_tenant_retention_purge_is_blocked(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    other_tenant_token = make_token(seeded_tenants["admin_b"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
        json={
            "agent_id": seeded_tenants["agent_b"].id,
            "user_id": seeded_tenants["admin_b"].id,
            "original_intent": "Read the account safely.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {"account_id": "acc_b_001", "access_token": "tenant-b-secret"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert response.status_code == 200
    tool_call = _get_tool_call(db_session, response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    db_session.refresh(tool_call)
    assert purge_response.status_code == 200
    assert purge_response.json()["result"]["requested"] == 0
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PROTECTED


def test_retention_endpoints_are_privileged_and_sanitized(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    secret = "ghp-retention-api-secret"
    gateway_response = _create_protected_salesforce_tool_call(
        client,
        seeded_tenants,
        token=admin_token,
        secret=secret,
    )
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    forbidden_status = client.get("/v1/retention/status", headers={"Authorization": f"Bearer {viewer_token}"})
    forbidden_purge = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"dry_run": True, "tool_call_ids": [tool_call.id], "limit": 10},
    )
    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": True, "tool_call_ids": [tool_call.id], "limit": 10},
    )

    assert forbidden_status.status_code == 403
    assert forbidden_purge.status_code == 403
    assert purge_response.status_code == 200
    assert secret not in purge_response.text
    assert "execution_arguments" not in purge_response.text


def test_approved_execution_fails_safely_if_payload_was_purged_before_execution(
    client,
    seeded_tenants,
    db_session,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    get_settings.cache_clear()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "id": 900,
                "html_url": "https://github.com/octocat/hello-world/issues/14#issuecomment-900",
                "created_at": "2026-05-02T10:30:00Z",
            },
        )

    _install_github_transport(monkeypatch, handler)

    gateway_response = _create_pending_github_comment_approval(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )
    assert purge_response.status_code == 200
    assert purge_response.json()["job"]["status"] == "queued"
    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert approvals_response.status_code == 200
    approval = next(item for item in approvals_response.json() if item["tool_call"]["id"] == tool_call.id)

    approve_response = client.post(
        f"/v1/approvals/{approval['id']}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approve and execute after purge.", "execute_now": True},
    )
    assert approve_response.status_code == 200
    execution_job_id = approve_response.json()["execution_status"]["job"]["id"]

    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1

    db_session.refresh(tool_call)
    execution_job = db_session.scalar(select(Job).where(Job.id == execution_job_id))
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGED
    assert tool_call.status == ToolCallStatus.FAILED
    assert execution_job is not None
    assert execution_job.status == JobStatus.FAILED
    assert "purged" in (execution_job.last_error or "").lower()
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == APPROVAL_EXECUTION_FAILED_EVENT))


def test_worker_executes_retention_purge_job(client, seeded_tenants, db_session, session_factory, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    gateway_response = _create_protected_salesforce_tool_call(client, seeded_tenants, token=admin_token)
    tool_call = _get_tool_call(db_session, gateway_response.json()["tool_call_id"])
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    purge_response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False, "tool_call_ids": [tool_call.id], "limit": 10},
    )
    job_id = purge_response.json()["job"]["id"]

    assert purge_response.status_code == 200
    assert purge_response.json()["job"]["status"] == "queued"
    assert purge_response.json()["result"] is None
    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1

    db_session.refresh(tool_call)
    job = db_session.scalar(select(Job).where(Job.id == job_id))
    assert tool_call.payload_redaction_status == PAYLOAD_REDACTION_STATUS_PURGED
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
