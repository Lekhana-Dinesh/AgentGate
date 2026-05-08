from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import AppError
from app.tests.conftest import make_token
from app.tools.base import ToolExecutionRequest
from app.tools.mcp_adapter import MCPToolAdapter


def _adapter_with_transport(handler):
    transport = httpx.MockTransport(handler)
    return MCPToolAdapter(
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs)
    )


def _install_mcp_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_client(self, *, base_url: str, auth_headers: dict[str, str], timeout: httpx.Timeout):
        return httpx.Client(
            base_url=base_url,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "AgentGate/0.1.0",
                **auth_headers,
            },
            timeout=timeout,
            transport=transport,
        )

    monkeypatch.setattr(MCPToolAdapter, "_build_client", _build_client)


def _mcp_config(**overrides):
    config = {
        "transport": "http",
        "auth_mode": "bearer_env",
        "token_env_var": "AGENTGATE_MCP_TOKEN",
        "allowed_tool_names": ["knowledge_search", "ticket_comment", "shell_execute"],
        "blocked_tool_names": ["delete_records"],
        "max_request_bytes": 16384,
        "max_response_bytes": 65536,
        "timeout_ms": 5000,
        "trust_domain": "internal",
        "max_read_retries": 1,
        "retry_backoff_seconds": 0.0,
    }
    config.update(overrides)
    for key in [key for key, value in config.items() if value is None]:
        config.pop(key, None)
    return config


def _mcp_tool_id(client, token: str) -> str:
    tools_response = client.get(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tools_response.status_code == 200
    return next(item["id"] for item in tools_response.json() if item["type"] == "mcp")


def test_tool_safe_metadata_create_and_update_for_mcp_stays_sanitized(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])

    create_response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Internal MCP Browser Managed",
            "type": "mcp",
            "description": "Safe browser-managed MCP metadata",
            "base_url": "https://mcp.internal.example",
            "transport": "http",
            "auth_mode": "api_key_env",
            "trust_domain": "internal",
            "allowed_tool_names": ["knowledge_search", "ticket_comment"],
            "blocked_tool_names": ["delete_records"],
            "risk_level": "high",
            "enabled": False,
        },
    )
    viewer_update = client.patch(
        f"/v1/tools/{_mcp_tool_id(client, admin_token)}/safe-metadata",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"enabled": False},
    )

    assert viewer_update.status_code == 403
    assert create_response.status_code == 201
    payload = create_response.json()
    assert payload["type"] == "mcp"
    assert payload["auth_mode"] == "api_key_env"
    assert payload["trust_domain"] == "internal"
    assert payload["allowed_tool_names"] == ["knowledge_search", "ticket_comment"]
    assert payload["blocked_tool_names"] == ["delete_records"]
    assert payload["base_url"] == "https://mcp.internal.example"
    assert "config" not in payload
    assert "api_key_env_var" not in create_response.text
    assert "token_env_var" not in create_response.text
    assert "AGENTGATE_MCP_API_KEY" not in create_response.text

    update_response = client.patch(
        f"/v1/tools/{payload['id']}/safe-metadata",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "enabled": True,
            "trust_domain": "external",
            "allowed_tool_names": ["knowledge_search", "ticket_comment", "status_lookup"],
        },
    )

    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["enabled"] is True
    assert updated_payload["trust_domain"] == "external"
    assert updated_payload["allowed_tool_names"] == ["knowledge_search", "ticket_comment", "status_lookup"]
    assert "api_key_env_var" not in update_response.text


def test_tool_safe_metadata_route_rejects_mcp_secret_like_fields_without_echoing_values(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "MCP Secret Leak Attempt",
            "type": "mcp",
            "description": "Should fail closed",
            "base_url": "https://mcp.example.test",
            "auth_mode": "bearer_env",
            "allowed_tool_names": ["knowledge_search"],
            "headers": {"Authorization": "Bearer mcp_browser_secret"},
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_safe_metadata_secret_fields_forbidden"
    assert "mcp_browser_secret" not in response.text


def test_mcp_allowed_tool_call_succeeds_with_mocked_server(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer mcp-test-token"
        body = json.loads(request.content.decode("utf-8"))
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "knowledge_search"
        assert body["params"]["arguments"] == {"query": "rollback runbook"}
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": "Rollback steps documented in KB-14."}],
                    "structuredContent": {"document_id": "KB-14"},
                    "isError": False,
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="MCP",
            action_name="call_tool",
            arguments={"tool_name": "knowledge_search", "arguments": {"query": "rollback runbook"}},
            tool_type="mcp",
            base_url="https://mcp.example.test",
            config=_mcp_config(),
        )
    )

    assert result["tool_name"] == "knowledge_search"
    assert result["structured_content"]["document_id"] == "KB-14"
    assert result["is_error"] is False


