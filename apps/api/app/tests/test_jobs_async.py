from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import JobStatus, ToolCallStatus, TraceStatus
from app.core.errors import AppError
from app.models import AuditEvent, ExecutionTrace, Job, ToolCall
from app.notifications.slack_notifier import SLACK_API_BASE_URL, SlackNotifier
from app.services.approved_execution_service import (
    APPROVAL_EXECUTION_FAILED_EVENT,
    APPROVAL_EXECUTION_QUEUED_EVENT,
    APPROVAL_EXECUTION_SUCCEEDED_EVENT,
)
from app.services.job_service import JobService
from app.services.notification_service import (
    SLACK_FAILED_EVENT,
    SLACK_QUEUED_EVENT,
    SLACK_RETRY_EXHAUSTED_EVENT,
    SLACK_SENT_EVENT,
)
from app.tests.conftest import make_token
from app.tools.github_adapter import GitHubToolAdapter
from app.tools.mock_adapter import MockToolAdapter


@pytest.fixture(autouse=True)
def clear_async_job_settings(monkeypatch):
    for env_key in (
        "AGENTGATE_JOB_DISPATCH_MODE",
        "AGENTGATE_JOB_BROKER",
        "AGENTGATE_JOB_SLACK_MAX_ATTEMPTS",
        "AGENTGATE_JOB_SLACK_RETRY_BACKOFF_SECONDS",
        "AGENTGATE_SLACK_NOTIFICATIONS_ENABLED",
        "AGENTGATE_SLACK_DEFAULT_CHANNEL",
        "AGENTGATE_SLACK_BOT_TOKEN",
        "AGENTGATE_GITHUB_TOKEN",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _install_slack_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_client(self, *, token: str, timeout_seconds: float):
        return httpx.Client(
            base_url=SLACK_API_BASE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=timeout_seconds,
            transport=transport,
        )

    monkeypatch.setattr(SlackNotifier, "_build_client", _build_client)


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


def _create_pending_email_approval(client, seeded_tenants, *, token: str):
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
    assert response.json()["decision"] == "require_approval"
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
    assert response.json()["decision"] == "require_approval"
    return response


def _get_pending_approval(client, token: str, *, tool_name: str):
    response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    return next(item for item in response.json() if item["tool_call"]["tool_name"] == tool_name)


def test_worker_mode_queues_slack_notification_job_without_inline_delivery(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    get_settings.cache_clear()

    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(200, json={"ok": True, "channel": "C123456", "ts": "1710000000.000100"})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval = _get_pending_approval(client, admin_token, tool_name="Email")
    job = db_session.scalar(select(Job).where(Job.id == approval["notification_status"]["job_id"]))

    assert outbound_calls["count"] == 0
    assert approval["notification_status"]["status"] == "queued"
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == SLACK_QUEUED_EVENT)) is not None


def test_worker_processes_slack_notification_job_and_records_sent_audit(
    client,
    seeded_tenants,
    db_session,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    get_settings.cache_clear()

    sent_messages: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_messages.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"ok": True, "channel": "C123456", "ts": "1710000000.000100"})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    processed = JobService().process_due_jobs(session_factory=session_factory, limit=5)
    approval = _get_pending_approval(client, admin_token, tool_name="Email")

    assert processed == 1
    assert len(sent_messages) == 1
    assert approval["notification_status"]["status"] == "sent"
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == SLACK_SENT_EVENT)) is not None


def test_worker_retries_slack_notification_until_retry_exhausted(
    client,
    seeded_tenants,
    db_session,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("AGENTGATE_JOB_SLACK_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("AGENTGATE_JOB_SLACK_RETRY_BACKOFF_SECONDS", "0")
    get_settings.cache_clear()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ok": False, "error": "ratelimited"})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    job_service = JobService()
    assert job_service.process_due_jobs(session_factory=session_factory, limit=1) == 1
    assert job_service.process_due_jobs(session_factory=session_factory, limit=1) == 1

    approval = _get_pending_approval(client, admin_token, tool_name="Email")
    job = db_session.scalar(select(Job).where(Job.id == approval["notification_status"]["job_id"]))

    assert approval["notification_status"]["status"] == "retry_exhausted"
    assert job is not None
    assert job.status == JobStatus.RETRY_EXHAUSTED
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == SLACK_FAILED_EVENT)) is not None
    assert (
        db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == SLACK_RETRY_EXHAUSTED_EVENT))
        is not None
    )


