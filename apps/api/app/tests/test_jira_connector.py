from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import AppError
from app.tools.base import ToolExecutionRequest
from app.tools.jira_adapter import JiraToolAdapter
from app.tests.conftest import make_token


def _adapter_with_transport(handler):
    transport = httpx.MockTransport(handler)
    return JiraToolAdapter(
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs)
    )


def _install_jira_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_client(self, *, base_url: str, auth_headers: dict[str, str], timeout: httpx.Timeout):
        return httpx.Client(
            base_url=base_url,
            headers={
                "Accept": "application/json",
                "User-Agent": "AgentGate/0.1.0",
                **auth_headers,
            },
            timeout=timeout,
            transport=transport,
        )

    monkeypatch.setattr(JiraToolAdapter, "_build_client", _build_client)


def _jira_config(**overrides):
    config = {
        "auth_mode": "env_token",
        "token_env_var": "AGENTGATE_JIRA_TOKEN",
        "project_allowlist": ["OPS", "SUPPORT"],
        "issue_type_allowlist": ["task", "bug", "incident"],
        "external_project_keys": ["SUPPORT"],
        "transition_allowlist": ["done", "31"],
        "assignee_allowlist": ["acct-support-1", "acct-oncall-1"],
        "max_read_retries": 1,
        "retry_backoff_seconds": 0.0,
        "timeout_seconds": 5,
    }
    config.update(overrides)
    return config


