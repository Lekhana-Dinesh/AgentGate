from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.core.errors import AppError
from app.tools.base import ToolExecutionRequest
from app.tools.github_adapter import GitHubToolAdapter
from app.tools.github_auth import ConfiguredGitHubAuthProvider, GitHubAppAuthProvider
from app.tests.conftest import make_token


def _adapter_with_transport(handler):
    transport = httpx.MockTransport(handler)
    return GitHubToolAdapter(
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs)
    )


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


def _install_github_app_auth_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_http_client(self, *, base_url: str, headers: dict[str, str], timeout: float):
        return httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    monkeypatch.setattr(GitHubAppAuthProvider, "_build_http_client", _build_http_client)


def _github_config(**overrides):
    config = {
        "auth_mode": "env_pat",
        "token_env_var": "AGENTGATE_GITHUB_TOKEN",
        "repository_allowlist": ["agentgate-labs/internal-agentgate", "octocat/hello-world"],
        "internal_repositories": ["agentgate-labs/internal-agentgate"],
        "internal_owners": ["agentgate-labs"],
        "public_repositories": ["octocat/hello-world"],
        "max_read_retries": 1,
        "retry_backoff_seconds": 0.0,
        "timeout_seconds": 5,
    }
    config.update(overrides)
    return config


def _github_app_config(**overrides):
    config = {
        "auth_mode": "github_app",
        "app_id": "12345",
        "installation_id": "67890",
        "private_key_env_var": "AGENTGATE_GITHUB_APP_PRIVATE_KEY",
        "repository_allowlist": ["agentgate-labs/internal-agentgate", "octocat/hello-world"],
        "internal_repositories": ["agentgate-labs/internal-agentgate"],
        "internal_owners": ["agentgate-labs"],
        "public_repositories": ["octocat/hello-world"],
        "max_read_retries": 1,
        "retry_backoff_seconds": 0.0,
        "timeout_seconds": 5,
        "token_cache_ttl_seconds": 300,
    }
    config.update(overrides)
    return config


def _generate_github_app_private_key() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_key_pem, public_key_pem


