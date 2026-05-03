# GitHub Connector

## Overview

AgentGate includes a production-quality foundation for a GitHub connector behind the standard tool adapter interface. Every GitHub action still goes through the normal gateway path for tenant checks, caller identity, intent analysis, risk scoring, policy evaluation, approvals, audit logging, and trace replay.

Supported actions in this build:

- `get_repository_metadata`
- `list_pull_requests`
- `get_pull_request_details`
- `create_issue`
- `comment_on_issue_or_pr`

Destructive actions are explicitly blocked at the adapter layer and should not rely on policy matching alone.

## Configuration

Set a GitHub token in the runtime environment:

```bash
export AGENTGATE_GITHUB_TOKEN=ghp_your_token_here
```

PowerShell:

```powershell
$env:AGENTGATE_GITHUB_TOKEN="ghp_your_token_here"
```

Create or update a GitHub tool with config like:

```json
{
  "name": "GitHub",
  "type": "github",
  "description": "GitHub repository metadata and issue workflow connector",
  "base_url": "https://api.github.com",
  "config": {
    "auth_mode": "env_pat",
    "token_env_var": "AGENTGATE_GITHUB_TOKEN",
    "repository_allowlist": [
      "agentgate-labs/internal-agentgate",
      "octocat/hello-world"
    ],
    "internal_repositories": ["agentgate-labs/internal-agentgate"],
    "internal_owners": ["agentgate-labs"],
    "public_repositories": ["octocat/hello-world"],
    "timeout_seconds": 15,
    "max_read_retries": 2,
    "retry_backoff_seconds": 0.2
  },
  "risk_level": "high",
  "enabled": true
}
```

Rules enforced by the API:

- `token_env_var` is required
- raw token-like config fields such as `token`, `access_token`, and `github_token` are rejected
- repository allowlists and trust lists are normalized and validated
- only `auth_mode: "env_pat"` is supported in this build

## Reliability Behavior

- The connector uses explicit connect/read/write/pool timeouts.
- Safe read operations may retry with bounded exponential backoff.
- Writes are not retried.
- Upstream response handling is structured:
  - `401` -> `github_auth_failed`
  - `403` -> `github_forbidden`
  - `404` -> `github_resource_not_found`
  - `409` -> `github_conflict`
  - `422` -> `github_validation_failed`
  - `429` -> `github_rate_limited`
  - `5xx` or transport failures -> `github_upstream_unavailable`

## Security Notes

- Development storage uses environment variables referenced by `token_env_var`.
- `token_env_var` is resolved through the shared secret-reference layer and never persisted as a raw token value.
- This is acceptable for local development and controlled demos, but it is not the final enterprise secret-management story.
- Production deployments should resolve GitHub credentials from a KMS-backed secret manager or equivalent platform secret store.
- Authorization headers and token-like values are redacted from API errors and sanitized tool-call payloads.
- Tool configs may safely store repository allowlists and trust classification hints, but they must not contain the actual token.

## Repository Trust Classification

AgentGate classifies GitHub repositories into:

- `internal`
- `external`
- `public`
- `unknown`

The current classifier uses connector config and runtime hints:

- `public_repositories`
- `internal_repositories`
- `internal_owners`
- request metadata such as `repository_visibility`

For policy consistency, public and external repositories are treated as external recipients for GitHub write actions, and GitHub tool calls also receive structured runtime classifications such as:

- `public_repository`
- `external_repository`
- `unknown_repository_trust`
- `github_comment_body`
- `public_comment_body`
- `github_issue_body`
- `public_issue_body`

## Policy Patterns

The demo seed includes GitHub-focused policies for:

- requiring approval before public repository comments
- requiring approval for issue creation by production agents
- blocking confidential public comments
- blocking destructive GitHub actions

Example policy shapes:

Require approval for public comments:

```json
{
  "match": "all",
  "rules": [
    { "field": "tool_name", "operator": "equals", "value": "GitHub" },
    { "field": "action_name", "operator": "contains", "value": "comment" },
    { "field": "repo_trust", "operator": "equals", "value": "public" }
  ]
}
```

Block confidential public comments:

```json
{
  "match": "all",
  "rules": [
    { "field": "tool_name", "operator": "equals", "value": "GitHub" },
    { "field": "action_name", "operator": "contains", "value": "comment" },
    { "field": "repo_trust", "operator": "equals", "value": "public" },
    { "field": "data_classification", "operator": "contains", "value": "confidential" },
    { "field": "data_classification", "operator": "contains", "value": "public_comment_body" }
  ]
}
```

## Diagnostics

GitHub tools now expose a connector health endpoint:

- `GET /v1/tools/{tool_id}/health`
- `GET /v1/tools/{tool_id}/health?probe=true`

Behavior:

- without `probe`, the endpoint reports whether credentials are configured
- with `probe=true`, the connector performs a safe `GET /rate_limit` check when a token is present
- the default seeded demo does not require a GitHub token, so unconfigured status is expected in a clean local setup

## GitHub App Readiness

This build does not fully implement GitHub App authentication.

What is in place:

- a clean GitHub auth provider interface
- an environment-token provider for local development and demos

What should come next:

- a GitHub App auth provider that exchanges app credentials for installation tokens
- installation selection and tenant binding
- installation-token caching and refresh
- stricter repository-to-installation mapping

The goal is to swap auth providers without rewriting the GitHub adapter or bypassing AgentGate governance.

## Demo Flow

The default sales demo does not require a GitHub token and does not call GitHub automatically.

To demo the connector itself:

1. Seed the demo environment.
2. Export `AGENTGATE_GITHUB_TOKEN`.
3. Use the seeded `GitHub` tool in the demo tenant.
4. Call the gateway with a safe read such as `get_repository_metadata`.
5. Try `comment_on_issue_or_pr` against `octocat/hello-world` to see approval routing.

Example gateway payload:

```json
{
  "agent_id": "demo-agent-id",
  "user_id": "demo-user-id",
  "original_intent": "Review repository posture and leave notes if necessary.",
  "tool_name": "GitHub",
  "action_name": "comment_on_issue_or_pr",
  "arguments": {
    "repository": "octocat/hello-world",
    "repository_visibility": "public",
    "number": 14,
    "body": "AgentGate review note."
  },
  "data_classifications": ["customer_data"],
  "metadata": {}
}
```

Expected result:

- public comment requests should route to `pending_approval`
- safe metadata reads should execute immediately when credentials are present

## Production Hardening Checklist

- move GitHub credentials from plain env management to a secret manager or KMS-backed injection path
- add a GitHub App auth provider and installation-token lifecycle management
- add outbound retry telemetry, alerting, and circuit-breaker behavior
- add repository trust synchronization from a source of truth instead of only static config
- add webhook ingestion for richer state validation and audit correlation
- add stronger payload retention and encryption controls for stored tool-call bodies
- add per-connector rate-limit dashboards and error budgets
- add tenant-scoped connector ownership and approval policies for connector changes

## Current Limitations

- no GitHub App auth yet
- no webhook ingestion yet
- no branch protection, merge, close, or delete actions yet
- no tenant-managed connector secret records yet
- no cloud secret-manager-backed auth provider yet
