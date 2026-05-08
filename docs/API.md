# API

## Health

- `GET /health`
- `GET /ready`
- `GET /metrics`

## Auth

- `POST /v1/auth/bootstrap`
- `POST /v1/auth/login`
- `GET /v1/auth/me`
- `GET /v1/auth/csrf-token`
- `POST /v1/auth/logout`
- `POST /v1/auth/users`
- `GET /v1/auth/oidc/{tenant_slug}/config-status`
- `GET /v1/auth/oidc/{tenant_slug}/login`
- `GET /v1/auth/oidc/{tenant_slug}/callback`
- `POST /v1/auth/oidc/exchange`

OIDC auth notes:

- Local email/password auth remains active and is still the default for development.
- `AGENTGATE_AUTH_SESSION_MODE=token` keeps the current bearer-token browser flow.
- `AGENTGATE_AUTH_SESSION_MODE=cookie` stores the same stateless JWT in an HttpOnly cookie for browser clients and returns a CSRF token instead of the JWT body.
- `GET /v1/auth/csrf-token` is the safe browser endpoint for fetching or refreshing the signed CSRF token used on unsafe cookie-authenticated requests.
- `POST /v1/auth/logout` clears browser session cookies. Bearer-token clients do not depend on it.
- `GET /v1/auth/me` and all JWT-authenticated tenant APIs re-check the current `User.is_active` state on each request.
- Deactivated users cannot log in locally, redeem OIDC exchange tickets, or continue using previously issued JWTs.
- CSRF is enforced only for unsafe cookie-authenticated browser requests. Bearer-token and API-key machine clients are intentionally excluded.
- OIDC is tenant-scoped and optional.
- `config-status` is public and only returns safe metadata such as whether SSO is configured and which provider label to show.
- The browser callback issues a short-lived exchange ticket, not the final AgentGate JWT directly.
- `POST /v1/auth/oidc/exchange` converts that exchange ticket into the normal AgentGate JWT used by the rest of the API.
- In cookie mode, the OIDC exchange endpoint sets the HttpOnly cookie session instead of returning the JWT body.
- OIDC config records use `client_secret_env_var` or `client_secret_ref`; raw client secrets are not stored in the database.
- The current build resolves `client_secret_env_var` and env-style secret references. Placeholder `secret_ref:` and `vault:` values fail closed until an external resolver is added.

## Dashboard

- `GET /v1/dashboard/overview`

## Onboarding

- `GET /v1/onboarding/status`
- `POST /v1/onboarding/dismiss`
- `POST /v1/onboarding/reset`
- `POST /v1/onboarding/demo-policy`

Onboarding API notes:

- The onboarding status endpoint is tenant-scoped and limited to owner, admin, and security reviewer roles.
- The status response is intentionally safe-summary only. It reports setup posture such as whether the tenant has agents, tools, policies, approval coverage, audit-integrity availability, and settings visibility.
- The onboarding response must not expose connector config bodies, secret refs, env-var token names, decrypted payloads, or unsafe audit metadata.
- `POST /v1/onboarding/dismiss`, `POST /v1/onboarding/reset`, and `POST /v1/onboarding/demo-policy` are limited to owner and admin roles.
- Dismiss and reset operations only manage tenant-scoped walkthrough state. They do not alter auth, tenant identity, or external integrations.
- `POST /v1/onboarding/demo-policy` is optional and idempotent. It creates one starter approval policy only if that exact onboarding policy does not already exist.
- Onboarding does not create connectors, inject secrets, or replace the narrower agent, tool, policy, or settings APIs.

## Users

- `GET /v1/users`
- `GET /v1/users/{user_id}`
- `PATCH /v1/users/{user_id}`
- `POST /v1/users/{user_id}/deactivate`
- `POST /v1/users/{user_id}/reactivate`

User API notes:

- `GET` endpoints are tenant-scoped and limited to owner, admin, and security reviewer roles.
- `PATCH`, `/deactivate`, and `/reactivate` are tenant-scoped and limited to owner and admin roles.
- `PATCH /v1/users/{user_id}` only accepts safe non-secret profile fields in the current build: `full_name` and `role`.
- Only a tenant owner can promote another user to `owner` or manage another owner account.
- The last active owner in a tenant cannot be deactivated or demoted.
- Deactivation records `deactivated_at` and `deactivation_reason`, blocks future authenticated use, and revokes any active agent API keys created by that user.
- Reactivation restores the user account but does not restore previously revoked agent API keys.
- `provisioned_source` currently reports `local`, `oidc`, `scim`, or `system`. Local, OIDC, and SCIM provisioning are exercised in the current build.

