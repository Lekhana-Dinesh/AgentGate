from __future__ import annotations

import json

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditEvent
from app.notifications.slack_notifier import SLACK_API_BASE_URL, SlackNotifier
from app.services.notification_service import SLACK_FAILED_EVENT, SLACK_SENT_EVENT
from app.tests.conftest import make_token


@pytest.fixture(autouse=True)
def clear_slack_settings_cache(monkeypatch):
    for env_key in (
        "AGENTGATE_SLACK_NOTIFICATIONS_ENABLED",
        "AGENTGATE_SLACK_BOT_TOKEN_ENV_VAR",
        "AGENTGATE_SLACK_DEFAULT_CHANNEL",
        "AGENTGATE_SLACK_BOT_TOKEN",
        "AGENTGATE_PUBLIC_APP_URL",
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


def _create_pending_email_approval(
    client,
    seeded_tenants,
    *,
    token: str,
    body: str = "Attached is pricing.",
    attachment: str = "internal_pricing_sheet.xlsx",
):
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
                "attachment": attachment,
                "body": body,
            },
            "data_classifications": ["internal_pricing", "customer_data"],
            "metadata": {},
        },
    )
    assert response.status_code == 200
    assert response.json()["decision"] == "require_approval"
    return response


def _get_pending_email_approval(client, token: str):
    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert approvals_response.status_code == 200
    approval = next(item for item in approvals_response.json() if item["tool_call"]["tool_name"] == "Email")
    return approval, approvals_response


def _notification_events(db_session, *, approval_id: str):
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.resource_type == "approval_request",
                AuditEvent.resource_id == approval_id,
                AuditEvent.event_type.in_([SLACK_SENT_EVENT, SLACK_FAILED_EVENT]),
            )
            .order_by(AuditEvent.created_at.desc())
        )
    )


def test_approval_creation_with_slack_disabled_does_not_attempt_notification(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(200, json={"ok": True})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval, _ = _get_pending_email_approval(client, admin_token)

    assert approval["notification_status"]["status"] == "disabled"
    assert outbound_calls["count"] == 0
    assert _notification_events(db_session, approval_id=approval["id"]) == []


def test_approval_creation_with_slack_enabled_sends_notification_and_records_audit(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("AGENTGATE_PUBLIC_APP_URL", "http://localhost:3000")
    get_settings.cache_clear()

    sent_messages: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat.postMessage")
        payload = json.loads(request.content.decode("utf-8"))
        sent_messages.append(payload)
        return httpx.Response(200, json={"ok": True, "channel": "C123456", "ts": "1710000000.000100"})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval, _ = _get_pending_email_approval(client, admin_token)
    events = _notification_events(db_session, approval_id=approval["id"])

    assert len(sent_messages) == 1
    assert sent_messages[0]["channel"] == "C123456"
    assert "Open AgentGate approval inbox" in json.dumps(sent_messages[0])
    assert approval["notification_status"]["status"] == "sent"
    assert approval["notification_status"]["channel"] == "C123456"
    assert any(event.event_type == SLACK_SENT_EVENT for event in events)

    status_response = client.get(
        f"/v1/approvals/{approval['id']}/notification-status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "sent"


def test_slack_missing_token_does_not_fail_approval_creation(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    get_settings.cache_clear()

    response = _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval, _ = _get_pending_email_approval(client, admin_token)
    events = _notification_events(db_session, approval_id=approval["id"])

    assert response.status_code == 200
    assert approval["notification_status"]["status"] == "failed"
    assert approval["notification_status"]["error_code"] == "slack_token_missing"
    assert any(event.metadata_json.get("code") == "slack_token_missing" for event in events)


@pytest.mark.parametrize("status_code", [401, 403])
def test_slack_auth_failures_do_not_leak_token_or_break_gateway(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
    status_code: int,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    secret_token = "xoxb-super-secret-token"
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", secret_token)
    get_settings.cache_clear()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"ok": False, "error": "invalid_auth", "detail": secret_token})

    _install_slack_transport(monkeypatch, handler)

    response = _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval, approvals_response = _get_pending_email_approval(client, admin_token)
    events = _notification_events(db_session, approval_id=approval["id"])
    event_payload = json.dumps([event.metadata_json for event in events])

    assert response.status_code == 200
    assert approval["notification_status"]["status"] == "failed"
    assert approval["notification_status"]["error_code"] == "slack_auth_failed"
    assert secret_token not in approvals_response.text
    assert secret_token not in event_payload


def test_slack_rate_limit_is_recorded_non_fatally(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    get_settings.cache_clear()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ok": False, "error": "ratelimited"})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval, _ = _get_pending_email_approval(client, admin_token)
    events = _notification_events(db_session, approval_id=approval["id"])

    assert approval["notification_status"]["status"] == "failed"
    assert approval["notification_status"]["error_code"] == "slack_rate_limited"
    assert any(event.metadata_json.get("code") == "slack_rate_limited" for event in events)


def test_slack_timeout_is_recorded_non_fatally(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    get_settings.cache_clear()

    def handler(_: httpx.Request):
        raise httpx.ReadTimeout("Slack timed out")

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(client, seeded_tenants, token=admin_token)
    approval, _ = _get_pending_email_approval(client, admin_token)
    events = _notification_events(db_session, approval_id=approval["id"])

    assert approval["notification_status"]["status"] == "failed"
    assert approval["notification_status"]["error_code"] == "slack_timeout"
    assert any(event.metadata_json.get("code") == "slack_timeout" for event in events)


def test_slack_message_redacts_sensitive_values_and_truncates_payload(
    client,
    seeded_tenants,
    db_session,
    monkeypatch,
):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    monkeypatch.setenv("AGENTGATE_PUBLIC_APP_URL", "http://localhost:3000")
    get_settings.cache_clear()

    secret_body = "Bearer ghp_ultra_secret_token " + ("x" * 1200)
    captured_payloads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(request.content.decode("utf-8"))
        return httpx.Response(200, json={"ok": True, "channel": "C123456", "ts": "1710000000.000200"})

    _install_slack_transport(monkeypatch, handler)

    _create_pending_email_approval(
        client,
        seeded_tenants,
        token=admin_token,
        body=secret_body,
        attachment="super-confidential-pricing-sheet.xlsx",
    )
    approval, _ = _get_pending_email_approval(client, admin_token)
    events = _notification_events(db_session, approval_id=approval["id"])
    serialized_payload = captured_payloads[0]

    assert len(captured_payloads) == 1
    assert "ghp_ultra_secret_token" not in serialized_payload
    assert "super-confidential-pricing-sheet.xlsx" not in serialized_payload
    assert "[REDACTED]" in serialized_payload
    assert len(serialized_payload) < 4000
    assert any(event.event_type == SLACK_SENT_EVENT for event in events)


def test_slack_health_endpoint_reports_ready_when_probe_succeeds(client, seeded_tenants, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")
    get_settings.cache_clear()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/auth.test")
        return httpx.Response(200, json={"ok": True, "team": "AgentGate Demo"})

    _install_slack_transport(monkeypatch, handler)

    response = client.get(
        "/v1/integrations/slack/health?probe=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["configured"] is True
    assert payload["probe_performed"] is True
    assert payload["can_connect"] is True