def _jira_tool_id(client, token: str) -> str:
    tools_response = client.get(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tools_response.status_code == 200
    return next(item["id"] for item in tools_response.json() if item["type"] == "jira")


def test_tool_safe_metadata_create_for_jira_is_sanitized_and_tenant_scoped(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    tenant_b_token = make_token(seeded_tenants["admin_b"])

    response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Jira Browser Managed",
            "type": "jira",
            "description": "Safe browser-managed Jira connector metadata",
            "base_url": "https://jira.example.test",
            "auth_mode": "basic_env",
            "project_allowlist": ["OPS", "SUPPORT"],
            "issue_type_allowlist": ["Task", "Incident"],
            "external_project_keys": ["SUPPORT"],
            "transition_allowlist": ["31", "Done"],
            "assignee_allowlist": ["acct-support-1"],
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["type"] == "jira"
    assert payload["auth_mode"] == "basic_env"
    assert payload["base_url"] == "https://jira.example.test"
    assert payload["project_allowlist"] == ["OPS", "SUPPORT"]
    assert payload["transition_allowlist"] == ["31", "done"]
    assert "config" not in payload
    assert "token_env_var" not in response.text
    assert "api_token_env_var" not in response.text
    assert "email_env_var" not in response.text
    assert "AGENTGATE_JIRA_API_TOKEN" not in response.text
    assert "AGENTGATE_JIRA_EMAIL" not in response.text

    cross_tenant_update = client.patch(
        f"/v1/tools/{payload['id']}/safe-metadata",
        headers={"Authorization": f"Bearer {tenant_b_token}"},
        json={"enabled": False},
    )
    assert cross_tenant_update.status_code == 404


def test_tool_safe_metadata_route_rejects_unsafe_jira_base_url_without_echoing_credentials(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Jira Bad URL",
            "type": "jira",
            "description": "Should reject embedded credentials",
            "base_url": "https://user:super-secret@jira.example.test/rest/api/3?token=abc",
            "auth_mode": "env_token",
            "project_allowlist": ["OPS"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_safe_base_url_invalid"
    assert "super-secret" not in response.text
    assert "token=abc" not in response.text


def test_jira_adapter_searches_issues_with_mocked_http(monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer jira-test-token"
        assert request.url.path == "/rest/api/3/search"
        assert "project+in+%28OPS%2CSUPPORT%29" in str(request.url)
        return httpx.Response(
            200,
            json={
                "startAt": 0,
                "maxResults": 20,
                "total": 1,
                "issues": [
                    {
                        "id": "10001",
                        "key": "OPS-101",
                        "fields": {
                            "summary": "Investigate production alert",
                            "description": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Review alert details"}]}]},
                            "project": {"key": "OPS"},
                            "issuetype": {"name": "Incident"},
                            "status": {"name": "Open"},
                            "assignee": {
                                "accountId": "acct-support-1",
                                "displayName": "On-call Engineer",
                                "emailAddress": "should-not-leak@example.com",
                            },
                        },
                    }
                ],
            },
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="Jira",
            action_name="search_issues",
            arguments={"text": "production alert"},
            tool_type="jira",
            base_url="https://jira.example.test",
            config=_jira_config(),
        )
    )

    assert result["count"] == 1
    assert result["issues"][0]["issue_key"] == "OPS-101"
    assert result["issues"][0]["assignee"]["display_name"] == "On-call Engineer"
    assert "emailAddress" not in json.dumps(result)


def test_jira_create_issue_uses_adapter_with_mocked_http(monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/rest/api/3/issue"
        body = json.loads(request.content.decode("utf-8"))
        assert body["fields"]["project"]["key"] == "OPS"
        assert body["fields"]["issuetype"]["name"] == "Task"
        assert body["fields"]["summary"] == "Investigate incident workflow"
        return httpx.Response(
            201,
            json={"id": "10045", "key": "OPS-145"},
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="Jira",
            action_name="create_issue",
            arguments={
                "project_key": "OPS",
                "issue_type": "Task",
                "summary": "Investigate incident workflow",
                "description": "Create a tracking issue for the follow-up.",
            },
            tool_type="jira",
            base_url="https://jira.example.test",
            config=_jira_config(),
        )
    )

    assert result["issue_key"] == "OPS-145"
    assert result["browse_url"].endswith("/browse/OPS-145")


def test_jira_comment_error_does_not_leak_secrets_or_email(monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"message": "Comment from support@example.com with Bearer jira-ultra-secret was rejected"},
        )

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="Jira",
                action_name="add_comment",
                arguments={"issue_key": "OPS-101", "body": "Escalating this to support."},
                tool_type="jira",
                base_url="https://jira.example.test",
                config=_jira_config(),
            )
        )

    assert exc_info.value.code == "jira_validation_failed"
    assert "support@example.com" not in exc_info.value.detail
    assert "jira-ultra-secret" not in exc_info.value.detail


def test_jira_write_actions_are_not_retried(monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(503, json={"message": "temporary upstream error"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="Jira",
                action_name="create_issue",
                arguments={
                    "project_key": "OPS",
                    "issue_type": "Task",
                    "summary": "Do not retry writes",
                },
                tool_type="jira",
                base_url="https://jira.example.test",
                config=_jira_config(max_read_retries=3),
            )
        )

    assert outbound_calls["count"] == 1
    assert exc_info.value.code == "jira_upstream_unavailable"


def test_jira_read_actions_retry_safely(monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        if outbound_calls["count"] == 1:
            return httpx.Response(503, json={"message": "temporary upstream error"})
        return httpx.Response(
            200,
            json={
                "id": "10001",
                "key": "OPS-101",
                "fields": {
                    "summary": "Investigate production alert",
                    "description": None,
                    "project": {"key": "OPS"},
                    "issuetype": {"name": "Incident"},
                    "status": {"name": "Open"},
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="Jira",
            action_name="get_issue",
            arguments={"issue_key": "OPS-101"},
            tool_type="jira",
            base_url="https://jira.example.test",
            config=_jira_config(max_read_retries=1),
        )
    )

    assert outbound_calls["count"] == 2
    assert result["issue_key"] == "OPS-101"


def test_jira_destructive_or_unknown_actions_are_blocked(monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")
    adapter = _adapter_with_transport(lambda _: httpx.Response(200, json={}))

    with pytest.raises(AppError) as destructive_exc:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="Jira",
                action_name="delete_issue",
                arguments={"issue_key": "OPS-101"},
                tool_type="jira",
                base_url="https://jira.example.test",
                config=_jira_config(),
            )
        )
    with pytest.raises(AppError) as unknown_exc:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="Jira",
                action_name="bulk_edit",
                arguments={"issue_key": "OPS-101"},
                tool_type="jira",
                base_url="https://jira.example.test",
                config=_jira_config(),
            )
        )

    assert destructive_exc.value.code == "jira_destructive_action_blocked"
    assert unknown_exc.value.code == "jira_action_not_allowed"


def test_tool_route_rejects_raw_jira_credentials_without_echoing_secret(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Jira Unsafe",
            "type": "jira",
            "description": "Unsafe Jira config",
            "base_url": "https://jira.example.test",
            "config": {
                "auth_mode": "env_token",
                "token": "jira-unsafe-secret",
                "project_allowlist": ["OPS"],
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "jira_raw_credentials_forbidden"
    assert "jira-unsafe-secret" not in response.text


def test_tool_route_accepts_jira_basic_env_configuration(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Jira Support",
            "type": "jira",
            "description": "Safe Jira config",
            "base_url": "https://jira.example.test",
            "config": {
                "auth_mode": "basic_env",
                "api_token_env_var": "AGENTGATE_JIRA_API_TOKEN",
                "email_env_var": "AGENTGATE_JIRA_EMAIL",
                "project_allowlist": ["OPS", "SUPPORT"],
                "issue_type_allowlist": ["Task", "Incident"],
                "external_project_keys": ["SUPPORT"],
                "transition_allowlist": ["Done", "31"],
                "assignee_allowlist": ["acct-support-1"],
                "max_read_retries": 1,
                "retry_backoff_seconds": 0,
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["config"]["auth_mode"] == "basic_env"
    assert payload["config"]["api_token_env_var"] == "AGENTGATE_JIRA_API_TOKEN"
    assert payload["config"]["email_env_var"] == "AGENTGATE_JIRA_EMAIL"
    assert payload["config"]["project_allowlist"] == ["OPS", "SUPPORT"]
    assert payload["config"]["transition_allowlist"] == ["31", "done"]


def test_tool_route_rejects_missing_jira_allowlist_safely(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Jira Missing Scope",
            "type": "jira",
            "description": "Invalid Jira config",
            "base_url": "https://jira.example.test",
            "config": {"auth_mode": "env_token", "token_env_var": "AGENTGATE_JIRA_TOKEN"},
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "jira_project_allowlist_required"


def test_jira_get_issue_executes_through_gateway(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")
    token = make_token(seeded_tenants["admin_a"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/issue/OPS-101"
        return httpx.Response(
            200,
            json={
                "id": "10001",
                "key": "OPS-101",
                "fields": {
                    "summary": "Investigate production alert",
                    "description": None,
                    "project": {"key": "OPS"},
                    "issuetype": {"name": "Incident"},
                    "status": {"name": "Open"},
                },
            },
        )

    _install_jira_transport(monkeypatch, handler)

    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Review the Jira issue before planning next steps.",
            "tool_name": "Jira",
            "action_name": "get_issue",
            "arguments": {"issue_key": "OPS-101"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["executed"] is True
    assert payload["output"]["issue_key"] == "OPS-101"


def test_jira_risky_transition_requires_approval_through_gateway(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Review the Jira issue and decide what to do next.",
            "tool_name": "Jira",
            "action_name": "transition_issue",
            "arguments": {"issue_key": "OPS-101", "transition_name": "Done"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "require_approval"
    assert response.json()["status"] == "pending_approval"


def test_jira_customer_visible_comment_requires_approval_through_gateway(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Add a customer-facing support update if it is approved.",
            "tool_name": "Jira",
            "action_name": "add_comment",
            "arguments": {"issue_key": "SUPPORT-24", "body": "Customer-visible update on ticket progress."},
            "data_classifications": ["customer_visible"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "require_approval"
    assert response.json()["status"] == "pending_approval"


def test_jira_confidential_comment_is_blocked_through_gateway(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Comment on the Jira issue with the review details.",
            "tool_name": "Jira",
            "action_name": "add_comment",
            "arguments": {"issue_key": "OPS-101", "body": "Confidential incident details."},
            "data_classifications": ["confidential"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "block"
    assert response.json()["status"] == "blocked"


def test_jira_comment_body_is_redacted_in_api_payloads(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Add a customer-facing support update if it is approved.",
            "tool_name": "Jira",
            "action_name": "add_comment",
            "arguments": {"issue_key": "SUPPORT-24", "body": "Bearer jira_super_secret_token"},
            "data_classifications": ["customer_visible"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    jira_approval = next(item for item in approvals_response.json() if item["tool_call"]["tool_name"] == "Jira")
    tool_call_payload = jira_approval["tool_call"]["request_payload"]

    assert "execution_arguments" not in tool_call_payload
    assert tool_call_payload["arguments"]["body"] == "[REDACTED]"
    assert "jira_super_secret_token" not in json.dumps(tool_call_payload)


def test_jira_connector_health_is_safe(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_API_TOKEN", "jira-api-token")
    monkeypatch.setenv("AGENTGATE_JIRA_EMAIL", "support@example.com")
    token = make_token(seeded_tenants["admin_a"])

    tools_response = client.get(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
    )
    jira_tool_id = next(item["id"] for item in tools_response.json() if item["type"] == "jira")

    update_response = client.put(
        f"/v1/tools/{jira_tool_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"config": _jira_config(auth_mode="basic_env", api_token_env_var="AGENTGATE_JIRA_API_TOKEN", email_env_var="AGENTGATE_JIRA_EMAIL")},
    )
    assert update_response.status_code == 200

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/project/search"
        assert request.headers["Authorization"].startswith("Basic ")
        return httpx.Response(200, json={"total": 2, "values": []})

    _install_jira_transport(monkeypatch, handler)

    response = client.get(
        f"/v1/tools/{jira_tool_id}/health?probe=true",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["auth_provider"] == "basic_env"
    assert payload["probe_performed"] is True
    assert payload["can_connect"] is True
    assert payload["details"]["project_allowlist_count"] == 2
    assert "jira-api-token" not in response.text
    assert "support@example.com" not in response.text


def test_tool_probe_health_is_restricted_and_sanitized(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JIRA_TOKEN", "jira-test-token")
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    tenant_b_token = make_token(seeded_tenants["admin_b"])
    jira_tool_id = _jira_tool_id(client, admin_token)

    reviewer_response = client.post(
        f"/v1/tools/{jira_tool_id}/probe-health",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    tenant_b_response = client.post(
        f"/v1/tools/{jira_tool_id}/probe-health",
        headers={"Authorization": f"Bearer {tenant_b_token}"},
    )

    assert reviewer_response.status_code == 403
    assert tenant_b_response.status_code == 404

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/api/3/project/search"
        assert request.headers["Authorization"] == "Bearer jira-test-token"
        return httpx.Response(200, json={"total": 2, "values": []})

    _install_jira_transport(monkeypatch, handler)

    response = client.post(
        f"/v1/tools/{jira_tool_id}/probe-health",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == jira_tool_id
    assert payload["type"] == "jira"
    assert payload["base_url_host"] == "jira.example.test"
    assert payload["auth_mode"] == "env_token"
    assert payload["health_status"] == "ready"
    assert payload["health_probe_performed"] is True
    assert payload["health_can_connect"] is True
    assert payload["allowlist_counts"]["project_allowlist"] == 2
    assert "config" not in payload
    assert "base_url" not in payload
    assert "AGENTGATE_JIRA_TOKEN" not in response.text
    assert "token_env_var" not in response.text
    assert "email_env_var" not in response.text
    assert "api_token_env_var" not in response.text
    assert "https://jira.example.test" not in response.text