## SCIM

- `GET /v1/scim/v2/Users`
- `GET /v1/scim/v2/Users/{user_id}`
- `POST /v1/scim/v2/Users`
- `PUT /v1/scim/v2/Users/{user_id}`
- `PATCH /v1/scim/v2/Users/{user_id}`

SCIM API notes:

- SCIM is disabled by default and only becomes active when `AGENTGATE_SCIM_TENANT_TOKEN_REFS` is configured.
- SCIM uses bearer-token auth only. It does not use browser session cookies or the normal operator login flow.
- Each configured SCIM token must map to exactly one tenant.
- Raw SCIM tokens are not stored in the database. Use env-backed or secret-ref-style configuration.
- `POST`, `PUT`, and `PATCH` operate on the existing tenant-scoped user model instead of a separate identity store.
- SCIM-created users are stored with `provisioned_source="scim"` and default to the `viewer` role.
- SCIM role management is intentionally unsupported in this build. Requests that attempt to manage roles are rejected.
- `active=false` uses the existing user deactivation path, including owner lockout protection and user-owned agent API key revocation.
- `active=true` reuses the existing reactivation path.
- SCIM `Groups` and broad filter coverage are intentionally out of scope for the current build.
- SCIM requests are rate limited and can return `429 rate_limited`.

## Agents

- `GET /v1/agents`
- `POST /v1/agents`
- `GET /v1/agents/{agent_id}`
- `PUT /v1/agents/{agent_id}`
- `POST /v1/agents/{agent_id}/suspend`
- `POST /v1/agents/{agent_id}/revoke`
- `POST /v1/agents/{agent_id}/api-keys`
- `GET /v1/agents/{agent_id}/api-keys`
- `POST /v1/agents/{agent_id}/api-keys/{api_key_id}/revoke`

Agent API key route notes:

- `GET /v1/agents/{agent_id}/api-keys` is tenant-scoped and available to owner, admin, security reviewer, and the owning developer.
- `POST /v1/agents/{agent_id}/api-keys` and `POST /v1/agents/{agent_id}/api-keys/{api_key_id}/revoke` are limited to owner, admin, and the owning developer.
- Developers can manage keys only for agents they own.
- Viewer and approver roles do not get agent API-key lifecycle access.
- API key create and revoke operations write audit events.

## Tools

- `GET /v1/tools`
- `GET /v1/tools/summary`
- `POST /v1/tools`
- `POST /v1/tools/safe-metadata`
- `GET /v1/tools/{tool_id}`
- `GET /v1/tools/{tool_id}/safe-detail`
- `GET /v1/tools/{tool_id}/health`
- `POST /v1/tools/{tool_id}/probe-health`
- `PUT /v1/tools/{tool_id}`
- `PATCH /v1/tools/{tool_id}/safe-metadata`

GitHub tool notes:

- `type: "github"` is supported.
- GitHub tools support `config.auth_mode` values `env_pat`, `env_token`, and `github_app`.
- Env-token mode uses `config.token_env_var` and resolves it through the shared secret-reference layer without returning the raw token.
- GitHub App mode uses `config.app_id`, `config.installation_id`, and exactly one of `config.private_key_env_var` or `config.private_key_secret_ref`.
- Raw GitHub tokens, installation tokens, JWTs, and private keys are rejected if placed directly in `config`.
- GitHub tools may also use `config.repository_allowlist`, `config.internal_repositories`, `config.internal_owners`, `config.public_repositories`, `config.max_read_retries`, `config.retry_backoff_seconds`, and `config.token_cache_ttl_seconds`.
- Supported GitHub actions are `get_repository_metadata`, `list_pull_requests`, `get_pull_request_details`, `create_issue`, and `comment_on_issue_or_pr`.
- Destructive GitHub actions are blocked at the adapter layer even if a caller attempts to invoke them.

Tool visibility API notes:

- `GET /v1/tools/summary` and `GET /v1/tools/{tool_id}/safe-detail` are tenant-scoped and limited to owner, admin, and security reviewer roles.
- These endpoints return safe metadata only: tool identity, connector type, enabled status, base URL host when present, auth mode label, trust-domain hint when applicable, allowlist counts, supported actions, health posture, warning flags, and safe-detail fields such as sanitized base URL, allowlist values, GitHub App IDs, and documentation path.
- These safe visibility endpoints do not expose raw `config`, tokens, private keys, secret refs, env-var token names, auth emails, request payloads, or decrypted data.
- `POST /v1/tools/safe-metadata` and `PATCH /v1/tools/{tool_id}/safe-metadata` are tenant-scoped and limited to owner and admin roles.
- These safe metadata routes accept only non-secret connector metadata such as names, auth-mode labels, base URLs, trust domains, allowlists, and GitHub App IDs. They do not accept raw credentials, secret refs, env-var names, auth emails, or Authorization headers.
- The safe metadata routes preserve or inject external credential bindings server-side when needed for validation, but they do not return those bindings in browser-safe responses.
- `POST /v1/tools/{tool_id}/probe-health` performs a safe outbound connector probe and is limited to owner and admin roles.
- The existing `GET /v1/tools`, `GET /v1/tools/{tool_id}`, `POST /v1/tools`, and `PUT /v1/tools/{tool_id}` APIs remain the broader admin/programmatic tool-management surface.

Jira tool notes:

- `type: "jira"` is supported.
- Jira tools support `config.auth_mode` values `env_token` and `basic_env`.
- `env_token` mode uses `config.token_env_var`.
- `basic_env` mode uses `config.api_token_env_var` plus `config.email_env_var`.
- Raw Jira tokens, passwords, Authorization headers, and auth emails are rejected if placed directly in `config`.
- Jira tools require `base_url` and `config.project_allowlist`.
- Jira tools may also use `config.issue_type_allowlist`, `config.transition_allowlist`, `config.assignee_allowlist`, `config.external_project_keys`, `config.max_read_retries`, and `config.retry_backoff_seconds`.
- Supported Jira actions are `get_issue`, `search_issues`, `create_issue`, `add_comment`, `transition_issue`, and `assign_issue`.
- `search_issues` is intentionally constrained by allowlisted projects plus bounded query limits.
- `create_issue` requires an issue type that is allowlisted.
- `transition_issue` requires an allowlisted transition id or name.
- `assign_issue` requires an allowlisted assignee account id.
- Destructive Jira actions are blocked at the adapter layer even if a caller attempts to invoke them.

MCP tool notes:

- `type: "mcp"` is supported.
- The shared tool `base_url` field is the MCP server URL in this build.
- MCP tools currently support `config.transport="http"` only.
- MCP tools support `config.auth_mode` values `none`, `bearer_env`, and `api_key_env`.
- `bearer_env` uses `config.token_env_var`.
- `api_key_env` uses `config.api_key_env_var`.
- Raw MCP bearer tokens, API keys, Authorization headers, and secret-bearing header maps are rejected if placed directly in `config`.
- MCP tools require `config.allowed_tool_names`.
- MCP tools may also use `config.blocked_tool_names`, `config.max_request_bytes`, `config.max_response_bytes`, `config.timeout_ms`, `config.trust_domain`, `config.max_read_retries`, and `config.retry_backoff_seconds`.
- Supported MCP actions are `list_tools` and `call_tool`.
- `call_tool` is intentionally scoped: the requested remote tool name must be allowlisted and must not be blocked.
- `list_tools` returns only the visible allowlisted tool subset. It does not expose unrestricted upstream tool discovery.
- MCP `call_tool` is not blindly retried.

## Policies

- `GET /v1/policies`
- `POST /v1/policies`
- `PUT /v1/policies/{policy_id}`

Policy API notes:

- The policy API is the current supported surface for tenant-scoped policy creation and updates.
- `GET /v1/policies` returns the tenant policy set for the authenticated user.
- `POST /v1/policies` and `PUT /v1/policies/{policy_id}` are limited to owner and admin roles.
- The browser policy page uses the same APIs for safe starter-template creation and enable or disable changes; it does not bypass the normal policy routes.
- The repo does not add a separate policy-import API for pilot packs. The pilot-pack helper script uses the existing `GET`, `POST`, and `PUT` policy endpoints.
- Policy packs should stay conservative, reviewable, and free of secrets. They must not contain connector credentials, secret refs, env-var token names, or raw payload examples.
- The shipped pilot default pack is intentionally approval-heavy and assumes operators will still review connector allowlists, trust classifications, and reviewer coverage before pilot traffic.