def _github_tool_id(client, token: str) -> str:
    tools_response = client.get(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tools_response.status_code == 200
    return next(item["id"] for item in tools_response.json() if item["type"] == "github")


def test_tool_summary_endpoint_is_safe_rbac_and_tenant_scoped(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    tenant_b_token = make_token(seeded_tenants["admin_b"])

    admin_response = client.get("/v1/tools/summary", headers={"Authorization": f"Bearer {admin_token}"})
    reviewer_response = client.get("/v1/tools/summary", headers={"Authorization": f"Bearer {reviewer_token}"})
    developer_response = client.get("/v1/tools/summary", headers={"Authorization": f"Bearer {developer_token}"})
    viewer_response = client.get("/v1/tools/summary", headers={"Authorization": f"Bearer {viewer_token}"})
    tenant_b_response = client.get("/v1/tools/summary", headers={"Authorization": f"Bearer {tenant_b_token}"})

    assert admin_response.status_code == 200
    assert reviewer_response.status_code == 200
    assert developer_response.status_code == 403
    assert viewer_response.status_code == 403
    assert tenant_b_response.status_code == 200

    payload = admin_response.json()
    assert all("config" not in item and "base_url" not in item for item in payload)

    github_tool = next(item for item in payload if item["type"] == "github")
    jira_tool = next(item for item in payload if item["type"] == "jira")
    mcp_tool = next(item for item in payload if item["type"] == "mcp")

    assert github_tool["base_url_host"] == "api.github.com"
    assert github_tool["auth_mode"] == "env_pat"
    assert github_tool["allowlist_counts"]["repository_allowlist"] == 2
    assert "create_issue" in github_tool["supported_actions"]
    assert "comment_on_issue_or_pr" in github_tool["supported_actions"]

    assert jira_tool["base_url_host"] == "jira.example.test"
    assert jira_tool["auth_mode"] == "env_token"
    assert jira_tool["allowlist_counts"]["project_allowlist"] == 2

    assert mcp_tool["base_url_host"] == "mcp.example.test"
    assert mcp_tool["auth_mode"] == "bearer_env"
    assert mcp_tool["trust_domain"] == "internal"
    assert mcp_tool["allowlist_counts"]["allowed_tool_names"] == 3
    assert "call_tool" in mcp_tool["supported_actions"]

    tenant_b_payload = tenant_b_response.json()
    assert len(tenant_b_payload) == 1
    assert tenant_b_payload[0]["name"] == "Salesforce"
    assert "GitHub" not in tenant_b_response.text
    assert seeded_tenants["tenant_a"].id not in tenant_b_response.text

    assert "AGENTGATE_GITHUB_TOKEN" not in admin_response.text
    assert "AGENTGATE_JIRA_TOKEN" not in admin_response.text
    assert "AGENTGATE_MCP_TOKEN" not in admin_response.text
    assert "token_env_var" not in admin_response.text
    assert "api_token_env_var" not in admin_response.text
    assert "api_key_env_var" not in admin_response.text
    assert "https://api.github.com" not in admin_response.text
    assert "https://jira.example.test" not in admin_response.text
    assert "https://mcp.example.test" not in admin_response.text


def test_tool_safe_detail_is_tenant_scoped(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    tenant_b_token = make_token(seeded_tenants["admin_b"])
    github_tool_id = _github_tool_id(client, admin_token)

    reviewer_response = client.get(
        f"/v1/tools/{github_tool_id}/safe-detail",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    tenant_b_response = client.get(
        f"/v1/tools/{github_tool_id}/safe-detail",
        headers={"Authorization": f"Bearer {tenant_b_token}"},
    )

    assert reviewer_response.status_code == 200
    assert tenant_b_response.status_code == 404
    payload = reviewer_response.json()
    assert payload["id"] == github_tool_id
    assert payload["type"] == "github"
    assert "config" not in payload
    assert payload["base_url"] == "https://api.github.com"
    assert "token_env_var" not in reviewer_response.text
    assert "private_key_env_var" not in reviewer_response.text


def test_tool_safe_metadata_create_and_update_for_github_is_sanitized_and_rbac_scoped(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])

    create_payload = {
        "name": "GitHub Browser Managed",
        "type": "github",
        "description": "Safe browser-managed connector metadata",
        "base_url": "https://api.github.com",
        "auth_mode": "github_app",
        "app_id": "12345",
        "installation_id": "67890",
        "repository_allowlist": ["AgentGate-Labs/Internal-AgentGate", "octocat/hello-world"],
        "internal_owners": ["AgentGate-Labs"],
        "internal_repositories": ["AgentGate-Labs/Internal-AgentGate"],
        "public_repositories": ["octocat/hello-world"],
        "risk_level": "high",
        "enabled": True,
    }

    reviewer_response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json=create_payload,
    )
    developer_response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {developer_token}"},
        json=create_payload,
    )
    admin_response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=create_payload,
    )

    assert reviewer_response.status_code == 403
    assert developer_response.status_code == 403
    assert admin_response.status_code == 201

    payload = admin_response.json()
    assert payload["type"] == "github"
    assert payload["auth_mode"] == "github_app"
    assert payload["app_id"] == "12345"
    assert payload["installation_id"] == "67890"
    assert payload["base_url"] == "https://api.github.com"
    assert payload["repository_allowlist"] == ["agentgate-labs/internal-agentgate", "octocat/hello-world"]
    assert "config" not in payload
    assert "token_env_var" not in admin_response.text
    assert "private_key_env_var" not in admin_response.text
    assert "private_key_secret_ref" not in admin_response.text
    assert "AGENTGATE_GITHUB_APP_PRIVATE_KEY" not in admin_response.text

    tool_id = payload["id"]
    update_response = client.patch(
        f"/v1/tools/{tool_id}/safe-metadata",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "enabled": False,
            "public_repositories": ["octocat/hello-world", "openai/openai-cookbook"],
        },
    )
    reviewer_update = client.patch(
        f"/v1/tools/{tool_id}/safe-metadata",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"enabled": True},
    )

    assert reviewer_update.status_code == 403
    assert update_response.status_code == 200
    updated_payload = update_response.json()
    assert updated_payload["enabled"] is False
    assert updated_payload["public_repositories"] == ["octocat/hello-world", "openai/openai-cookbook"]
    assert "private_key_env_var" not in update_response.text
    assert "AGENTGATE_GITHUB_APP_PRIVATE_KEY" not in update_response.text


