# Architecture

## Overview

AgentGate is designed as an agent runtime control plane. The backend sits between agents and enterprise tools, evaluating each tool call against:

- Caller identity
- Tenant ownership
- Agent state and configured scope
- Deterministic intent heuristics
- Deterministic risk scoring
- Enabled tenant policies
- Human approval rules

The frontend is a separate admin console for security reviewers, admins, and platform operators.

Authentication now has two parallel operator entry paths:

- Local email/password login for development and bootstrap workflows
- Optional tenant-scoped OIDC browser login for enterprise SSO

## Runtime Flow

`POST /v1/gateway/tool-call`

1. Authenticate caller with JWT or agent API key.
2. Resolve tenant from user or API key.
3. Load agent and tool inside that tenant boundary.
4. Verify agent status, tool status, and allowed scopes.
5. Create or attach an execution trace.
6. Run deterministic intent analysis.
7. Run baseline risk scoring.
8. Evaluate enabled policies against the runtime context.
9. Recompute risk with matched policy severity.
10. Apply built-in fail-closed guardrails for critical uncertainty.
11. Protect sensitive execution arguments before persisting `ToolCall` state.
12. Persist `ToolCall`, `AuditEvent`, and trace steps using sanitized response-facing payload views.
13. If required, create `ApprovalRequest`.
14. If approval is created and Slack notifications are enabled, create a tenant-scoped notification job and either run it inline or publish it for worker delivery.
15. If allowed and the adapter is supported in the current build, execute the tool immediately on the gateway path.
16. If approval is granted with `execute_now`, create a durable approved-execution job and either run it inline or hand it to the worker.
17. Expired protected execution payloads can later be redacted by a tenant-scoped retention purge job without decrypting them.
18. Tenant-scoped audit export jobs can later stream sanitized audit history to external SIEM destinations without replaying raw payloads or decrypted secrets.
19. If approval is pending, lock the trace until a reviewer resolves it.
20. Request middleware adds request IDs, structured logs, security headers, aggregate metrics, and endpoint-specific throttling around sensitive control-plane routes.

## Backend Modules

- `app/core`: settings, errors, enums, security, logging, networking, metrics
- `app/db`: engine, session, init, seed
- `app/models`: tenant-aware SQLAlchemy models
- `app/schemas`: API contracts
- `app/services`: auth, OIDC, gateway, audit, audit export, risk, policy, approvals, traces, notifications
- `app/jobs`: job dispatch entrypoints and worker routing
- `app/security`: payload encryption, key management, and secret-reference abstractions
- `app/notifications`: outbound notifier implementations such as Slack
- `app/tools`: execution adapter interfaces, registry, and mock adapters
- `app/api/routes`: HTTP interface

## Data Model

Primary entities:

- Tenant
- User
- Agent
- Tool
- Policy
- ToolCall
- ApprovalRequest
- AuditEvent
- ExecutionTrace
- TraceStep
- AgentAPIKey
- Job
- TenantOIDCConfig
- AuditExportConfig

Every business record is tenant-scoped, and every user-facing data access path filters by `tenant_id`.
`ToolCall.trace_id` is now a first-class foreign key so traces and decisions can be joined without relying on JSON payload inspection.
`ToolCall` also carries payload protection metadata so retention and purge flows can evolve without changing the core execution model.
`Job` is the durable async workflow record for approval notifications, approved execution, retention purge, and audit export work.
`TenantOIDCConfig` is the tenant-scoped SSO entrypoint record and stores issuer/client metadata without storing raw client secrets.
`AuditExportConfig` is the tenant-scoped destination record that stores export endpoint metadata, filters, cursor checkpoints, and non-sensitive last-run state without storing raw tokens.

## OIDC Authentication Flow

1. The login page checks `GET /v1/auth/oidc/{tenant_slug}/config-status`.
2. If a tenant has an enabled OIDC config, the browser is redirected to `GET /v1/auth/oidc/{tenant_slug}/login`.
3. AgentGate creates a signed `state` token, includes a nonce, and redirects to the provider authorization endpoint.
4. The provider redirects back to `GET /v1/auth/oidc/{tenant_slug}/callback`.
5. AgentGate validates the callback state and tenant binding, exchanges the code through the provider abstraction, validates identity claims, checks allowed email domains, and provisions or updates the tenant user.
6. AgentGate creates a short-lived exchange ticket and redirects the browser back to the web login page.
7. The frontend redeems that ticket at `POST /v1/auth/oidc/exchange` and then proceeds with the normal AgentGate JWT session model.

## Approval and Trace Semantics

- A trace can move from `running` to `pending_approval` when a step requires review.
- While a trace is pending approval, the gateway rejects new steps for that trace to avoid decision races or hidden execution after a pause.
- Approval decisions move the trace back to `running`, `completed`, `blocked`, or `failed` depending on whether execution resumes, is queued, succeeds, or fails.
- Approval notifications are durable jobs. Slack delivery success, failure, and retry exhaustion are written as tenant-scoped audit events and never change the underlying approval decision.
- Sensitive execution arguments remain decryptable only inside trusted backend execution paths such as immediate adapter execution and approved execution replay.
- Audit export runs are also durable jobs. They operate on already-sanitized `AuditEvent` rows and keep a per-destination cursor on `AuditExportConfig` so multiple tenant destinations can export independently.