## Gateway

- `POST /v1/gateway/tool-call`
- `GET /v1/gateway/tool-calls`

Gateway payload notes:

- Sensitive execution arguments are protected at rest before the `ToolCall` record is committed.
- `GET /v1/gateway/tool-calls` returns sanitized `request_payload` and `response_payload` views only.
- Internal `execution_arguments` are never returned through the public API.
- `POST /v1/gateway/tool-call` is rate limited and can return `429 rate_limited` with a generic error body and `Retry-After`.

## Approvals

- `GET /v1/approvals`
- `POST /v1/approvals/{approval_id}/approve`
- `POST /v1/approvals/{approval_id}/reject`
- `GET /v1/approvals/{approval_id}/notification-status`

Approval response notes:

- Approval list/detail responses may include `notification_status` for Slack approval alerts.
- Approval responses may include `execution_status` when an approval triggered queue-backed execution.
- `notification_status` is operational metadata only and never includes raw Slack credentials or raw tool payloads.
- Approval responses include the same sanitized nested `tool_call` view used by the gateway list API.

## Jobs

- `GET /v1/jobs`
- `GET /v1/jobs/{job_id}`
- `POST /v1/jobs/{job_id}/retry`

Job API notes:

- Job APIs are tenant-scoped and limited to owner, admin, security reviewer, and developer roles.
- Job payloads are sanitized before serialization and are intended for operator diagnostics, not for replaying raw execution state.
- `status` values are `queued`, `running`, `succeeded`, `failed`, `retry_exhausted`, and `cancelled`.
- Job responses can include safe reliability metadata such as `locked_by`, `locked_at`, `lease_expires_at`, and `dead_letter_reason`.
- `GET /v1/jobs` supports filtering for dead-letter review with `?dead_lettered=true`.
- `POST /v1/jobs/{job_id}/retry` is restricted to owner, admin, and security reviewer roles.
- Manual retry is intentionally blocked for approved execution jobs to avoid blind duplicate writes.
- `POST /v1/jobs/{job_id}/retry` is rate limited and can return `429 rate_limited`.

## Workers

- `GET /v1/workers`
- `GET /v1/workers/status`

Worker API notes:

- Worker endpoints are restricted to owner, admin, and security reviewer roles.
- Responses expose worker identity, heartbeat, status, and safe runtime metadata only.
- Worker endpoints do not expose tenant payloads, raw job inputs, or secrets.

## Audit Exports

- `GET /v1/audit-exports`
- `POST /v1/audit-exports`
- `PATCH /v1/audit-exports/{config_id}`
- `POST /v1/audit-exports/{config_id}/run`
- `GET /v1/audit-exports/{config_id}/status`

Audit export API notes:

- `GET /v1/audit-exports` and `GET /v1/audit-exports/{config_id}/status` are tenant-scoped and limited to owner, admin, and security reviewer roles.
- `POST /v1/audit-exports`, `PATCH /v1/audit-exports/{config_id}`, and `POST /v1/audit-exports/{config_id}/run` are limited to owner and admin roles.
- Config records store destination metadata, filters, cursor checkpoints, and safe last-run state only.
- `destination_type` values currently include `webhook`, `http_json`, `splunk_hec`, `datadog`, and `custom_placeholder`.
- Raw destination tokens are never stored in the database. Use `secret_ref` or `token_env_var`.
- `endpoint_url` must be an `http` or `https` URL without embedded credentials, query parameters, or fragments.
- `GET /v1/audit-exports` and `GET /v1/audit-exports/{config_id}/status` return `credential_source` and `credential_status` instead of actual references or secret values.
- `POST /v1/audit-exports/{config_id}/run` always writes a durable job. In `inline` mode it can complete during the request; in `worker` mode it returns a queued job.
- Export jobs maintain a per-config cursor using `last_exported_at` and `last_exported_event_id`, so multiple destinations for the same tenant do not duplicate one another's progress.
- Export payloads contain sanitized audit events only. Decrypted payloads, raw secrets, and payload-protection envelope internals are excluded.
- Exported events may include safe integrity metadata such as `event_hash`, `previous_event_hash`, `sequence_number`, and `hash_algorithm`.

## Audit Integrity

- `GET /v1/audit-integrity/status`
- `POST /v1/audit-integrity/verify`
- `POST /v1/audit-integrity/backfill`
- `GET /v1/audit-integrity/checkpoints`
- `POST /v1/audit-integrity/checkpoints`
- `GET /v1/audit-integrity/checkpoints/{id}`
- `POST /v1/audit-integrity/checkpoints/{id}/verify`

