# GitHub Connector

## Overview

AgentGate includes a hardened GitHub connector behind the standard tool-adapter interface. Every GitHub action still goes through the normal gateway path for tenant checks, caller identity, intent analysis, risk scoring, policy evaluation, approvals, audit logging, and trace replay.
For controlled pilots, GitHub is the strongest current real connector and the recommended first live workflow surface.

Supported actions in this build:

- `get_repository_metadata`
- `list_pull_requests`
- `get_pull_request_details`
- `create_issue`
- `comment_on_issue_or_pr`

Destructive and unknown actions are explicitly blocked at the adapter layer and must not rely on policy matching alone.

## Auth Modes

Supported `config.auth_mode` values:

- `env_pat`
- `env_token`
- `github_app`

Guidance:

- `env_pat` and `env_token` are the local/dev-friendly env-token path. `env_pat` remains as a backward-compatible alias.
- `github_app` is the recommended production auth path.

## Local Env-Token Configuration

Set a token in the runtime environment:

```bash
export AGENTGATE_GITHUB_TOKEN=ghp_fake_local_dev_token
```

PowerShell:

```powershell
$env:AGENTGATE_GITHUB_TOKEN="ghp_fake_local_dev_token"
```

Example tool config:

```json
{
  "name": "GitHub",
  "type": "github",
  "description": "GitHub repository metadata and issue workflow connector",
  "base_url": "https://api.github.com",
  "config": {
    "auth_mode": "env_token",
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

## GitHub App Configuration

GitHub App mode stores only safe metadata in tool config:

- `app_id`
- `installation_id`
- exactly one of:
  - `private_key_env_var`
  - `private_key_secret_ref`
- optional `token_cache_ttl_seconds`

Example using an env var directly:

```json
{
  "name": "GitHub",
  "type": "github",
  "description": "GitHub App-backed connector",
  "base_url": "https://api.github.com",
  "config": {
    "auth_mode": "github_app",
    "app_id": "12345",
    "installation_id": "67890",
    "private_key_env_var": "AGENTGATE_GITHUB_APP_PRIVATE_KEY",
    "token_cache_ttl_seconds": 600,
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

Example using the shared secret-reference pattern:

```json
{
  "config": {
    "auth_mode": "github_app",
    "app_id": "12345",
    "installation_id": "67890",
    "private_key_secret_ref": "env:AGENTGATE_GITHUB_APP_PRIVATE_KEY"
  }
}
```

Current resolver behavior:

- `env:...` works today
- `secret_ref:...` and `vault:...` are parsed but still fail closed until a real external resolver is implemented

## GitHub App Token Flow

GitHub App mode works like this:

1. Resolve the private key through `private_key_env_var` or `private_key_secret_ref`.
2. Generate a short-lived GitHub App JWT locally.
3. Exchange that JWT for an installation access token.
4. Cache the installation token in memory only.
5. Refresh the token before expiry.
6. Use the installation token for the normal GitHub API call.

Important constraints:

- raw private keys are never stored in the database
- GitHub App JWTs are never persisted
- installation tokens are never persisted
- Authorization headers are never returned in APIs

## Required GitHub App Permissions

Minimum practical permissions for the currently supported actions:

- `Metadata`: read
- `Pull requests`: read
- `Issues`: read and write

`Issues` write is required for:

- `create_issue`
- `comment_on_issue_or_pr`

If you only need safe read actions, you can scope the app more tightly, but AgentGate will still block unsupported actions at the adapter boundary.

## GitHub Enterprise Server Support

If you already use a non-default `base_url`, GitHub App auth uses that same base URL for:

- installation-token exchange
- connector API calls
- health probes

This supports GitHub Enterprise Server API roots such as:

- `https://github.example.com/api/v3`

Repository allowlists, trust classification, and action restrictions still apply exactly the same way.

## API Validation Rules

The API enforces these configuration rules:

- raw token-like fields are rejected
- raw private-key fields are rejected
- `env_pat`, `env_token`, and `github_app` are the only supported auth modes
- env-token mode requires `token_env_var`
- GitHub App mode requires:
  - `app_id`
  - `installation_id`
  - exactly one private-key reference field
- repository allowlists and trust lists are normalized and validated

## Reliability Behavior

- The connector uses explicit connect, read, write, and pool timeouts.
- Safe read operations may retry with bounded exponential backoff.
- Writes are not retried.
- GitHub App installation-token exchange also uses explicit timeout handling.
- Installation tokens are cached in memory only and refreshed before expiry.
- Writes remain single-attempt even when using GitHub App auth.

Upstream response handling remains structured:

- `401` -> `github_auth_failed`
- `403` -> `github_forbidden`
- `404` -> `github_resource_not_found`
- `409` -> `github_conflict`
- `422` -> `github_validation_failed`
- `429` -> `github_rate_limited`
- `5xx` or transport failures -> `github_upstream_unavailable`

## Health And Readiness

GitHub tools expose:

- `GET /v1/tools/{tool_id}/health`
- `GET /v1/tools/{tool_id}/health?probe=true`

Safe health fields can include:

- `auth_provider`
- `token_present`
- `credentials_configured`
- `app_id`
- `installation_id`
- `private_key_env_var`
- `private_key_reference_type`
- `token_expires_at`
- `cache_hit`
- `repository_allowlist_count`
- warnings and sanitized error codes

Notes:

- `probe=true` performs a safe upstream `GET /rate_limit` check after resolving a usable credential
- `GET /ready` does not expose GitHub credentials, private keys, JWTs, or installation tokens

## Security Notes

- Tool config may safely store allowlists, trust hints, app IDs, installation IDs, and env/ref names.
- Tool config must never store raw tokens, raw private keys, JWTs, or Authorization headers.
- Repository allowlists are enforced before outbound GitHub calls.
- Repository trust classification still informs policy and approval behavior.
- Public and external write actions still route through the normal approval and audit model.
- Destructive and unknown actions are blocked before auth exchange or outbound execution.

## Migration Path From PAT To GitHub App

Recommended migration:

1. Keep the existing GitHub tool config and PAT/env-token path working in local or lower environments.
2. Create a GitHub App with the minimum permissions AgentGate needs.
3. Install the app on the target repositories or orgs.
4. Inject the private key through `AGENTGATE_GITHUB_APP_PRIVATE_KEY` or a future secret-manager-backed ref.
5. Update the tool config from `auth_mode=env_pat` or `env_token` to `auth_mode=github_app`.
6. Set `app_id`, `installation_id`, and the private-key env/ref field.
7. Verify `GET /v1/tools/{tool_id}/health` and, if desired, `?probe=true`.
8. Remove the PAT only after the GitHub App path is validated.

Compatibility note:

- existing `env_pat` configs continue to work
- `env_token` is the forward-looking explicit name for the same local env-token pattern

## Current Limitations

- no tenant-managed GitHub App installation discovery UI or workflow yet
- no webhook ingestion yet
- no live enterprise repository trust synchronization yet
- GitHub App private key resolution is still env-backed in this build
- `secret_ref:` and `vault:` private-key references still fail closed until a real external resolver exists
- no branch protection, merge, close, reopen, or delete actions yet
