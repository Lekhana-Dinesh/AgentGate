# Rate Limiting

## Goal

AgentGate now includes a lightweight abuse-protection layer for sensitive control-plane endpoints.

It is designed to:

- stay simple for local development
- be tunable through env vars
- avoid changing the core gateway or approval architecture
- leave room for a future Redis-backed implementation

## Current backend

- current implementation: in-memory
- current scope: single API process
- current behavior in `development` and `test`: disabled by default unless explicitly enabled
- current behavior outside `development` and `test`: enabled by default unless explicitly disabled

## Protected endpoints

- `POST /v1/auth/login`
- `GET /v1/auth/oidc/{tenant_slug}/login`
- `GET /v1/auth/oidc/{tenant_slug}/callback`
- `POST /v1/auth/oidc/exchange`
- `POST /v1/gateway/tool-call`
- `POST /v1/approvals/{approval_id}/approve`
- `POST /v1/approvals/{approval_id}/reject`
- `POST /v1/audit-exports/{config_id}/run`
- `POST /v1/retention/purge`

## Keying model

Rate-limit keys use combinations of:

- client IP
- tenant ID or tenant slug when available
- user ID or agent ID when available
- endpoint-specific identifiers such as export config ID

The combined key is hashed before storage in the in-memory limiter.

## Tuning

Environment variables:

- `AGENTGATE_RATE_LIMIT_ENABLED`
- `AGENTGATE_RATE_LIMIT_LOGIN_LIMIT`
- `AGENTGATE_RATE_LIMIT_LOGIN_WINDOW_SECONDS`
- `AGENTGATE_RATE_LIMIT_OIDC_LIMIT`
- `AGENTGATE_RATE_LIMIT_OIDC_WINDOW_SECONDS`
- `AGENTGATE_RATE_LIMIT_GATEWAY_LIMIT`
- `AGENTGATE_RATE_LIMIT_GATEWAY_WINDOW_SECONDS`
- `AGENTGATE_RATE_LIMIT_APPROVAL_LIMIT`
- `AGENTGATE_RATE_LIMIT_APPROVAL_WINDOW_SECONDS`
- `AGENTGATE_RATE_LIMIT_AUDIT_EXPORT_LIMIT`
- `AGENTGATE_RATE_LIMIT_AUDIT_EXPORT_WINDOW_SECONDS`
- `AGENTGATE_RATE_LIMIT_RETENTION_LIMIT`
- `AGENTGATE_RATE_LIMIT_RETENTION_WINDOW_SECONDS`

## Response shape

When throttled, AgentGate returns:

- HTTP `429`
- error code `rate_limited`
- a generic detail string
- `request_id`
- `Retry-After`

For authenticated privileged endpoints, serious throttling is also written as a tenant-scoped audit event.

## Current limitations

- no shared limiter across multiple API replicas yet
- no Redis backend yet
- no proxy-aware client IP trust model yet
- no per-API-key custom policy yet