Audit integrity API notes:

- These endpoints are tenant-scoped and limited to owner, admin, and security reviewer roles.
- `GET /v1/audit-integrity/status` reports whether the tenant currently has anchored, legacy, or mixed audit history.
- `POST /v1/audit-integrity/verify` recomputes hashes and chain links for the tenant's anchored audit history and reports integrity issues without exposing secrets.
- `POST /v1/audit-integrity/backfill` supports `dry_run` and real execution for anchoring historical tenant audit rows in order.
- `POST /v1/audit-integrity/checkpoints` always writes a durable checkpoint job. In `inline` mode it can complete during the request; in `worker` mode it returns a queued job.
- Checkpoint records are tenant-scoped and expose only safe fields such as sequence boundaries, checkpoint hashes, status, destination reference, and non-secret metadata.
- Checkpoint documents are built from safe integrity metadata only. Raw secrets, decrypted payloads, protected envelope internals, and unsafe audit metadata are excluded.
- `POST /v1/audit-integrity/checkpoints/{id}/verify` re-verifies the checkpointed audit range and compares the current database state to the stored external checkpoint document.
- Bounded verification by event ID or date is supported only for already anchored events. Legacy or unanchored rows are reported honestly and cannot be used as chain boundaries until backfill runs.
- The current checkpoint destination types are `local`, `object_storage`, and `custom_placeholder`.
- `local` is intended for development or test only. `object_storage` is the production-minded path for S3-compatible destinations.
- Checkpointing improves evidence integrity outside the database trust boundary, but it is not a claim of full immutability unless the external storage itself enforces WORM or Object Lock semantics.
- `POST /v1/audit-integrity/verify`, `POST /v1/audit-integrity/backfill`, `POST /v1/audit-integrity/checkpoints`, and `POST /v1/audit-integrity/checkpoints/{id}/verify` are rate limited and can return `429 rate_limited`.

## Retention

- `GET /v1/retention/status`
- `POST /v1/retention/purge`

Retention API notes:

- `GET /v1/retention/status` is tenant-scoped and limited to owner, admin, and security reviewer roles.
- `POST /v1/retention/purge` is tenant-scoped and limited to owner and admin roles.
- `POST /v1/retention/purge` defaults to `dry_run=true` and can also accept `limit`, `retention_classes`, `tool_name`, and `tool_call_ids`.
- The purge endpoint always writes a durable retention job. In `inline` mode it runs immediately after commit; in `worker` mode it returns a queued job.
- Purge removes replayable `execution_arguments` only. Sanitized operator-facing `request_payload.arguments`, decision data, trace references, and audit references remain intact.
- `POST /v1/retention/purge` is rate limited and can return `429 rate_limited`.

## Scheduled Tasks

- `GET /v1/scheduled-tasks`
- `POST /v1/scheduled-tasks`
- `GET /v1/scheduled-tasks/{task_id}`
- `PATCH /v1/scheduled-tasks/{task_id}`
- `POST /v1/scheduled-tasks/{task_id}/run-now`

Scheduled task API notes:

- `GET /v1/scheduled-tasks` and `GET /v1/scheduled-tasks/{task_id}` are tenant-scoped and limited to owner, admin, and security reviewer roles.
- `POST /v1/scheduled-tasks`, `PATCH /v1/scheduled-tasks/{task_id}`, and `POST /v1/scheduled-tasks/{task_id}/run-now` are limited to owner and admin roles.
- Supported task types are `retention_purge`, `audit_export`, `audit_integrity_verify`, `audit_integrity_checkpoint`, and `connector_health_check`.
- `schedule_kind=interval` requires `interval_seconds`. `schedule_kind=cron` accepts a simple five-field UTC cron expression.
- Scheduled task `config` stores only safe IDs and filters. Secrets, tokens, and connector credentials are rejected and never persisted.
- `POST /v1/scheduled-tasks/{task_id}/run-now` enqueues the underlying durable job immediately but does not bypass the normal job handlers.
- Scheduler `last_status` tracks enqueue behavior such as `idle`, `enqueued`, `duplicate`, or `failed`. Downstream job completion is still tracked on the durable job row.

## Settings

- `GET /v1/settings/overview`

Settings API notes:

- The settings overview endpoint is tenant-authenticated and limited to owner, admin, and security reviewer roles.
- The endpoint itself is intentionally read-only.
- It returns safe summaries for tenant profile status, OIDC / SSO status, GitHub connector health, Slack notification health, audit export status, retention status, scheduled task status, key provider status, rate limiter status, and readiness / metrics links.
- The browser settings page can link operators into the narrower scheduled-task, audit-export, and retention surfaces, but those mutations still use their own role-checked APIs and remain non-secret only.
- It must not expose raw tokens, private keys, secret refs, decrypted payloads, or unsafe config dumps.
- Deployment-level statuses such as key-provider and rate-limiter health can appear in the same response, but the endpoint still remains tenant-authenticated and does not expose other tenants' data.

## OIDC Configuration Notes

- OIDC config fields include `provider_name`, `issuer_url`, `client_id`, `client_secret_env_var`, `client_secret_ref`, `redirect_uri`, `scopes`, `allowed_email_domains`, and `role_mapping`.
- Current role mapping supports group-based and claim-based mappings plus a configurable `default_role`.
- If no mapping matches, new JIT-provisioned users fall back to `viewer` or the configured default role.
- Owner is only granted if the role mapping explicitly resolves to `owner`.
- OIDC JIT-provisioned or OIDC-bound users are marked with `provisioned_source="oidc"`.
- Deactivated users stay blocked even if OIDC role mapping would otherwise resolve to a privileged role.

## Traces

- `GET /v1/traces`
- `POST /v1/traces`
- `POST /v1/traces/{trace_id}/steps`
- `GET /v1/traces/{trace_id}`

## Audit

- `GET /v1/audit/events`

Audit notes:

- Audit metadata is sanitized on write and sanitized again on response serialization.
- Secret values and protected payload envelopes are never returned through the audit API.
- Export severity is inferred from audit metadata or event-type heuristics during audit-export processing; the core `AuditEvent` schema remains backward compatible.
- Audit event responses may include non-sensitive integrity metadata such as `event_hash`, `previous_event_hash`, `chain_scope`, `sequence_number`, `hash_algorithm`, and `anchored_at`.

## Integrations

- `GET /v1/integrations/slack/health`

## Security

- `GET /v1/security/key-status`

Security API notes:

- `GET /v1/security/key-status` is restricted to owner, admin, and security reviewer roles.
- The response includes provider type, readiness, configured purposes, active key ref, active key version, safe AWS region metadata when applicable, and warnings only.
- Raw key material, client secrets, bot tokens, and connector credentials are never returned.

## Metrics And Readiness Notes

- `GET /metrics` exposes safe aggregate metrics only and does not include tenant labels, user labels, raw payload values, Redis keys, or secrets.
- `GET /ready` includes safe status for database connectivity plus jobs, scheduler config, keys, selected integration/config checks, and the configured rate-limit provider.
- The `keys` readiness check reports provider type, active key ref, readiness, warnings, and AWS region when applicable without exposing raw key material, wrapped data keys, or cloud credentials.
- Sensitive control-plane endpoints can return `429` with `error.code="rate_limited"` and a `Retry-After` header.
- Job reliability metrics include worker counts, lease expirations, stale recovery totals, dead-letter job counts, and retry totals by job type.
- Scheduler metrics include current due scheduled-task counts, current last-status counts, enqueue totals, and scheduler error totals without tenant labels or secret-bearing config values.
- Rate-limit metrics include provider, scope, allowed totals, blocked totals, and backend error totals.

## Demo

- `POST /v1/demo/run-sales-agent-risk-scenario`

## Gateway Request Shape

```json
{
  "agent_id": "uuid",
  "user_id": "uuid",
  "trace_id": "optional-trace-id",
  "original_intent": "Prepare and send a renewal proposal to Acme Corp.",
  "tool_name": "Email",
  "action_name": "send_external_email",
  "arguments": {
    "recipient": "buyer@acme.com",
    "attachment": "internal_pricing_sheet.xlsx"
  },
  "data_classifications": ["internal_pricing", "customer_data"],
  "metadata": {}
}
```

## Gateway Response Shape