def test_approval_execution_job_is_queued_on_approval_in_worker_mode(client, seeded_tenants, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval = _get_pending_approval(client, reviewer_token, tool_name="Email")

    response = client.post(
        f"/v1/approvals/{approval['id']}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approved for async execution.", "execute_now": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["tool_call"]["status"] == "allowed"
    assert payload["execution_status"]["status"] == "queued"


def test_approved_execution_job_executes_once_in_worker_mode(
    client,
    seeded_tenants,
    db_session,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    calls = {"count": 0}
    original_execute = MockToolAdapter.execute

    def wrapped_execute(self, request):
        if request.tool_name == "Email" and "send" in request.action_name.lower():
            calls["count"] += 1
        return original_execute(self, request)

    monkeypatch.setattr(MockToolAdapter, "execute", wrapped_execute)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval = _get_pending_approval(client, reviewer_token, tool_name="Email")
    response = client.post(
        f"/v1/approvals/{approval['id']}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approve once.", "execute_now": True},
    )
    assert response.status_code == 200

    job_service = JobService()
    assert job_service.process_due_jobs(session_factory=session_factory, limit=5) == 1
    assert job_service.process_due_jobs(session_factory=session_factory, limit=5) == 0

    execution_job_id = response.json()["execution_status"]["job"]["id"]
    with session_factory() as db:
        job_service.process_job(db, job_id=execution_job_id, raise_on_error=False)

    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == response.json()["tool_call_id"]))
    assert calls["count"] == 1
    assert tool_call is not None
    assert tool_call.status == ToolCallStatus.EXECUTED
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == APPROVAL_EXECUTION_SUCCEEDED_EVENT))
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == APPROVAL_EXECUTION_QUEUED_EVENT))


def test_worker_execution_job_decrypts_payload_only_when_job_runs(
    client,
    seeded_tenants,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    get_settings.cache_clear()

    posted_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        posted_bodies.append(body["body"])
        return httpx.Response(
            201,
            json={
                "id": 900,
                "html_url": "https://github.com/octocat/hello-world/issues/14#issuecomment-900",
                "created_at": "2026-05-02T10:30:00Z",
            },
        )

    _install_github_transport(monkeypatch, handler)

    _create_pending_github_comment_approval(client, seeded_tenants, token=admin_token)
    approval = _get_pending_approval(client, reviewer_token, tool_name="GitHub")
    response = client.post(
        f"/v1/approvals/{approval['id']}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approved for async secure execution.", "execute_now": True},
    )
    assert response.status_code == 200
    assert posted_bodies == []

    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1
    assert posted_bodies == ["Security review approved for posting."]


def test_failed_execution_job_updates_tool_call_trace_and_audit(
    client,
    seeded_tenants,
    db_session,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    original_execute = MockToolAdapter.execute

    def failing_execute(self, request):
        if request.tool_name == "Email" and "send" in request.action_name.lower():
            raise AppError("Mock approved execution failed.", status_code=503, code="mock_execution_failed")
        return original_execute(self, request)

    monkeypatch.setattr(MockToolAdapter, "execute", failing_execute)

    gateway_response = _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval = _get_pending_approval(client, reviewer_token, tool_name="Email")
    response = client.post(
        f"/v1/approvals/{approval['id']}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approve and test failure path.", "execute_now": True},
    )
    assert response.status_code == 200

    assert JobService().process_due_jobs(session_factory=session_factory, limit=5) == 1

    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == gateway_response.json()["tool_call_id"]))
    trace = db_session.scalar(select(ExecutionTrace).where(ExecutionTrace.id == tool_call.trace_id))

    assert tool_call is not None
    assert tool_call.status == ToolCallStatus.FAILED
    assert trace is not None
    assert trace.status == TraceStatus.FAILED
    assert db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == APPROVAL_EXECUTION_FAILED_EVENT))


def test_jobs_endpoint_is_tenant_scoped(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    other_tenant_token = make_token(seeded_tenants["admin_b"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    get_settings.cache_clear()

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    job = db_session.scalar(select(Job).order_by(Job.created_at.desc()))

    developer_response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {developer_token}"})
    other_tenant_response = client.get("/v1/jobs", headers={"Authorization": f"Bearer {other_tenant_token}"})
    cross_tenant_detail = client.get(f"/v1/jobs/{job.id}", headers={"Authorization": f"Bearer {other_tenant_token}"})

    assert developer_response.status_code == 200
    assert any(item["id"] == job.id for item in developer_response.json())
    assert other_tenant_response.status_code == 200
    assert all(item["id"] != job.id for item in other_tenant_response.json())
    assert cross_tenant_detail.status_code == 404


def test_inline_job_fallback_still_executes_approved_tool_call(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    get_settings.cache_clear()

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval = _get_pending_approval(client, reviewer_token, tool_name="Email")
    response = client.post(
        f"/v1/approvals/{approval['id']}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Inline mode should still execute.", "execute_now": True},
    )

    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == response.json()["tool_call_id"]))
    job = db_session.scalar(select(Job).where(Job.id == response.json()["execution_status"]["job"]["id"]))

    assert response.status_code == 200
    assert response.json()["execution_status"]["status"] == "succeeded"
    assert tool_call is not None
    assert tool_call.status == ToolCallStatus.EXECUTED
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
