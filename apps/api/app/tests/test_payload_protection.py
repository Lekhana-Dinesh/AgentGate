from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.core.enums import AuditActorType
from app.core.errors import AppError
from app.core.redaction import REDACTED_VALUE
from app.models import AuditEvent, ToolCall
from app.security.key_management import get_key_provider
from app.security.payload_protection import ENCRYPTED_MARKER, LocalSymmetricPayloadEncryptionProvider
from app.services.audit_service import AuditService
from app.services.payload_service import PayloadProtectionContext, PayloadService
from app.tests.conftest import make_token
from app.tools.github_adapter import GitHubToolAdapter


@pytest.fixture(autouse=True)
def clear_payload_settings_cache(monkeypatch):
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS_JSON", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEY_VERSIONS", raising=False)
    monkeypatch.delenv("AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEY_VERSIONS_JSON", raising=False)
    monkeypatch.delenv("AGENTGATE_KEY_PROVIDER", raising=False)
    get_settings.cache_clear()
    get_key_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_key_provider.cache_clear()


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


def test_local_payload_provider_uses_deterministic_dev_fallback():
    provider = LocalSymmetricPayloadEncryptionProvider()
    envelope = provider.encrypt("demo-secret")

    assert envelope[ENCRYPTED_MARKER] is True
    assert envelope["alg"] == "local-fernet-v1"
    assert envelope["algorithm"] == "local-fernet-v1"
    assert envelope["key_ref"] == "local-dev-fallback"
    assert envelope["provider"] == "env"
    assert envelope["key_version"] == "dev-fallback"
    assert envelope["created_at"]
    assert provider.decrypt(envelope) == "demo-secret"


def test_payload_service_detects_sensitive_fields_and_encrypts_envelope():
    service = PayloadService()
    bundle = service.protect_payload(
        {
            "account_id": "acc_demo_001",
            "access_token": "Bearer ghp_ultra_secret_token",
            "body": "internal pricing goes here",
        },
        context=PayloadProtectionContext(
            tool_name="Email",
            action_name="send_external_email",
            data_classifications=["internal_pricing"],
        ),
    )

    assert bundle.protection_version == "local-fernet-v1"
    assert bundle.retention_class == "extended"
    assert bundle.expires_at is not None
    assert bundle.redaction_status == "protected"
    assert "$.access_token" in bundle.protected_field_paths
    assert "$.body" in bundle.protected_field_paths
    assert bundle.protected_payload["access_token"][ENCRYPTED_MARKER] is True
    assert bundle.protected_payload["body"][ENCRYPTED_MARKER] is True
    assert bundle.sanitized_payload["access_token"] == REDACTED_VALUE
    assert bundle.sanitized_payload["body"] == REDACTED_VALUE
    assert service.decrypt_payload_for_execution(bundle.protected_payload)["body"] == "internal pricing goes here"


def test_corrupted_protected_payload_fails_closed():
    service = PayloadService()
    bundle = service.protect_payload(
        {"access_token": "Bearer ghp_ultra_secret_token"},
        context=PayloadProtectionContext(tool_name="Salesforce", action_name="read_account"),
    )
    corrupted = dict(bundle.protected_payload)
    corrupted["access_token"] = {**corrupted["access_token"], "ciphertext": "not-valid"}

    with pytest.raises(AppError) as exc_info:
        service.decrypt_payload_for_execution(corrupted)

    assert exc_info.value.code == "protected_payload_invalid"


