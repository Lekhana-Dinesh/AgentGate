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
- Tenant-scoped user lifecycle management for deactivation/reactivation without replacing the existing JWT or OIDC flows

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
13. Link the new audit event into the tenant-scoped audit hash chain using canonical sanitized content.
14. If required, create `ApprovalRequest`.
15. If approval is created and Slack notifications are enabled, create a tenant-scoped notification job and either run it inline or publish it for worker delivery.
16. If allowed and the adapter is supported in the current build, execute the tool immediately on the gateway path.
17. Worker-mode jobs are claimed with explicit lease ownership so two workers do not intentionally execute the same due row at once.
18. If approval is granted with `execute_now`, create a durable approved-execution job and either run it inline or hand it to the worker.
19. Expired protected execution payloads can later be redacted by a tenant-scoped retention purge job without decrypting them.
20. Tenant-scoped audit export jobs can later stream sanitized audit history plus safe integrity metadata to external SIEM destinations without replaying raw payloads or decrypted secrets.
21. Tenant-scoped audit-integrity checkpoint jobs can verify anchored chain continuity, summarize a safe integrity range, and write an external checkpoint document to a configured anchor destination.
22. Stale `running` jobs can be requeued safely or moved to dead-letter review depending on job type and retry policy.
23. If approval is pending, lock the trace until a reviewer resolves it.
24. Request middleware adds request IDs, structured logs, security headers, aggregate metrics, and endpoint-specific throttling around sensitive control-plane routes using either local in-memory windows or Redis-backed distributed counters.

## Backend Modules

- `app/core`: settings, errors, enums, security, logging, networking, metrics
- `app/db`: engine, session, init, seed
- `app/models`: tenant-aware SQLAlchemy models
- `app/audit`: audit hash canonicalization and chain-linking helpers
- `app/schemas`: API contracts
- `app/services`: auth, user lifecycle, OIDC, gateway, audit, audit integrity, audit export, audit checkpointing, risk, policy, approvals, traces, notifications, scheduled tasks, settings overview
- `app/jobs`: job dispatch entrypoints and worker routing
- `app/security`: payload encryption, key management, secret-reference abstractions, and external audit-anchor adapters
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
- Worker
- TenantOIDCConfig
- AuditExportConfig
- AuditIntegrityCheckpoint

Every business record is tenant-scoped, and every user-facing data access path filters by `tenant_id`.
`ToolCall.trace_id` is now a first-class foreign key so traces and decisions can be joined without relying on JSON payload inspection.
`ToolCall` also carries payload protection metadata so retention and purge flows can evolve without changing the core execution model.
`Job` is the durable async workflow record for approval notifications, approved execution, retention purge, audit export, audit integrity verification, audit integrity checkpointing, and connector health checks. It now also carries lease ownership and terminal dead-letter reason fields.
`Worker` is the safe operational registry for worker identity, heartbeat, and stop state. It is infrastructure metadata, not tenant business data.
`ScheduledTask` is the tenant-scoped recurring enqueue record that stores safe schedule metadata, next-run state, last scheduler status, and non-secret config for recurring operational work.
`TenantOIDCConfig` is the tenant-scoped SSO entrypoint record and stores issuer/client metadata without storing raw client secrets.
`AuditExportConfig` is the tenant-scoped destination record that stores export endpoint metadata, filters, cursor checkpoints, and non-sensitive last-run state without storing raw tokens.
`AuditEvent` now also carries optional tenant-scoped integrity fields such as `event_hash`, `previous_event_hash`, `chain_scope`, `sequence_number`, and `anchored_at` so new audit evidence can be verified later without exposing payload secrets.
`AuditIntegrityCheckpoint` is the tenant-scoped checkpoint record for externally anchored audit ranges. It stores range boundaries, checkpoint hashes, external destination references, status, and safe metadata only.
`User` now also carries lifecycle metadata for `provisioned_source`, `deactivated_at`, and `deactivation_reason`. Active versus deactivated state continues to flow through `is_active`, so existing auth and gateway checks fail closed without a separate session store rewrite.

## OIDC Authentication Flow

1. The login page checks `GET /v1/auth/oidc/{tenant_slug}/config-status`.
2. If a tenant has an enabled OIDC config, the browser is redirected to `GET /v1/auth/oidc/{tenant_slug}/login`.
3. AgentGate creates a signed `state` token, includes a nonce, and redirects to the provider authorization endpoint.
4. The provider redirects back to `GET /v1/auth/oidc/{tenant_slug}/callback`.
5. AgentGate validates the callback state and tenant binding, exchanges the code through the provider abstraction, validates identity claims, checks allowed email domains, and provisions or updates the tenant user.
6. AgentGate creates a short-lived exchange ticket and redirects the browser back to the web login page.
7. The frontend redeems that ticket at `POST /v1/auth/oidc/exchange` and then proceeds with the normal AgentGate JWT session model.
8. OIDC-provisioned or OIDC-bound users are marked with `provisioned_source=oidc`, and inactive users remain blocked even if role mapping would otherwise resolve to a privileged role.

