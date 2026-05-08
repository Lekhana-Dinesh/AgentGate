# Rate Limiting

## Goal

AgentGate includes an abuse-protection layer for sensitive control-plane endpoints that works in two modes:

- `in_memory` for local development and tests
- `redis` for multi-instance and production deployments

The implementation preserves the existing route-level limiter hooks and keeps local setup light while allowing a production-safe distributed provider.

## Provider selection

Environment variables:

- `AGENTGATE_RATE_LIMIT_PROVIDER=in_memory|redis`
- `AGENTGATE_REDIS_URL=redis://...`
- `AGENTGATE_RATE_LIMIT_ENABLED=true|false`
- `AGENTGATE_ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true|false`
- `AGENTGATE_RATE_LIMIT_FAIL_OPEN_ON_BACKEND_ERROR=true|false`

Behavior:

- `development` and `test`
  - rate limiting is disabled by default unless explicitly enabled
  - `in_memory` is the default provider
- production-like environments
  - rate limiting is enabled by default unless explicitly disabled
  - `redis` is the expected provider for multi-instance safety
  - `in_memory` is rejected unless `AGENTGATE_ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true`
  - if `AGENTGATE_RATE_LIMIT_PROVIDER=redis`, `AGENTGATE_REDIS_URL` is required at startup

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
- `POST /v1/jobs/{job_id}/retry`
- `POST /v1/audit-integrity/verify`
- `POST /v1/audit-integrity/backfill`

## Algorithm

- Provider algorithm: fixed-window counters
- Redis implementation: per-window hashed keys with atomic `INCR` + `EXPIRE` + `TTL` in a transactional pipeline
- In-memory implementation: process-local deque window tracking

Redis key shape is namespaced and hashed before storage. Raw email addresses, tenant slugs, user IDs, agent IDs, or tokens are not stored as plaintext Redis keys.

## Keying model

Rate-limit keys use combinations of:

- client IP
- tenant ID or tenant slug when available
- user ID or agent ID when available
- endpoint-specific identifiers such as export config ID, job ID, or integrity action

The combined key is normalized and hashed before storage in either provider.

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
- `AGENTGATE_RATE_LIMIT_JOBS_RETRY_LIMIT`
- `AGENTGATE_RATE_LIMIT_JOBS_RETRY_WINDOW_SECONDS`
- `AGENTGATE_RATE_LIMIT_AUDIT_INTEGRITY_LIMIT`
- `AGENTGATE_RATE_LIMIT_AUDIT_INTEGRITY_WINDOW_SECONDS`

## Response shape

When throttled, AgentGate returns:

- HTTP `429`
- error code `rate_limited`
- a generic detail string
- `request_id`
- `Retry-After`

For authenticated privileged endpoints, serious throttling is also written as a tenant-scoped audit event.

## Redis failure behavior

- default behavior is fail-closed on backend errors for protected scopes
- if the Redis-backed limiter cannot be reached, protected endpoints return a safe `503 rate_limiter_unavailable`
- `GET /ready` reports Redis-backed limiter health without exposing the Redis URL or credentials
- `AGENTGATE_RATE_LIMIT_FAIL_OPEN_ON_BACKEND_ERROR=true` exists as an escape hatch, but it should only be used deliberately in low-risk or isolated environments

## Metrics

`GET /metrics` includes safe aggregate limiter metrics:

- `agentgate_rate_limit_requests_total{provider,scope,outcome}`
- `agentgate_rate_limit_backend_errors_total{provider,scope}`
- `agentgate_rate_limit_exceeded_total{provider,scope}`

No limiter keys, tenant IDs, user IDs, raw IPs, or secret material are exposed.

## Limitations

- the Redis implementation is fixed-window, not sliding-window or token-bucket
- client IP handling is not yet proxy-trust-aware
- the built-in implementation assumes a single Redis endpoint and does not yet include Sentinel or Cluster-specific behavior
- no per-API-key custom policy yet