def test_tool_safe_metadata_route_rejects_secret_like_github_fields_without_echoing_values(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools/safe-metadata",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "GitHub Secret Leak Attempt",
            "type": "github",
            "description": "Should fail closed",
            "base_url": "https://api.github.com",
            "auth_mode": "env_token",
            "repository_allowlist": ["agentgate-labs/internal-agentgate"],
            "token": "ghp_browser_never_store_this",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "tool_safe_metadata_secret_fields_forbidden"
    assert "ghp_browser_never_store_this" not in response.text


def test_github_adapter_gets_repository_metadata(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.url.path == "/repos/agentgate-labs/internal-agentgate"
        return httpx.Response(
            200,
            json={
                "full_name": "agentgate-labs/internal-agentgate",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
                "open_issues_count": 3,
                "stargazers_count": 7,
                "html_url": "https://github.com/agentgate-labs/internal-agentgate",
                "archived": False,
            },
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="GitHub",
            action_name="get_repository_metadata",
            arguments={"repository": "agentgate-labs/internal-agentgate"},
            tool_type="github",
            base_url="https://api.github.com",
            config=_github_config(),
        )
    )

    assert result["full_name"] == "agentgate-labs/internal-agentgate"
    assert result["visibility"] == "private"


def test_github_allowlist_denial_happens_before_outbound_call(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(200, json={})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="get_repository_metadata",
                arguments={"repository": "unknown-org/private-repo"},
                tool_type="github",
                config=_github_config(repository_allowlist=["agentgate-labs/internal-agentgate"]),
            )
        )

    assert exc_info.value.code == "github_repository_forbidden"
    assert outbound_calls["count"] == 0


def test_github_auth_failure_is_sanitized(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "bad credentials for ghp_super_secret"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="get_repository_metadata",
                arguments={"repository": "agentgate-labs/internal-agentgate"},
                tool_type="github",
                config=_github_config(),
            )
        )

    assert exc_info.value.code == "github_auth_failed"
    assert "ghp_super_secret" not in exc_info.value.detail


def test_github_forbidden_maps_cleanly(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource access denied"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="get_repository_metadata",
                arguments={"repository": "agentgate-labs/internal-agentgate"},
                tool_type="github",
                config=_github_config(),
            )
        )

    assert exc_info.value.code == "github_forbidden"


def test_github_not_found_maps_cleanly(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="get_repository_metadata",
                arguments={"repository": "agentgate-labs/internal-agentgate"},
                tool_type="github",
                config=_github_config(),
            )
        )

    assert exc_info.value.code == "github_resource_not_found"


def test_github_rate_limit_maps_cleanly(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "API rate limit exceeded"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="get_repository_metadata",
                arguments={"repository": "agentgate-labs/internal-agentgate"},
                tool_type="github",
                config=_github_config(max_read_retries=0),
            )
        )

    assert exc_info.value.code == "github_rate_limited"