## Identity Lifecycle Flow

1. Owner or admin lists tenant users through `GET /v1/users`, while security reviewers have view-only access.
2. Owner or admin can safely update non-secret user profile fields through `PATCH /v1/users/{user_id}`.
3. Deactivation at `POST /v1/users/{user_id}/deactivate` flips `is_active` false, records lifecycle metadata, revokes agent API keys created by that user, and writes a tenant-scoped audit event.
4. Existing JWTs become unusable on the next request because current-user resolution reloads the user row and rejects inactive accounts.
5. Reactivation at `POST /v1/users/{user_id}/reactivate` restores account activity without restoring previously revoked API keys.
6. The last active owner cannot be demoted or deactivated, preventing tenant self-lockout.

## Approval and Trace Semantics

- A trace can move from `running` to `pending_approval` when a step requires review.
- While a trace is pending approval, the gateway rejects new steps for that trace to avoid decision races or hidden execution after a pause.
- Approval decisions move the trace back to `running`, `completed`, `blocked`, or `failed` depending on whether execution resumes, is queued, succeeds, or fails.
- Approval notifications are durable jobs. Slack delivery success, failure, and retry exhaustion are written as tenant-scoped audit events and never change the underlying approval decision.
- Worker-mode jobs now use explicit lease ownership and stale recovery. Safe retryable jobs can be requeued after lease expiry, while non-idempotent approved execution jobs are moved to terminal operator review instead of being replayed automatically.
- Sensitive execution arguments remain decryptable only inside trusted backend execution paths such as immediate adapter execution and approved execution replay.
- Audit export runs are also durable jobs. They operate on already-sanitized `AuditEvent` rows and keep a per-destination cursor on `AuditExportConfig` so multiple tenant destinations can export independently.
- Audit integrity verification and backfill are privileged tenant-scoped operator workflows. They validate or rebuild chain metadata on already-sanitized audit rows without exposing raw payload content.
- Audit checkpointing is also a privileged tenant-scoped operator workflow. It verifies the target anchored range first, computes a deterministic checkpoint hash from safe integrity metadata, and then writes a checkpoint document to the configured local or object-storage anchor.
- The built-in scheduler is a separate polling loop that claims due `ScheduledTask` rows, enqueues the appropriate durable job through existing job handlers, advances `next_run_at`, and records scheduler audit events.

## Adapter Boundary

- `app/tools/base.py` defines the execution request and adapter interface.
- `app/tools/registry.py` resolves the adapter responsible for a tool execution request.
- `app/tools/mock_adapter.py` contains the local demo adapters.
- `app/tools/github_adapter.py` is the first real production-style connector and supports env-token local auth plus GitHub App installation-token auth through a separate auth-provider boundary.
- Real REST, MCP, database, or internal enterprise connectors should plug into this layer rather than extend gateway business logic directly.
- Slack notifications intentionally sit outside the tool adapter layer because they are platform-side governance notifications, not agent-executable tools.
- GitHub App auth lives behind the connector auth-provider boundary so installation-token exchange, caching, and refresh do not bypass gateway policy, audit, or approval semantics.

## Payload Protection Boundary

- `ToolCall.request_payload.arguments` is a sanitized operator-facing summary.
- `ToolCall.request_payload.execution_arguments` stores protected field-level envelopes for sensitive values.
- Protected envelopes now include `key_ref`, `key_version`, `provider`, and creation metadata so future rotation and rewrap workflows can reason about historical ciphertext safely. AWS KMS-backed envelopes additionally carry a wrapped per-envelope data key.
- Retention classes currently include `standard`, `short_lived`, `extended`, and `legal_hold`.
- Purge replaces expired `execution_arguments` with a non-sensitive tombstone marker and updates `payload_redaction_status` to preserve operator visibility without preserving replayable secrets.
- Trusted execution paths decrypt those envelopes only when an adapter actually needs the original value.
- Tool-call list responses, approvals, traces, audit feeds, and Slack notifications never expose decrypted values or raw envelope internals.

## Key And Secret Management

- The current build uses a provider-selected payload-protection key path: `env` for local/dev simplicity and `aws_kms` for production-minded envelope encryption.
- AWS KMS mode uses KMS-generated data keys for payload protection while keeping the payload ciphertext local and symmetric.
- Supported secret reference syntax today is `env:NAME` or a bare environment variable name where a legacy env-var field already exists.
- GitHub connector auth uses the same secret-reference layer for `token_env_var`, `private_key_env_var`, and `private_key_secret_ref`. GitHub App installation tokens are cached in memory only and are never written to the database.
- Placeholder reference types such as `secret_ref:` and `vault:` are parsed and fail closed until a real external resolver is wired in.
- `GET /v1/security/key-status` exposes provider type, provider readiness, active key ref, configured purposes, AWS region when applicable, and warnings without exposing raw key material.
- Rotation scaffolding supports an active key plus additional decrypt-only env key refs so new payloads can encrypt with the active provider while legacy env envelopes remain decryptable by `key_ref`.