```json
{
  "tool_call_id": "uuid",
  "trace_id": "uuid",
  "decision": "require_approval",
  "status": "pending_approval",
  "intent": {
    "intent_match": false,
    "confidence": 0.7,
    "explanation": "The proposed action includes behaviors that were not clearly authorized by the original intent.",
    "detected_mismatch_reasons": ["Sensitive data is being routed to an external recipient."]
  },
  "risk": {
    "score": 83,
    "band": "high",
    "reasons": ["External recipient increases data exposure risk."],
    "summary": "Risk is high at score 83 based on 5 contributing factors.",
    "factors": [
      {
        "key": "recipient:external",
        "label": "External recipient",
        "category": "recipient",
        "weight": 15,
        "explanation": "External recipients increase the chance of unintended data disclosure."
      }
    ]
  },
  "policies": {
    "decision": "require_approval",
    "matched_policies": [],
    "reasons": ["Built-in externalization guardrail activated for intent mismatch."]
  },
  "executed": false
}
```

## API Key Notes

- Agent API keys are hashed at rest and never stored in raw form.
- New keys default to the `gateway:invoke` scope and 90-day expiration unless a caller sets a different supported expiry.
- `GET /v1/agents/{agent_id}/api-keys` returns metadata only; the raw key is only returned once at creation time.
- The browser UI follows the same rule: the raw secret is shown once immediately after creation and is not retrievable later.
- `last_used_at` updates when a key successfully authenticates a gateway request.
- Revocation is immediate for future gateway requests and writes an audit event.
- Expired or revoked API keys are rejected before gateway processing begins.

## GitHub Connector Notes

- Env-token mode reads credentials from the environment variable named by `config.token_env_var`.
- GitHub App mode signs a short-lived app JWT, exchanges it for an installation token, caches that installation token in memory only, and refreshes it before expiry.
- The default demo seed still expects `AGENTGATE_GITHUB_TOKEN` if you want to exercise GitHub actions without reconfiguring the tool.
- Public repository comments can be routed to approval based on seeded policies and repository trust classification.
- GitHub tools support `GET /v1/tools/{tool_id}/health` for local diagnostics and `?probe=true` for an optional safe upstream `GET /rate_limit` check.
- Health responses can safely include `auth_provider`, `token_present`, `app_id`, `installation_id`, `private_key_env_var`, `private_key_reference_type`, token-cache metadata, repository allowlist counts, and warnings.
- Tool-call payloads expose sanitized connector context such as repository and `repo_trust`, but do not expose raw connector credentials.

## Jira Connector Notes

- Env-token mode reads credentials from the environment variable named by `config.token_env_var`.
- Basic-env mode reads credentials from `config.api_token_env_var` and `config.email_env_var`.
- Jira tools require `base_url` plus `project_allowlist`.
- `create_issue`, `transition_issue`, and `assign_issue` are intentionally scoped by allowlists. They do not act as unrestricted ticket mutations.
- Jira tools support `GET /v1/tools/{tool_id}/health` for local diagnostics and `?probe=true` for an optional safe project-search probe.
- Health responses can safely include `auth_provider`, `token_present`, env-var names, allowlist counts, and warnings.
- Tool-call payloads do not expose raw Jira credentials, Authorization headers, or protected execution arguments.

## MCP Connector Notes

- AgentGate's MCP support is a governed HTTP proxy foundation for MCP-compatible tool servers, not a full MCP transport implementation.
- Use the tool `base_url` as the MCP server URL.
- Supported auth modes are `none`, `bearer_env`, and `api_key_env`.
- MCP support is intentionally limited to `list_tools` and `call_tool`.
- Remote tool names must be explicitly allowlisted with `config.allowed_tool_names`.
- `config.blocked_tool_names` can deny remote tools even if the upstream server exposes them.
- `config.trust_domain` can be `internal`, `external`, or `unknown` and influences runtime risk and approval behavior.
- AgentGate enforces bounded request and response sizes with `config.max_request_bytes` and `config.max_response_bytes`.
- `GET /v1/tools/{tool_id}/health` supports MCP and can optionally probe `tools/list` with `?probe=true`.
- Agents should call MCP tools through AgentGate rather than directly so tenant auth, policy, approvals, audit, traces, and payload protection remain in force.

## Slack Notification Notes

- Slack approval notifications are disabled by default.
- When enabled, approval creation writes a durable notification job and either delivers it inline or hands it to the worker depending on `AGENTGATE_JOB_DISPATCH_MODE`.
- Slack delivery failure never changes the gateway decision, approval record, or trace status.
- Approval responses can report `notification_status.status` values such as `disabled`, `queued`, `running`, `sent`, `failed`, or `retry_exhausted`.
- `GET /v1/integrations/slack/health` checks whether Slack notification configuration is present. Add `?probe=true` to call Slack `auth.test` for a safe connectivity probe.
- Slack alerts are outbound only in this version. Reviewers still approve or reject inside AgentGate.