def test_github_read_action_retries_once_then_succeeds(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        if outbound_calls["count"] == 1:
            return httpx.Response(503, json={"message": "temporary upstream error"})
        return httpx.Response(
            200,
            json={
                "full_name": "agentgate-labs/internal-agentgate",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
                "open_issues_count": 1,
                "stargazers_count": 1,
                "html_url": "https://github.com/agentgate-labs/internal-agentgate",
                "archived": False,
            },
        )

    adapter = _adapter_with_transport(handler)
    result = adapter.execute(
        ToolExecutionRequest(
            tool_name="GitHub",
            action_name="get_repository_metadata",
            arguments={"repository": "agentgate-labs/internal-agentgate"},
            tool_type="github",
            config=_github_config(max_read_retries=1),
        )
    )

    assert outbound_calls["count"] == 2
    assert result["full_name"] == "agentgate-labs/internal-agentgate"


def test_github_write_action_is_not_retried(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    outbound_calls = {"count": 0}

    def handler(_: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        return httpx.Response(503, json={"message": "temporary upstream error"})

    adapter = _adapter_with_transport(handler)
    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="create_issue",
                arguments={
                    "repository": "agentgate-labs/internal-agentgate",
                    "title": "Retry guard test",
                    "body": "Should not retry writes.",
                },
                tool_type="github",
                config=_github_config(max_read_retries=3),
            )
        )

    assert outbound_calls["count"] == 1
    assert exc_info.value.code == "github_upstream_unavailable"


def test_github_destructive_action_is_blocked_at_adapter_level(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    adapter = _adapter_with_transport(lambda _: httpx.Response(200, json={}))

    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="delete_branch",
                arguments={"repository": "agentgate-labs/internal-agentgate"},
                tool_type="github",
                config=_github_config(),
            )
        )

    assert exc_info.value.code == "github_destructive_action_blocked"