def test_mcp_disallowed_tool_is_blocked_before_outbound_call(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(200, json={})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="MCP",
                action_name="call_tool",
                arguments={"tool_name": "transfer_funds", "arguments": {"amount": 100}},
                tool_type="mcp",
                base_url="https://mcp.example.test",
                config=_mcp_config(),
            )
        )

    assert exc_info.value.code == "mcp_tool_not_allowed"
    assert outbound_calls["count"] == 0


def test_tool_route_rejects_raw_mcp_credentials_without_echoing_secret(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "MCP Unsafe",
            "type": "mcp",
            "description": "Unsafe MCP config",
            "base_url": "https://mcp.example.test",
            "config": {
                "auth_mode": "bearer_env",
                "token": "mcp-unsafe-secret",
                "allowed_tool_names": ["knowledge_search"],
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "mcp_raw_credentials_forbidden"
    assert "mcp-unsafe-secret" not in response.text


def test_tool_route_rejects_missing_mcp_allowlist_safely(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "MCP Missing Scope",
            "type": "mcp",
            "description": "Invalid MCP config",
            "base_url": "https://mcp.example.test",
            "config": {"transport": "http", "auth_mode": "none"},
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "mcp_allowed_tool_names_required"


def test_mcp_auth_error_does_not_leak_api_key(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_API_KEY", "mcp-ultra-secret-key")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "Forbidden for header X-API-Key: mcp-ultra-secret-key"},
        )

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="MCP",
                action_name="call_tool",
                arguments={"tool_name": "knowledge_search", "arguments": {"query": "ops"}},
                tool_type="mcp",
                base_url="https://mcp.example.test",
                config=_mcp_config(auth_mode="api_key_env", api_key_env_var="AGENTGATE_MCP_API_KEY"),
            )
        )

    assert exc_info.value.code == "mcp_forbidden"
    assert "mcp-ultra-secret-key" not in exc_info.value.detail


def test_mcp_response_size_limit_is_enforced(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "agentgate-tools-call",
                "result": {
                    "content": [{"type": "text", "text": "x" * 512}],
                    "structuredContent": {"rows": ["x" * 128]},
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="MCP",
                action_name="call_tool",
                arguments={"tool_name": "knowledge_search", "arguments": {"query": "ops"}},
                tool_type="mcp",
                base_url="https://mcp.example.test",
                config=_mcp_config(max_response_bytes=128),
            )
        )

    assert exc_info.value.code == "mcp_response_too_large"


def test_mcp_timeout_and_upstream_error_map_safely(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(408, json={"message": "request timeout"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="MCP",
                action_name="call_tool",
                arguments={"tool_name": "knowledge_search", "arguments": {"query": "ops"}},
                tool_type="mcp",
                base_url="https://mcp.example.test",
                config=_mcp_config(),
            )
        )

    assert exc_info.value.code == "mcp_upstream_timeout"


def test_mcp_list_tools_retries_safely(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")
    outbound_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        if outbound_calls["count"] == 1:
            return httpx.Response(503, json={"message": "temporary upstream error"})
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "tools": [
                        {"name": "knowledge_search", "description": "Search runbooks."},
                        {"name": "delete_records", "description": "Should stay hidden."},
                    ]
                },
            },
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="MCP",
            action_name="list_tools",
            arguments={},
            tool_type="mcp",
            base_url="https://mcp.example.test",
            config=_mcp_config(max_read_retries=1),
        )
    )

    assert outbound_calls["count"] == 2
    assert result["count"] == 1
    assert result["tools"][0]["name"] == "knowledge_search"