## Adapter Boundary

- `app/tools/base.py` defines the execution request and adapter interface.
- `app/tools/registry.py` resolves the adapter responsible for a tool execution request.
- `app/tools/mock_adapter.py` contains the local demo adapters.
- `app/tools/github_adapter.py` is the first real production-style connector and uses environment-backed credentials for development.
- Real REST, MCP, database, or internal enterprise connectors should plug into this layer rather than extend gateway business logic directly.
- Slack notifications intentionally sit outside the tool adapter layer because they are platform-side governance notifications, not agent-executable tools.

## Payload Protection Boundary

- `ToolCall.request_payload.arguments` is a sanitized operator-facing summary.
- `ToolCall.request_payload.execution_arguments` stores protected field-level envelopes for sensitive values.
- Protected envelopes now include `key_ref`, `key_version`, `provider`, and creation metadata so future rotation and rewrap workflows can reason about historical ciphertext safely.
- Retention classes currently include `standard`, `short_lived`, `extended`, and `legal_hold`.
- Purge replaces expired `execution_arguments` with a non-sensitive tombstone marker and updates `payload_redaction_status` to preserve operator visibility without preserving replayable secrets.
- Trusted execution paths decrypt those envelopes only when an adapter actually needs the original value.
- Tool-call list responses, approvals, traces, audit feeds, and Slack notifications never expose decrypted values or raw envelope internals.

## Key And Secret Management

- The current build uses an env-backed key provider for payload protection and a shared secret-reference resolver for GitHub, Slack, and OIDC secrets.
- Supported secret reference syntax today is `env:NAME` or a bare environment variable name where a legacy env-var field already exists.
- Placeholder reference types such as `secret_ref:` and `vault:` are parsed and fail closed until a real external resolver is wired in.
- `GET /v1/security/key-status` exposes provider type, active key ref, configured purposes, and warnings without exposing raw key material.
- Rotation scaffolding supports an active key plus additional decrypt-only key refs so new payloads can encrypt with the active key while old envelopes remain decryptable by `key_ref`.

## Audit Export Boundary

- `AuditEvent.metadata_json` is sanitized on write and sanitized again before export.
- Export payloads never include decrypted execution arguments, raw secrets, or payload-protection envelope internals.
- Each `AuditExportConfig` maintains its own `(last_exported_at, last_exported_event_id)` cursor so multiple destinations per tenant do not interfere with one another.
- Export severity filters are derived at export time from audit metadata or event-type heuristics. This preserves backward compatibility with the existing audit schema while still supporting SIEM routing filters.
- Destination credentials resolve through the shared secret-reference layer and are never returned in APIs, audit records, trace data, or dashboard responses.

## Frontend Architecture

The Next.js app uses:

- Client-side session storage for development JWT auth
- Optional OIDC discovery on the login page, with callback ticket redemption before normal session hydration
- Typed API client in `apps/web/lib/api.ts`
- Shared `PageShell` layout for protected pages
- Operational views for dashboard, approvals, traces, audit history, and audit export status

This UI is intentionally admin-console oriented rather than consumer-chat oriented.

## Deployment Foundation

- PostgreSQL is the primary database target.
- Redis is optional and now acts as an accelerator for job publication and worker wakeups. The jobs table remains the durable source of truth.
- `/metrics` exposes safe aggregate counters and gauges in Prometheus text format.
- `/ready` now reports safe status for database connectivity, jobs, key management, and selected integration/config checks.
- Dockerfiles exist for API and web.
- `docker-compose.yml` provisions API, worker, web, Postgres, and Redis.
- Retention purge is queue-backed, but the current build still expects operators to enqueue it explicitly through the API rather than through a built-in scheduler.
- Audit export is queue-backed and tenant-scoped. Operators can trigger it manually today or schedule `POST /v1/audit-exports/{id}/run` externally.
- OIDC callback validation expects `AGENTGATE_PUBLIC_API_URL` to match the externally reachable API origin.
- Key management currently expects `AGENTGATE_KEY_PROVIDER=env`; cloud KMS providers are documented future paths, not active implementations.

## Extension Points

- Replace deterministic intent heuristics with an additional ML or LLM evaluator behind the same interface.
- Add real REST, MCP, SaaS, and internal connector adapters beyond the mock executor.
- Extend the current audit export foundation with managed destination health checks, dead-letter handling, signed destination verification, and immutable archival guarantees.
- Replace environment-scoped Slack configuration with tenant-managed integration records backed by a secret manager or KMS.
- Replace the env key provider with AWS KMS, GCP KMS, Azure Key Vault, or HashiCorp Vault adapters once operational dependencies and rotation workflows are ready.
- Extend the OIDC foundation with tenant-managed admin APIs/UI, external secret resolvers, and eventually SAML or SCIM if required by deployment targets.
- Replace the built-in worker loop with a dedicated distributed runner such as Celery, RQ, Arq, or BullMQ if the deployment requires stronger orchestration guarantees.
