# API

## Health

- `GET /health`
- `GET /ready`
- `GET /metrics`

## Auth

- `POST /v1/auth/bootstrap`
- `POST /v1/auth/login`
- `GET /v1/auth/me`
- `POST /v1/auth/users`
- `GET /v1/auth/oidc/{tenant_slug}/config-status`
- `GET /v1/auth/oidc/{tenant_slug}/login`
- `GET /v1/auth/oidc/{tenant_slug}/callback`
- `POST /v1/auth/oidc/exchange`

OIDC auth notes:

- Local email/password auth remains active and is still the default for development.
- OIDC is tenant-scoped and optional.
- `config-status` is public and only returns safe metadata such as whether SSO is configured and which provider label to show.
- The browser callback issues a short-lived exchange ticket, not the final AgentGate JWT directly.
- `POST /v1/auth/oidc/exchange` converts that exchange ticket into the normal AgentGate JWT used by the rest of the API.
- OIDC config records use `client_secret_env_var` or `client_secret_ref`; raw client secrets are not stored in the database.
- The current build resolves `client_secret_env_var` and env-style secret references. Placeholder `secret_ref:` and `vault:` values fail closed until an external resolver is added.

## Dashboard

- `GET /v1/dashboard/overview`

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

## Tools

- `GET /v1/tools`
- `POST /v1/tools`
- `GET /v1/tools/{tool_id}`
- `GET /v1/tools/{tool_id}/health`
- `PUT /v1/tools/{tool_id}`

GitHub tool notes:

- `type: "github"` is supported.
- GitHub tools must use `config.token_env_var` instead of storing raw tokens in `config`.
- `config.token_env_var` is resolved through the shared secret-reference layer and never returned as a raw token.
- GitHub tools may use `config.auth_mode`, `config.repository_allowlist`, `config.internal_repositories`, `config.internal_owners`, `config.public_repositories`, `config.max_read_retries`, and `config.retry_backoff_seconds`.
- Supported GitHub actions are `get_repository_metadata`, `list_pull_requests`, `get_pull_request_details`, `create_issue`, and `comment_on_issue_or_pr`.
- Destructive GitHub actions are blocked at the adapter layer even if a caller attempts to invoke them.

## Policies

- `GET /v1/policies`
- `POST /v1/policies`
- `PUT /v1/policies/{policy_id}`

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

Job API notes:

- Job APIs are tenant-scoped and limited to owner, admin, security reviewer, and developer roles.
- Job payloads are sanitized before serialization and are intended for operator diagnostics, not for replaying raw execution state.
- `status` values are `queued`, `running`, `succeeded`, `failed`, `retry_exhausted`, and `cancelled`.

## Audit Exports

- `GET /v1/audit-exports`
- `POST /v1/audit-exports`
- `PATCH /v1/audit-exports/{config_id}`
- `POST /v1/audit-exports/{config_id}/run`
- `GET /v1/audit-exports/{config_id}/status`

Audit export API notes:

- Audit export endpoints are tenant-scoped and limited to owner, admin, and security reviewer roles.
- Config records store destination metadata, filters, cursor checkpoints, and safe last-run state only.
- `destination_type` values currently include `webhook`, `http_json`, `splunk_hec`, `datadog`, and `custom_placeholder`.
- Raw destination tokens are never stored in the database. Use `secret_ref` or `token_env_var`.
- `endpoint_url` must be an `http` or `https` URL without embedded credentials, query parameters, or fragments.
- `GET /v1/audit-exports` and `GET /v1/audit-exports/{config_id}/status` return `credential_source` and `credential_status` instead of actual references or secret values.
- `POST /v1/audit-exports/{config_id}/run` always writes a durable job. In `inline` mode it can complete during the request; in `worker` mode it returns a queued job.
- Export jobs maintain a per-config cursor using `last_exported_at` and `last_exported_event_id`, so multiple destinations for the same tenant do not duplicate one another's progress.
- Export payloads contain sanitized audit events only. Decrypted payloads, raw secrets, and payload-protection envelope internals are excluded.

## Retention

- `GET /v1/retention/status`
- `POST /v1/retention/purge`

Retention API notes:

- Retention endpoints are tenant-scoped and limited to owner, admin, and security reviewer roles.
- `POST /v1/retention/purge` defaults to `dry_run=true` and can also accept `limit`, `retention_classes`, `tool_name`, and `tool_call_ids`.
- The purge endpoint always writes a durable retention job. In `inline` mode it runs immediately after commit; in `worker` mode it returns a queued job.
- Purge removes replayable `execution_arguments` only. Sanitized operator-facing `request_payload.arguments`, decision data, trace references, and audit references remain intact.
- `POST /v1/retention/purge` is rate limited and can return `429 rate_limited`.

## OIDC Configuration Notes

- OIDC config fields include `provider_name`, `issuer_url`, `client_id`, `client_secret_env_var`, `client_secret_ref`, `redirect_uri`, `scopes`, `allowed_email_domains`, and `role_mapping`.
- Current role mapping supports group-based and claim-based mappings plus a configurable `default_role`.
- If no mapping matches, new JIT-provisioned users fall back to `viewer` or the configured default role.
- Owner is only granted if the role mapping explicitly resolves to `owner`.

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

## Integrations

- `GET /v1/integrations/slack/health`

## Security

- `GET /v1/security/key-status`

Security API notes:

- `GET /v1/security/key-status` is restricted to owner, admin, and security reviewer roles.
- The response includes provider type, configured purposes, active key ref, active key version, and warnings only.
- Raw key material, client secrets, bot tokens, and connector credentials are never returned.

## Metrics And Readiness Notes

- `GET /metrics` exposes safe aggregate metrics only and does not include tenant labels, user labels, raw payload values, or secrets.
- `GET /ready` includes safe status for database connectivity plus jobs, keys, and selected integration/config checks.
- Sensitive control-plane endpoints can return `429` with `error.code="rate_limited"` and a `Retry-After` header.

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
- Expired or revoked API keys are rejected before gateway processing begins.

## GitHub Connector Notes

- The connector reads credentials from the environment variable named by `config.token_env_var`.
- The default demo seed expects `AGENTGATE_GITHUB_TOKEN` if you want to exercise GitHub actions.
- Public repository comments can be routed to approval based on seeded policies and repository trust classification.
- GitHub tools support `GET /v1/tools/{tool_id}/health` for local diagnostics and `?probe=true` for an optional safe upstream `GET /rate_limit` check.
- Tool-call payloads expose sanitized connector context such as repository and `repo_trust`, but do not expose raw connector credentials.

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

## Approved Execution Notes

- Approving with `execute_now=true` writes a durable `approval_execution.tool_call` job.
- In `inline` mode, AgentGate executes that job inside the API process after the approval transaction commits.
- In `worker` mode, the approval response returns immediately with `execution_status.status="queued"` and the worker performs the execution later.
- Approved execution jobs do not blindly retry tool writes. The current implementation uses single-attempt execution to avoid duplicate GitHub issues, comments, or other non-idempotent mutations.
- If the protected execution payload was already purged by retention, approved execution fails closed with `protected_payload_purged`.

## Payload Protection Notes

- Sensitive values such as tokens, passwords, authorization fields, cookies, and selected content fields are protected with field-level encryption envelopes in stored execution arguments.
- Current envelopes include `alg`, `ciphertext`, `key_ref`, `key_version`, `provider`, and `created_at`.
- API-facing payloads render placeholders such as `[REDACTED]` or `[PROTECTED]` instead of raw secrets or ciphertext envelopes.
- Tool calls also expose payload protection metadata including `payload_protection_version`, `payload_retention_class`, `payload_expires_at`, and `payload_redaction_status`.
- Current retention classes are `standard`, `short_lived`, `extended`, and `legal_hold`.
- `legal_hold` payloads are never purged automatically.
- Purged execution payloads are replaced with a tombstone marker instead of being decrypted or replayed.
- Trace and audit APIs return sanitized metadata views only.
- Corrupted protected payload state causes approved execution to fail closed with `protected_payload_invalid`.

## Key And Secret Management Notes

- The current provider is `env`, designed to preserve local simplicity while keeping the abstraction ready for future KMS-backed implementations.
- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` still works for local and existing deployments.
- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF` can point at `env:...` for explicit secret-reference wiring.
- `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS` can register decrypt-only key refs so old envelopes remain decryptable during manual rotation.

## OpenAPI

FastAPI serves interactive API docs at `/docs` and the OpenAPI schema at `/openapi.json`.