## Audit Export Notes

- Splunk HEC and Datadog-compatible destinations require `token_env_var` or `secret_ref`.
- Generic `webhook`, `http_json`, and `custom_placeholder` destinations may run without auth headers, though production deployments should usually authenticate them.
- Export delivery uses explicit timeouts, redacts upstream error details, and retries only safe, retryable failures such as timeouts, `429`, or `5xx`.
- `401`, `403`, `404`, `409`, and `422` are treated as non-retryable export failures.
- Dry-run export is supported through `POST /v1/audit-exports/{config_id}/run` with `{"dry_run": true}` and does not advance the per-config cursor.
- Export payloads can preserve safe audit-integrity metadata so downstream SIEM or archive systems can retain verification context.

## Approved Execution Notes

- Approving with `execute_now=true` writes a durable `approval_execution.tool_call` job.
- In `inline` mode, AgentGate executes that job inside the API process after the approval transaction commits.
- In `worker` mode, the approval response returns immediately with `execution_status.status="queued"` and the worker performs the execution later.
- Approved execution jobs do not blindly retry tool writes. The current implementation uses single-attempt execution to avoid duplicate GitHub issues, comments, or other non-idempotent mutations.
- If the protected execution payload was already purged by retention, approved execution fails closed with `protected_payload_purged`.

## Payload Protection Notes

- Sensitive values such as tokens, passwords, authorization fields, cookies, and selected content fields are protected with field-level encryption envelopes in stored execution arguments.
- Current envelopes always include `alg`, `ciphertext`, `key_ref`, `key_version`, `provider`, and `created_at`.
- AWS KMS-backed envelopes additionally include `encrypted_data_key` and `encrypted_data_key_algorithm` so the ciphertext can be decrypted later without storing plaintext key material.
- API-facing payloads render placeholders such as `[REDACTED]` or `[PROTECTED]` instead of raw secrets or ciphertext envelopes.
- Tool calls also expose payload protection metadata including `payload_protection_version`, `payload_retention_class`, `payload_expires_at`, and `payload_redaction_status`.
- Current retention classes are `standard`, `short_lived`, `extended`, and `legal_hold`.
- `legal_hold` payloads are never purged automatically.
- Purged execution payloads are replaced with a tombstone marker instead of being decrypted or replayed.
- Trace and audit APIs return sanitized metadata views only.
- Corrupted protected payload state causes approved execution to fail closed with `protected_payload_invalid`.

## Key And Secret Management Notes

- `AGENTGATE_KEY_PROVIDER=env` remains the default local/dev path and uses a Fernet key from `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` or `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF`.
- `AGENTGATE_KEY_PROVIDER=aws_kms` uses `AGENTGATE_AWS_REGION` plus `AGENTGATE_AWS_KMS_KEY_ID` and creates AWS KMS-backed envelope-encrypted data keys for protected payload fields.
- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` still works for local and existing deployments and can remain configured as a legacy decrypt-only source during migration to AWS KMS.
- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF` can point at `env:...` for explicit secret-reference wiring.
- `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS` can register decrypt-only env key refs so old envelopes remain decryptable during manual rotation or during migration from env-backed envelopes to AWS KMS-backed envelopes.
- GitHub App private keys can resolve through `private_key_env_var` or `private_key_secret_ref`, but only env-backed resolution is implemented today. `secret_ref:` and `vault:` placeholders still fail closed until an external resolver is added.

## OpenAPI

FastAPI serves interactive API docs at `/docs` and the OpenAPI schema at `/openapi.json`.

## API Evaluation Collection

For local or self-hosted reviewer workflows, use the repo-friendly request collection under `api-collections/http/AgentGate/`.

Included files:

- `operator-evaluation-token.http`
- `operator-evaluation-cookie.http`
- `http-client.env.json.example`

The collection covers health, readiness, login, current-user checks, settings, onboarding, tools, jobs, scheduled tasks, audit integrity, audit checkpoints, retention dry-run, users, and a safe seeded-demo gateway path without requiring live GitHub, Jira, MCP, Slack, or AWS connectivity.