def test_mcp_call_tool_is_not_retried(monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(503, json={"message": "temporary upstream error"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="MCP",
                action_name="call_tool",
                arguments={"tool_name": "knowledge_search", "arguments": {"query": "ops"}},
                tool_type="mcp",
                base_url="https://mcp.example.test",
                config=_mcp_config(max_read_retries=3),
            )
        )

    assert outbound_calls["count"] == 1
    assert exc_info.value.code == "mcp_upstream_unavailable"


def test_mcp_gateway_call_executes_for_allowlisted_safe_tool(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_TOKEN", "mcp-test-token")
    token = make_token(seeded_tenants["admin_a"])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["method"] == "tools/call"
        assert body["params"]["name"] == "knowledge_search"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "content": [{"type": "text", "text": "Rollback plan lives in KB-42."}],
                    "structuredContent": {"document_id": "KB-42"},
                },
            },
        )

    _install_mcp_transport(monkeypatch, handler)

    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Search the internal runbook for rollback steps.",
            "tool_name": "MCP",
            "action_name": "call_tool",
            "arguments": {
                "tool_name": "knowledge_search",
                "arguments": {"query": "rollback steps"},
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["status"] == "executed"
    assert payload["executed"] is True
    assert payload["output"]["tool_name"] == "knowledge_search"


def test_external_mcp_tool_requires_approval_through_gateway(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    mcp_tool_id = _mcp_tool_id(client, token)

    update_response = client.put(
        f"/v1/tools/{mcp_tool_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"config": _mcp_config(trust_domain="external")},
    )
    assert update_response.status_code == 200

    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Search the vendor incident knowledge base for the linked case.",
            "tool_name": "MCP",
            "action_name": "call_tool",
            "arguments": {
                "tool_name": "knowledge_search",
                "arguments": {"query": "vendor outage case"},
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "require_approval"
    assert response.json()["status"] == "pending_approval"


def test_dangerous_mcp_tool_name_is_blocked_through_gateway(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Check whether the remote admin tool is available.",
            "tool_name": "MCP",
            "action_name": "call_tool",
            "arguments": {
                "tool_name": "shell_execute",
                "arguments": {"command": "whoami"},
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"] == "block"
    assert response.json()["status"] == "blocked"


def test_mcp_nested_tool_arguments_are_redacted_in_api_payloads(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    gateway_response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Post a support comment after review.",
            "tool_name": "MCP",
            "action_name": "call_tool",
            "arguments": {
                "tool_name": "ticket_comment",
                "arguments": {"body": "Bearer mcp_super_secret_token"},
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200
    assert gateway_response.json()["decision"] == "require_approval"

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    mcp_approval = next(item for item in approvals_response.json() if item["tool_call"]["tool_name"] == "MCP")
    tool_call_payload = mcp_approval["tool_call"]["request_payload"]

    assert "execution_arguments" not in tool_call_payload
    assert tool_call_payload["arguments"]["arguments"]["body"] == "[REDACTED]"
    assert "mcp_super_secret_token" not in json.dumps(tool_call_payload)


def test_mcp_connector_health_is_safe(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_MCP_API_KEY", "mcp-api-key")
    token = make_token(seeded_tenants["admin_a"])
    mcp_tool_id = _mcp_tool_id(client, token)

    update_response = client.put(
        f"/v1/tools/{mcp_tool_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"config": _mcp_config(auth_mode="api_key_env", token_env_var=None, api_key_env_var="AGENTGATE_MCP_API_KEY")},
    )
    assert update_response.status_code == 200

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "mcp-api-key"
        body = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "tools": [
                        {"name": "knowledge_search", "description": "Search runbooks."},
                        {"name": "delete_records", "description": "Should stay hidden."},
                    ]
                },
            },
        )

    _install_mcp_transport(monkeypatch, handler)

    response = client.get(
        f"/v1/tools/{mcp_tool_id}/health?probe=true",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["auth_provider"] == "api_key_env"
    assert payload["probe_performed"] is True
    assert payload["can_connect"] is True
    assert payload["details"]["allowed_tool_count"] == 3
    assert payload["details"]["visible_tool_count"] == 1
    assert "mcp-api-key" not in response.text
