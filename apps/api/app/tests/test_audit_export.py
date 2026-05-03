from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AuditActorType, JobStatus
from app.models import AuditEvent, AuditExportConfig, Job
from app.services.audit_export_service import (
    AUDIT_EXPORT_RUN_FAILED_EVENT,
    AUDIT_EXPORT_RUN_RETRY_EXHAUSTED_EVENT,
    AUDIT_EXPORT_RUN_SUCCEEDED_EVENT,
    AuditExportDispatcher,
)
from app.services.audit_service import AuditService
from app.services.job_service import JobService
from app.tests.conftest import make_token


@pytest.fixture(autouse=True)
def clear_audit_export_settings(monkeypatch):
    for env_key in (
        "AGENTGATE_JOB_DISPATCH_MODE",
        "AGENTGATE_JOB_BROKER",
        "AGENTGATE_JOB_AUDIT_EXPORT_MAX_ATTEMPTS",
        "AGENTGATE_JOB_AUDIT_EXPORT_RETRY_BACKOFF_SECONDS",
        "AGENTGATE_AUDIT_EXPORT_TIMEOUT_SECONDS",
        "AGENTGATE_TEST_AUDIT_EXPORT_TOKEN",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _install_audit_export_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_client(self, *, timeout_seconds: float, headers: dict[str, str]):
        return httpx.Client(
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    monkeypatch.setattr(AuditExportDispatcher, "_build_client", _build_client)


def _create_audit_event(db_session, seeded_tenants, *, tenant_key: str = "tenant_a", actor_key: str = "admin_a"):
    audit_service = AuditService()
    actor = seeded_tenants[actor_key]
    tenant = seeded_tenants[tenant_key]
    event = audit_service.create_event(
        db_session,
        tenant_id=tenant.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        event_type="security.review.failed",
        resource_type="tool_call",
        resource_id="tool-call-1",
        metadata={
            "authorization": "Bearer ghp_super_secret_token",
            "body": "Contains internal pricing and ghp_super_secret_token",
            "execution_arguments": {
                "__agentgate_encrypted__": True,
                "ciphertext": "abc123",
                "alg": "local-fernet-v1",
            },
            "note": "safe-note",
        },
        ip_address="10.0.0.1",
    )
    db_session.commit()
    return event


def _create_export_config(client, token: str, payload: dict) -> dict:
    response = client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def test_create_audit_export_config_does_not_leak_raw_secret_values(client, seeded_tenants, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    secret_value = "xoxb-raw-should-not-leak"
    monkeypatch.setenv("AGENTGATE_TEST_AUDIT_EXPORT_TOKEN", secret_value)
    get_settings.cache_clear()

    response = client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Tenant A Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
            "token_env_var": "AGENTGATE_TEST_AUDIT_EXPORT_TOKEN",
            "event_type_filters": ["security.review.failed"],
            "severity_filters": ["error"],
            "max_batch_size": 50,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["credential_source"] == "token_env_var"
    assert secret_value not in response.text


def test_audit_export_config_validation_rejects_invalid_secret_ref_without_echoing_value(
    client,
    seeded_tenants,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    raw_secret = "xoxb-unsafe-secret"

    response = client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Unsafe Splunk",
            "destination_type": "splunk_hec",
            "enabled": True,
            "endpoint_url": "https://splunk.example.test/services/collector/event",
            "secret_ref": raw_secret,
        },
    )

    assert response.status_code == 422
    assert raw_secret not in response.text


def test_audit_export_config_rejects_secret_like_endpoint_url_without_echoing_value(
    client,
    seeded_tenants,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    raw_secret = "dd-api-key-should-not-leak"

    response = client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Unsafe Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": f"https://siem.example.test/agentgate?api_key={raw_secret}",
        },
    )

    assert response.status_code == 422
    assert raw_secret not in response.text


def test_webhook_audit_export_sends_sanitized_events(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants)
    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Tenant A Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
            "event_type_filters": ["security.review.failed"],
            "severity_filters": ["error"],
            "max_batch_size": 100,
        },
    )

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    _install_audit_export_transport(monkeypatch, handler)

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )

    assert run_response.status_code == 200
    assert run_response.json()["job"]["status"] == "succeeded"
    assert len(captured_payloads) == 1
    serialized = json.dumps(captured_payloads[0])
    assert "ghp_super_secret_token" not in serialized
    assert "__agentgate_encrypted__" not in serialized
    assert captured_payloads[0]["events"][0]["metadata"]["authorization"] == "[REDACTED]"
    assert captured_payloads[0]["events"][0]["metadata"]["execution_arguments"] == "[PROTECTED]"