def test_tool_route_rejects_raw_github_token_storage_without_echoing_secret(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "GitHub Public",
            "type": "github",
            "description": "Unsafe tool config",
            "base_url": "https://api.github.com",
            "config": {"token": "ghp_unsafe_secret"},
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "github_raw_token_forbidden"
    assert "ghp_unsafe_secret" not in response.text


def test_tool_route_accepts_github_env_var_configuration(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "GitHub Internal",
            "type": "github",
            "description": "Safe tool config",
            "base_url": "https://api.github.com",
            "config": {
                "auth_mode": "env_token",
                "token_env_var": "AGENTGATE_GITHUB_TOKEN",
                "internal_owners": ["AgentGate-Labs"],
                "internal_repositories": ["AgentGate-Labs/Internal-AgentGate"],
                "repository_allowlist": ["AgentGate-Labs/Internal-AgentGate"],
                "max_read_retries": 1,
                "retry_backoff_seconds": 0,
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["config"]["auth_mode"] == "env_token"
    assert payload["config"]["token_env_var"] == "AGENTGATE_GITHUB_TOKEN"
    assert payload["config"]["internal_owners"] == ["agentgate-labs"]
    assert payload["config"]["internal_repositories"] == ["agentgate-labs/internal-agentgate"]
    assert payload["config"]["repository_allowlist"] == ["agentgate-labs/internal-agentgate"]


def test_github_connector_health_endpoint_reports_unconfigured_without_token(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    tools_response = client.get(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
    )
    github_tool_id = next(item["id"] for item in tools_response.json() if item["type"] == "github")

    response = client.get(
        f"/v1/tools/{github_tool_id}/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unconfigured"
    assert payload["probe_performed"] is False


def test_github_repository_metadata_executes_through_gateway(client, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    token = make_token(seeded_tenants["admin_a"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/agentgate-labs/internal-agentgate"
        return httpx.Response(
            200,
            json={
                "full_name": "agentgate-labs/internal-agentgate",
                "private": True,
                "visibility": "private",
                "default_branch": "main",
                "open_issues_count": 2,
                "stargazers_count": 1,
                "html_url": "https://github.com/agentgate-labs/internal-agentgate",
                "archived": False,
            },
        )

    _install_github_transport(monkeypatch, handler)

    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Review repository metadata before planning a maintenance issue.",
            "tool_name": "GitHub",
            "action_name": "get_repository_metadata",
            "arguments": {"repository": "agentgate-labs/internal-agentgate"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["executed"] is True
    assert payload["status"] == "executed"
    assert payload["output"]["full_name"] == "agentgate-labs/internal-agentgate"


def test_public_github_comment_requires_approval_through_gateway(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
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
                "body": "Posting a public comment from the sales agent.",
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    assert response.json()["decision"] == "require_approval"


def test_github_issue_creation_requires_approval_for_production_agent(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Open a tracking issue for the security review.",
            "tool_name": "GitHub",
            "action_name": "create_issue",
            "arguments": {
                "repository": "agentgate-labs/internal-agentgate",
                "title": "Security review follow-up",
                "body": "Create an issue after risk review.",
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending_approval"
    assert response.json()["decision"] == "require_approval"


def test_github_secret_like_body_is_redacted_from_api_payloads(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    gateway_response = client.post(
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
                "body": "Bearer ghp_ultra_secret_token",
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

    approvals_response = client.get(
        "/v1/approvals?status=pending",
        headers={"Authorization": f"Bearer {token}"},
    )
    github_approval = next(item for item in approvals_response.json() if item["tool_call"]["tool_name"] == "GitHub")
    tool_call_payload = github_approval["tool_call"]["request_payload"]

    assert "execution_arguments" not in tool_call_payload
    assert tool_call_payload["arguments"]["body"] == "[REDACTED]"
    assert "ghp_ultra_secret_token" not in json.dumps(tool_call_payload)


def test_security_reviewer_can_approve_and_execute_pending_github_comment(
    client,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "test-token")
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octocat/hello-world/issues/14/comments"
        body = json.loads(request.content.decode("utf-8"))
        assert body["body"] == "Security review approved for posting."
        return httpx.Response(
            201,
            json={
                "id": 701,
                "html_url": "https://github.com/octocat/hello-world/issues/14#issuecomment-701",
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
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert gateway_response.status_code == 200

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
        json={"approver_comment": "Approved public GitHub comment for the test.", "execute_now": True},
    )

    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"


def test_github_app_jwt_generation_uses_configured_private_key():
    private_key, public_key = _generate_github_app_private_key()
    issued_at = 1_714_717_200
    provider = GitHubAppAuthProvider(time_source=lambda: issued_at)

    app_jwt = provider._build_app_jwt("12345", private_key)
    claims = jwt.decode(
        app_jwt,
        public_key,
        algorithms=["RS256"],
        options={"verify_aud": False, "verify_exp": False, "verify_iat": False},
    )

    assert claims["iss"] == "12345"
    assert claims["iat"] == issued_at - 60
    assert claims["exp"] == issued_at + 540


def test_github_app_installation_token_exchange_uses_mocked_http(monkeypatch):
    private_key, _ = _generate_github_app_private_key()
    monkeypatch.setenv("AGENTGATE_GITHUB_APP_PRIVATE_KEY", private_key)
    outbound_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        outbound_calls["count"] += 1
        assert request.method == "POST"
        assert request.url.path == "/app/installations/67890/access_tokens"
        assert request.headers["Authorization"].startswith("Bearer ")
        assert "PRIVATE KEY" not in request.headers["Authorization"]
        return httpx.Response(
            201,
            json={
                "token": "ghs_installation_test_token",
                "expires_at": "2026-05-04T12:30:00Z",
            },
        )

    transport = httpx.MockTransport(handler)
    provider = GitHubAppAuthProvider(
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs)
    )

    auth_context = provider.get_auth_context(
        _github_app_config(),
        base_url="https://api.github.com",
    )

    assert outbound_calls["count"] == 1
    assert auth_context.provider_name == "github_app"
    assert auth_context.auth_headers["Authorization"] == "Bearer ghs_installation_test_token"
    assert auth_context.token_expires_at == "2026-05-04T12:30:00Z"
    assert auth_context.cache_hit is False


def test_github_app_token_cache_refreshes_before_expiry(monkeypatch):
    private_key, _ = _generate_github_app_private_key()
    monkeypatch.setenv("AGENTGATE_GITHUB_APP_PRIVATE_KEY", private_key)
    clock = {"now": 1_714_717_200.0}
    outbound_tokens: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        token = f"ghs_cached_token_{len(outbound_tokens) + 1}"
        outbound_tokens.append(token)
        expires_at = datetime.fromtimestamp(clock["now"], tz=timezone.utc) + timedelta(seconds=120)
        return httpx.Response(
            201,
            json={"token": token, "expires_at": expires_at.isoformat().replace("+00:00", "Z")},
        )

    transport = httpx.MockTransport(handler)
    provider = GitHubAppAuthProvider(
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
        time_source=lambda: clock["now"],
    )

    first = provider.get_auth_context(_github_app_config(), base_url="https://api.github.com")
    clock["now"] += 40
    second = provider.get_auth_context(_github_app_config(), base_url="https://api.github.com")
    clock["now"] += 70
    third = provider.get_auth_context(_github_app_config(), base_url="https://api.github.com")

    assert outbound_tokens == ["ghs_cached_token_1", "ghs_cached_token_2"]
    assert first.auth_headers["Authorization"] == "Bearer ghs_cached_token_1"
    assert first.cache_hit is False
    assert second.auth_headers["Authorization"] == "Bearer ghs_cached_token_1"
    assert second.cache_hit is True
    assert third.auth_headers["Authorization"] == "Bearer ghs_cached_token_2"
    assert third.cache_hit is False


def test_tool_route_rejects_incomplete_github_app_configuration(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "GitHub App Missing Config",
            "type": "github",
            "description": "Invalid GitHub App config",
            "base_url": "https://api.github.com",
            "config": {
                "auth_mode": "github_app",
                "installation_id": "67890",
                "private_key_env_var": "AGENTGATE_GITHUB_APP_PRIVATE_KEY",
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "github_app_app_id_required"


def test_tool_route_rejects_raw_github_app_private_key_without_echoing_secret(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "GitHub App Unsafe",
            "type": "github",
            "description": "Unsafe GitHub App config",
            "base_url": "https://api.github.com",
            "config": {
                "auth_mode": "github_app",
                "app_id": "12345",
                "installation_id": "67890",
                "private_key": "raw-private-key-value-forbidden",
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "github_raw_token_forbidden"
    assert "raw-private-key-value-forbidden" not in response.text


def test_tool_route_accepts_github_app_secret_reference_configuration(client, seeded_tenants):
    token = make_token(seeded_tenants["admin_a"])
    response = client.post(
        "/v1/tools",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "GitHub App Internal",
            "type": "github",
            "description": "Safe GitHub App config",
            "base_url": "https://api.github.com",
            "config": {
                "auth_mode": "github_app",
                "app_id": "12345",
                "installation_id": "67890",
                "private_key_secret_ref": "env:AGENTGATE_GITHUB_APP_PRIVATE_KEY",
                "repository_allowlist": ["AgentGate-Labs/Internal-AgentGate"],
                "internal_owners": ["AgentGate-Labs"],
                "token_cache_ttl_seconds": 600,
            },
            "risk_level": "high",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["config"]["auth_mode"] == "github_app"
    assert payload["config"]["app_id"] == "12345"
    assert payload["config"]["installation_id"] == "67890"
    assert payload["config"]["private_key_secret_ref"] == "env:AGENTGATE_GITHUB_APP_PRIVATE_KEY"
    assert payload["config"]["repository_allowlist"] == ["agentgate-labs/internal-agentgate"]


def test_github_connector_health_endpoint_reports_safe_github_app_provider_status(
    client,
    seeded_tenants,
    monkeypatch,
):
    private_key, _ = _generate_github_app_private_key()
    monkeypatch.setenv("AGENTGATE_GITHUB_APP_PRIVATE_KEY", private_key)
    token = make_token(seeded_tenants["admin_a"])
    github_tool_id = _github_tool_id(client, token)

    update_response = client.put(
        f"/v1/tools/{github_tool_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"config": _github_app_config()},
    )
    assert update_response.status_code == 200

    response = client.get(
        f"/v1/tools/{github_tool_id}/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["auth_provider"] == "github_app"
    assert payload["details"]["app_id"] == "12345"
    assert payload["details"]["installation_id"] == "67890"
    assert payload["details"]["private_key_env_var"] == "AGENTGATE_GITHUB_APP_PRIVATE_KEY"
    assert "PRIVATE KEY" not in response.text
    assert "ghs_" not in response.text


def test_github_connector_health_hides_invalid_private_key_material(
    client,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_GITHUB_APP_PRIVATE_KEY", "invalid-private-key-material")
    token = make_token(seeded_tenants["admin_a"])
    github_tool_id = _github_tool_id(client, token)

    update_response = client.put(
        f"/v1/tools/{github_tool_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"config": _github_app_config()},
    )
    assert update_response.status_code == 200

    response = client.get(
        f"/v1/tools/{github_tool_id}/health",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    assert payload["details"]["error_code"] == "github_app_private_key_invalid"
    assert "invalid-private-key-material" not in response.text


def test_github_repository_metadata_executes_through_gateway_with_github_app_auth(
    client,
    seeded_tenants,
    monkeypatch,
):
    private_key, _ = _generate_github_app_private_key()
    monkeypatch.setenv("AGENTGATE_GITHUB_APP_PRIVATE_KEY", private_key)
    admin_token = make_token(seeded_tenants["admin_a"])
    github_tool_id = _github_tool_id(client, admin_token)
    exchange_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/app/installations/67890/access_tokens":
            exchange_calls["count"] += 1
            assert request.headers["Authorization"].startswith("Bearer ")
            return httpx.Response(
                201,
                json={
                    "token": "ghs_gateway_installation_token",
                    "expires_at": "2026-05-04T12:30:00Z",
                },
            )
        if request.url.path == "/repos/agentgate-labs/internal-agentgate":
            assert request.headers["Authorization"] == "Bearer ghs_gateway_installation_token"
            return httpx.Response(
                200,
                json={
                    "full_name": "agentgate-labs/internal-agentgate",
                    "private": True,
                    "visibility": "private",
                    "default_branch": "main",
                    "open_issues_count": 2,
                    "stargazers_count": 1,
                    "html_url": "https://github.com/agentgate-labs/internal-agentgate",
                    "archived": False,
                },
            )
        raise AssertionError(f"Unexpected GitHub path {request.url.path}")

    update_response = client.put(
        f"/v1/tools/{github_tool_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"config": _github_app_config()},
    )
    assert update_response.status_code == 200

    _install_github_transport(monkeypatch, handler)
    _install_github_app_auth_transport(monkeypatch, handler)

    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "agent_id": seeded_tenants["agent_a"].id,
            "user_id": seeded_tenants["admin_a"].id,
            "original_intent": "Review repository metadata before planning a maintenance issue.",
            "tool_name": "GitHub",
            "action_name": "get_repository_metadata",
            "arguments": {"repository": "agentgate-labs/internal-agentgate"},
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "allow"
    assert payload["executed"] is True
    assert payload["output"]["full_name"] == "agentgate-labs/internal-agentgate"
    assert exchange_calls["count"] == 1


def test_github_destructive_action_is_blocked_before_github_app_token_exchange(monkeypatch):
    outbound_calls = {"count": 0}

    def _unexpected_http_client(self, *, base_url: str, headers: dict[str, str], timeout: float):
        outbound_calls["count"] += 1
        return httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=httpx.MockTransport(lambda _: httpx.Response(500, json={})),
        )

    monkeypatch.setattr(GitHubAppAuthProvider, "_build_http_client", _unexpected_http_client)
    adapter = GitHubToolAdapter(
        auth_provider=ConfiguredGitHubAuthProvider(
            github_app_provider=GitHubAppAuthProvider(),
        )
    )

    with pytest.raises(AppError) as exc_info:
        adapter.execute(
            ToolExecutionRequest(
                tool_name="GitHub",
                action_name="delete_branch",
                arguments={"repository": "agentgate-labs/internal-agentgate"},
                tool_type="github",
                config=_github_app_config(),
            )
        )

    assert exc_info.value.code == "github_destructive_action_blocked"
    assert outbound_calls["count"] == 0