## Audit Export Boundary

- `AuditEvent.metadata_json` is sanitized on write and sanitized again before export.
- Audit events are chained per tenant using canonical sanitized content rather than raw request bodies, decrypted payloads, or secret material.
- Export payloads never include decrypted execution arguments, raw secrets, or payload-protection envelope internals.
- Export payloads can include safe integrity metadata such as `event_hash`, `previous_event_hash`, `sequence_number`, and `hash_algorithm`.
- Checkpoint documents use safe integrity metadata only and do not include decrypted payloads, raw secrets, or unsafe audit-event metadata bodies.
- Each `AuditExportConfig` maintains its own `(last_exported_at, last_exported_event_id)` cursor so multiple destinations per tenant do not interfere with one another.
- Export severity filters are derived at export time from audit metadata or event-type heuristics. This preserves backward compatibility with the existing audit schema while still supporting SIEM routing filters.
- Destination credentials resolve through the shared secret-reference layer and are never returned in APIs, audit records, trace data, or dashboard responses.

## Frontend Architecture

The Next.js app uses:

- Client-side session storage for development JWT auth
- Optional OIDC discovery on the login page, with callback ticket redemption before normal session hydration
- Typed API client in `apps/web/lib/api.ts`
- Shared `PageShell` layout for protected pages
- Operational views for dashboard, approvals, traces, audit history, audit export status, and safe admin settings status
- A minimal `/users` operator page for user role, status, provisioning source, and deactivation/reactivation actions

This UI is intentionally admin-console oriented rather than consumer-chat oriented.

## Deployment Foundation

- PostgreSQL is the primary database target.
- Redis is optional for local development and expected for multi-instance production rate limiting. It also acts as an accelerator for job publication and worker wakeups. The jobs table remains the durable source of truth.
- Worker heartbeat is recorded in the primary datastore and exposed through safe `/v1/workers` APIs. Running jobs use explicit lease ownership rather than best-effort process-local execution only.
- `/metrics` exposes safe aggregate counters and gauges in Prometheus text format.
- `/ready` now reports safe status for database connectivity, jobs, scheduler config, key management, selected integration/config checks, and the configured rate-limit provider.
- `GET /v1/settings/overview` now composes a tenant-authenticated, read-only operator summary for tenant profile state plus safe global control-plane health such as keys and rate limiting without exposing secrets.
- Dockerfiles exist for API and web.
- `docker-compose.yml` provisions API, worker, web, Postgres, and Redis.
- Retention purge, audit export, audit integrity verification, audit integrity checkpointing, and simple connector health checks can now be scheduled through tenant-scoped `ScheduledTask` rows and the built-in `python -m app.scheduler` loop.
- The scheduler loop is intentionally simple: it is UTC-oriented, poll-based, and overlap-avoiding. External cron or orchestration can still drive the same APIs if stronger control is required.
- OIDC callback validation expects `AGENTGATE_PUBLIC_API_URL` to match the externally reachable API origin.
- Key management supports `AGENTGATE_KEY_PROVIDER=env` and `AGENTGATE_KEY_PROVIDER=aws_kms`. The env provider remains the default local path, while AWS KMS adds production-minded envelope-encryption support without changing the payload-protection boundary.
- External audit checkpoint anchoring supports a local development path plus an S3-compatible object-storage path. Strong immutability claims still depend on destination-side WORM controls such as S3 Object Lock.

## Extension Points

- Replace deterministic intent heuristics with an additional ML or LLM evaluator behind the same interface.
- Add real REST, MCP, SaaS, and internal connector adapters beyond the mock executor.
- Extend the current audit export and audit checkpoint foundations with managed destination health checks, dead-letter handling, signed destination verification, and stronger external immutable evidence options.
- Replace environment-scoped Slack configuration with tenant-managed integration records backed by a secret manager or KMS.
- Add additional key providers such as GCP KMS, Azure Key Vault, or HashiCorp Vault once operational dependencies and rotation workflows are ready.
- Extend the OIDC and identity lifecycle foundations with tenant-managed admin APIs/UI for OIDC config, external secret resolvers, and eventually a full SCIM HTTP surface or SAML if required by deployment targets.
- Replace the built-in worker and scheduler loops with a dedicated distributed runner such as Celery, RQ, Arq, or BullMQ if the deployment requires stronger orchestration guarantees.