def test_audit_export_cursor_prevents_duplicate_exports(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants)
    audit_service = AuditService()
    audit_service.create_event(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        actor_type=AuditActorType.USER,
        actor_id=seeded_tenants["admin_a"].id,
        event_type="security.review.failed",
        resource_type="tool_call",
        resource_id="tool-call-2",
        metadata={"note": "second"},
    )
    db_session.commit()

    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Cursor Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
            "event_type_filters": ["security.review.failed"],
            "max_batch_size": 100,
        },
    )

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    _install_audit_export_transport(monkeypatch, handler)

    first_run = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )
    second_run = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )

    assert first_run.status_code == 200
    assert first_run.json()["result"]["exported_events"] == 2
    assert second_run.status_code == 200
    assert second_run.json()["result"]["exported_events"] == 0
    assert len(captured_payloads) == 1


def test_multiple_tenants_are_isolated_for_audit_export(client, seeded_tenants, db_session, monkeypatch):
    admin_token_a = make_token(seeded_tenants["admin_a"])
    admin_token_b = make_token(seeded_tenants["admin_b"])
    _create_audit_event(db_session, seeded_tenants, tenant_key="tenant_a", actor_key="admin_a")
    _create_audit_event(db_session, seeded_tenants, tenant_key="tenant_b", actor_key="admin_b")
    config = _create_export_config(
        client,
        admin_token_a,
        {
            "name": "Tenant A Export",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/tenant-a",
            "event_type_filters": ["security.review.failed"],
        },
    )

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    _install_audit_export_transport(monkeypatch, handler)

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token_a}"},
        json={"dry_run": False},
    )
    other_tenant_list = client.get(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {admin_token_b}"},
    )
    other_tenant_status = client.get(
        f"/v1/audit-exports/{config['id']}/status",
        headers={"Authorization": f"Bearer {admin_token_b}"},
    )

    assert run_response.status_code == 200
    assert len(captured_payloads) == 1
    assert all(item["tenant_id"] == seeded_tenants["tenant_a"].id for item in captured_payloads[0]["events"])
    assert all(item["id"] != config["id"] for item in other_tenant_list.json())
    assert other_tenant_status.status_code == 404


def test_disabled_audit_export_config_does_not_run(client, seeded_tenants, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Disabled Export",
            "destination_type": "webhook",
            "enabled": False,
            "endpoint_url": "https://siem.example.test/agentgate",
        },
    )
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(200, json={"ok": True})

    _install_audit_export_transport(monkeypatch, handler)

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )

    assert run_response.status_code == 409
    assert outbound_calls["count"] == 0


def test_inline_export_failure_records_failed_job_and_audit_event(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants)
    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Failing Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
            "event_type_filters": ["security.review.failed"],
        },
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad auth xoxb-should-not-leak"})

    _install_audit_export_transport(monkeypatch, handler)

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )

    job = db_session.scalar(select(Job).where(Job.tenant_id == seeded_tenants["tenant_a"].id).order_by(Job.created_at.desc()))
    failed_event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == AUDIT_EXPORT_RUN_FAILED_EVENT))

    assert run_response.status_code == 500
    assert "xoxb-should-not-leak" not in run_response.text
    assert job is not None
    assert job.status == JobStatus.FAILED
    assert failed_event is not None
    assert "xoxb-should-not-leak" not in json.dumps(failed_event.metadata_json)


def test_retryable_export_failures_exhaust_safely(
    client,
    seeded_tenants,
    db_session,
    session_factory,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_JOB_AUDIT_EXPORT_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("AGENTGATE_JOB_AUDIT_EXPORT_RETRY_BACKOFF_SECONDS", "0")
    get_settings.cache_clear()

    _create_audit_event(db_session, seeded_tenants)
    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Retrying Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
            "event_type_filters": ["security.review.failed"],
        },
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "ratelimited"})

    _install_audit_export_transport(monkeypatch, handler)

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )
    assert run_response.status_code == 200

    job_service = JobService()
    assert job_service.process_due_jobs(session_factory=session_factory, limit=1) == 1
    assert job_service.process_due_jobs(session_factory=session_factory, limit=1) == 1

    job = db_session.scalar(select(Job).where(Job.id == run_response.json()["job"]["id"]))
    retry_event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == AUDIT_EXPORT_RUN_RETRY_EXHAUSTED_EVENT))

    assert job is not None
    assert job.status == JobStatus.RETRY_EXHAUSTED
    assert retry_event is not None


def test_secret_refs_fail_closed_for_audit_export_destinations(client, seeded_tenants, db_session):
    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants)
    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Unsupported Secret Ref",
            "destination_type": "splunk_hec",
            "enabled": True,
            "endpoint_url": "https://splunk.example.test/services/collector/event",
            "secret_ref": "secret_ref:tenant-a/splunk-hec",
            "event_type_filters": ["security.review.failed"],
        },
    )

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )

    assert run_response.status_code == 500
    assert "tenant-a/splunk-hec" not in run_response.text


def test_audit_export_endpoints_enforce_rbac(client, seeded_tenants):
    viewer_token = make_token(seeded_tenants["viewer_a"])

    list_response = client.get(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    create_response = client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "name": "Viewer Attempt",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
        },
    )

    assert list_response.status_code == 403
    assert create_response.status_code == 403
