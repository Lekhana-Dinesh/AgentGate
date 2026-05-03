from __future__ import annotations

import json

import httpx
import pytest

from app.core.errors import AppError
from app.tools.base import ToolExecutionRequest
from app.tools.github_adapter import GitHubToolAdapter
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
                "auth_mode": "env_pat",
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