def test_gateway_stores_protected_execution_arguments_and_sanitizes_responses(
    client,
    seeded_tenants,
    db_session,
):
    token = make_token(seeded_tenants["admin_a"])
    secret_token = "ghp_internal_super_secret"
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Prepare a safe customer account summary.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {
                "account_id": "acc_acme_001",
                "access_token": secret_token,
                "authorization": f"Bearer {secret_token}",
                "password": "super-secret-password",
            },
            "data_classifications": ["customer_data"],
            "metadata": {"api_key": secret_token},
        },
    )

    assert response.status_code == 200
    assert secret_token not in response.text

    tool_call_id = response.json()["tool_call_id"]
    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == tool_call_id))
    assert tool_call is not None
    assert tool_call.payload_protection_version == "local-fernet-v1"
    assert tool_call.payload_retention_class == "short_lived"
    assert tool_call.payload_expires_at is not None
    assert tool_call.payload_redaction_status == "protected"
    assert tool_call.request_payload["execution_arguments"]["access_token"][ENCRYPTED_MARKER] is True
    assert tool_call.request_payload["execution_arguments"]["authorization"][ENCRYPTED_MARKER] is True
    assert tool_call.request_payload["execution_arguments"]["password"][ENCRYPTED_MARKER] is True
    assert tool_call.request_payload["arguments"]["access_token"] == REDACTED_VALUE
    assert tool_call.request_payload["metadata"]["api_key"] == REDACTED_VALUE

    tool_calls_response = client.get(
        "/v1/gateway/tool-calls",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tool_calls_response.status_code == 200
    serialized = json.dumps(tool_calls_response.json())
    assert secret_token not in serialized
    assert ENCRYPTED_MARKER not in serialized


def test_approval_execution_decrypts_protected_github_comment_body(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
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

    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {admin_token}"},
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
    assert gateway_response.status_code == 200
    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == gateway_response.json()["tool_call_id"]))
    assert tool_call.request_payload["execution_arguments"]["body"][ENCRYPTED_MARKER] is True

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    approval_id = next(
        item["id"]
        for item in approvals_response.json()
        if item["tool_call"]["tool_name"] == "GitHub"
    )

    decision_response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"approver_comment": "Approved for secure execution.", "execute_now": True},
    )
    assert decision_response.status_code == 200
    assert posted_bodies == ["Security review approved for posting."]


def test_approvals_and_traces_only_expose_sanitized_payload_views(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    secret = "ghp_trace_secret_token"

    trace_response = client.post(
        "/v1/traces",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "original_intent": "Prepare and review internal pricing notes.",
            "metadata": {"authorization": f"Bearer {secret}", "body": "internal pricing attached"},
        },
    )
    assert trace_response.status_code == 201
    trace_id = trace_response.json()["id"]

    step_response = client.post(
        f"/v1/traces/{trace_id}/steps",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "type": "thought",
            "content": "Evaluating sensitive context.",
            "metadata": {"access_token": secret, "message": "contains secret-like details"},
        },
    )
    assert step_response.status_code == 201

    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "trace_id": trace_id,
            "original_intent": "Prepare and review internal pricing notes.",
            "tool_name": "Email",
            "action_name": "send_external_email",
            "arguments": {
                "recipient": "buyer@acme.com",
                "body": f"internal pricing and {secret}",
                "authorization": f"Bearer {secret}",
            },
            "data_classifications": ["internal_pricing"],
            "metadata": {"api_key": secret},
        },
    )
    assert gateway_response.status_code == 200

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approvals_response.status_code == 200
    approvals_payload = json.dumps(approvals_response.json())
    assert secret not in approvals_payload
    assert ENCRYPTED_MARKER not in approvals_payload

    trace_replay = client.get(
        f"/v1/traces/{trace_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert trace_replay.status_code == 200
    trace_payload = trace_replay.json()
    assert secret not in json.dumps(trace_payload)
    assert trace_payload["metadata_json"]["authorization"] == REDACTED_VALUE
    assert trace_payload["metadata_json"]["body"] == REDACTED_VALUE
    assert trace_payload["steps"][0]["metadata_json"]["access_token"] == REDACTED_VALUE
    assert trace_payload["steps"][0]["metadata_json"]["message"] == REDACTED_VALUE


def test_audit_service_and_audit_api_do_not_expose_secret_metadata(client, db_session, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    audit_service = AuditService()
    secret = "xoxb-super-secret"

    audit_service.create_event(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        actor_type=AuditActorType.USER,
        actor_id=seeded_tenants["admin_a"].id,
        event_type="test.audit.secret",
        resource_type="tool_call",
        resource_id="resource-1",
        metadata={"authorization": f"Bearer {secret}", "body": "internal pricing note", "note": "safe"},
    )
    db_session.commit()

    event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == "test.audit.secret"))
    assert event is not None
    assert event.metadata_json["authorization"] == REDACTED_VALUE
    assert event.metadata_json["body"] == REDACTED_VALUE

    audit_response = client.get(
        "/v1/audit/events?event_type=test.audit.secret",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit_response.status_code == 200
    payload = json.dumps(audit_response.json())
    assert secret not in payload
    assert ENCRYPTED_MARKER not in payload


def test_production_settings_fail_when_payload_encryption_key_is_missing():
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            debug=False,
            secret_key="0123456789abcdef0123456789abcdef",
            payload_encryption_key=None,
        )
