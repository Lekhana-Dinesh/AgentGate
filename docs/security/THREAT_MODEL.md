# Threat Model

## Purpose And Scope

This document is the formal threat model for AgentGate as it exists in this repository today.
It focuses on the runtime control plane, not on hypothetical future platform components that are not implemented yet.

Use this document together with:

- [Security Overview](../SECURITY.md)
- [Audit Integrity](audit-integrity.md)
- [External Audit Anchoring](external-audit-anchoring.md)
- [Payload Protection](payload-protection.md)
- [Key And Secret Management](key-and-secret-management.md)
- [SSO And OIDC](sso-oidc.md)
- [Retention And Purge](retention-and-purge.md)
- [Jobs And Workers](../operations/jobs-and-workers.md)
- [Audit Export](../integrations/audit-export.md)
- [Deployment Hardening](../operations/deployment-hardening.md)

## System Summary

AgentGate sits between AI agents and real tools.
Its core security promise is not "the model will always behave safely."
Its promise is that tool use is routed through a governed runtime path that can authenticate the caller, enforce tenant scope, score risk, apply policy, require approval, sanitize stored payloads, and emit audit evidence before execution.

## Assets

The highest-value assets in scope are:

- Tenant-scoped business objects such as agents, tools, approvals, tool calls, jobs, audit events, and traces
- Authentication material including JWT signing secrets, API keys, OIDC exchange tickets, and session-related artifacts
- Connector credentials and secret references for GitHub, Jira, MCP, Slack, OIDC, and audit export destinations
- Protected execution payloads, especially `request_payload.execution_arguments`
- Policy definitions, risk signals, intent classifications, and approval decisions
- Audit logs, traces, job records, export cursors, and audit checkpoint records that support investigation and accountability
- Payload-encryption keys and key metadata such as `key_ref` and `key_version`
- Deployment configuration, CORS settings, public URLs, rate-limit settings, and worker mode configuration

## Actors

Expected actors:

- AgentGate tenant users such as owners, admins, reviewers, developers, and viewers
- Human approvers making allow or reject decisions
- AI agents or applications calling the gateway with user or service credentials
- Platform operators running the API, worker, database, and deployment environment
- External identity providers used for tenant-scoped OIDC
- External services such as GitHub, Jira, MCP servers, Slack, audit export destinations, and external audit-checkpoint storage

## Attacker Types

Relevant attacker types:

- A malicious or compromised end user inside a tenant
- A malicious or compromised AI agent acting with legitimate credentials
- An external attacker with stolen credentials or network access
- A tenant attempting to read, influence, or disrupt another tenant
- A compromised connector destination or untrusted upstream content source
- A malicious insider with deployment, database, or secret access
- A downstream audit destination that is misconfigured, hostile, or over-privileged

## Trust Boundaries

Major trust boundaries in the current design:

1. Browser, agent, or client application to the public AgentGate API
2. AgentGate API process to the database and durable job store
3. API process to worker process when execution is deferred
4. AgentGate to external identity providers during OIDC login
5. AgentGate to external connectors such as GitHub, Jira, MCP servers, and Slack
6. AgentGate to downstream audit export destinations
7. Application code to deployment-provided secrets and encryption keys

Crossing one of these boundaries should be treated as a potential point for spoofing, tampering, disclosure, or availability abuse.

## Data Flows

### 1. Local login

1. User submits `email`, `password`, and `tenant_slug` to `POST /v1/auth/login`.
2. AgentGate validates tenant and user state, checks the password hash, and issues a JWT.
3. Request and auth events are logged and audited without logging the password.

### 2. OIDC login

1. Browser starts tenant-scoped login through the OIDC login route.
2. AgentGate creates signed state and nonce values and redirects to the provider.
3. Provider returns to the callback route.
4. AgentGate validates state, tenant binding, issuer, audience, email domain, and role mapping.
5. AgentGate creates or updates the tenant user and returns a short-lived exchange ticket.
6. Frontend redeems that ticket for the normal AgentGate JWT.

### 3. Gateway decision and execution

1. Client submits a tool-call request to `POST /v1/gateway/tool-call`.
2. AgentGate authenticates the caller and resolves tenant, user, agent, and tool scope.
3. Intent, risk, policy, and approval requirements are evaluated.
4. Sensitive execution arguments are protected before persistence.
5. Tool call, audit event, trace data, and operator-safe views are stored.
6. If allowed, the adapter executes through the governed connector path.
7. If approval is required, execution pauses and resumes only after an approval decision.

### 4. Approval and async execution

1. Approval decision is written through the approval workflow.
2. Job rows are created for Slack notification, approved execution, retention purge, or audit export as needed.
3. Inline mode executes after commit in-process.
4. Worker mode executes later from the durable jobs table.

### 5. Retention purge

1. Privileged caller requests a purge dry-run or real purge.
2. AgentGate creates a durable retention job.
3. Purge logic redacts expired protected payloads without decrypting them.
4. Future approved execution fails closed if a required payload was already purged.

### 6. Audit export

1. Privileged caller configures a tenant-scoped destination.
2. Export run is triggered manually today.
3. AgentGate reads sanitized audit events, re-sanitizes metadata, and sends only safe aggregates to the destination.
4. Per-destination cursors prevent duplicate export on later runs.

### 7. Audit checkpoint anchoring

1. Privileged caller requests a checkpoint.
2. AgentGate enqueues a durable checkpoint job.
3. The job verifies chain continuity for the targeted anchored range.
4. AgentGate computes a deterministic checkpoint hash from safe integrity metadata only.
5. AgentGate stores the checkpoint record and writes a checkpoint document to the configured anchor destination.
6. Later verification can compare the current database state to that external checkpoint document.

## Abuse Cases

Representative abuse cases for this platform:

- An agent tries to exfiltrate internal data by posting it to a public GitHub issue or comment
- A prompt injection hidden in GitHub content or a ticket body convinces the agent to call a different tool than intended
- A tenant user attempts cross-tenant object access by guessing IDs or reusing another tenant's token
- A compromised reviewer approves a dangerous action that should have been rejected
- An attacker floods login, OIDC, gateway, approval, export, or purge endpoints to degrade availability
- A connector configuration attempts to bypass adapter safety by using raw tokens or destructive actions
- A worker replays or duplicates an approved execution and causes duplicate side effects
- A private or malicious audit export endpoint is configured to siphon data or trigger SSRF-like behavior
- A deployment operator accidentally exposes secrets through `.env`, logs, metrics, or screenshots
- A compromised IdP claim mapping grants a broader role than intended

## STRIDE-Style Analysis

### Spoofing

Threats:

- Stolen JWTs or API keys used to impersonate users or agents
- Forged or replayed OIDC login responses
- A caller pretending to act for a different tenant, user, or agent

Mitigations already implemented:

- JWT auth and tenant-aware auth resolution
- API keys are hashed at rest and checked for revocation, scope, and expiry
- OIDC state signing, nonce handling, tenant binding, domain checks, and exchange-ticket handoff
- Role mapping does not auto-grant `owner` unless explicitly mapped

Remaining risk:

- Local email/password auth still exists beside OIDC
- No signed client requests or mTLS model for service callers yet
- Only a minimal SCIM Users foundation exists; there is no broader identity-governance or stronger centralized deprovisioning flow yet

### Tampering

Threats:

- Modification of tool calls, approvals, jobs, audit events, or export cursors
- Malicious tool configuration intended to bypass connector safety
- Runtime payload alteration before execution or after approval

Mitigations already implemented:

- Central gateway path for auth, policy, risk, audit, trace, and approval
- Adapter-level blocking of unknown or destructive GitHub actions
- Protected payload storage with envelope metadata and trusted-path decryption only
- Tenant-scoped tamper-evident audit hashing on sanitized `AuditEvent` content
- Tenant-scoped checkpoint hashing and external anchor document writing for verified audit ranges
- Tenant-scoped jobs with idempotency keys and single-attempt GitHub writes

Remaining risk:

- External checkpoint anchoring now exists, but there is still no built-in notarization service and no valid immutability claim unless the destination itself enforces WORM or Object Lock semantics
- No database row-level security policies at the database layer yet
- Operators with direct database access remain high-trust actors

### Repudiation

Threats:

- A user or agent denies having triggered an action
- A reviewer denies approving a tool execution
- An operator cannot prove whether an export or purge happened

Mitigations already implemented:

- Audit events for gateway and approval actions
- Trace capture and replay references
- Request IDs, structured logs, and job records
- Approval decisions persist with tenant context and operator-safe metadata
- Audit integrity endpoints can verify tenant-scoped chain continuity and detect later mutation or deletion of anchored events
- External checkpoint verification can compare the current tenant-scoped audit range to a previously anchored external checkpoint document

Remaining risk:

- External checkpoints can now survive compromise of the primary database if the destination remains trustworthy
- There is still no guaranteed immutable external sink unless the destination uses WORM or Object Lock semantics
- No cryptographic signing of approvals or audit records yet

### Information Disclosure

Threats:

- Secrets leaked through logs, audit export, traces, Slack, metrics, or docs
- Protected execution payloads exposed through APIs or screenshots
- Cross-tenant data exposure through missing filters or job bugs

Mitigations already implemented:

- Sensitive execution arguments are field-level protected before persistence
- Public APIs, UI views, audit export, traces, and Slack use sanitized payload summaries only
- Request logs avoid request bodies and include safe error codes only
- Metrics and readiness expose aggregate, non-secret operational data
- Audit export blocks encrypted envelope internals, decrypted payloads, and raw credentials

Remaining risk:

- Payload keys are environment-scoped, not tenant-scoped
- Downstream SIEM or webhook destinations can still over-retain sanitized data
- Environment-variable secret handling is still part of the deployment trust model

### Denial Of Service

Threats:

- Brute-force login attacks
- Gateway flooding to consume CPU, database, or approval capacity
- Export or retention abuse by privileged callers
- Worker backlog, stuck jobs, or repeated transient upstream failures

Mitigations already implemented:

- Endpoint rate limiting on login, OIDC, gateway, approval, audit export, retention, jobs retry, and audit integrity routes
- Explicit upstream timeouts and bounded retries for safe reads only
- Durable jobs with worker and inline modes
- Worker heartbeat, explicit job leases, and stale-running recovery for safe retryable job types
- Readiness, health, metrics, and structured logging foundations

Remaining risk:

- Rate limiting supports Redis-backed distributed enforcement with in-memory local fallback
- No lease-renewal mechanism or external dead-letter queue yet
- No production autoscaling or load-test evidence is built in

### Elevation Of Privilege

Threats:

- OIDC role mapping grants excessive roles
- A user reaches admin-only or reviewer-only routes
- An agent or API key is used outside intended scope
- Approval or connector paths bypass central governance

Mitigations already implemented:

- RBAC on sensitive endpoints
- Tenant-aware auth and per-role access checks
- API key scope, revocation, and expiration checks
- Gateway decisions always go through auth, risk, policy, audit, trace, and approval

Remaining risk:

- Local auth increases attack surface in deployments that want SSO-only posture
- No per-key IP allowlisting or signed service-to-service request scheme yet

## Agent-Specific Risks

The system assumes agents are fallible and sometimes adversarial from a control perspective.

Agent-specific risks include:

- The agent misunderstands the user intent and chooses the wrong tool
- The agent correctly understands the task but takes an unnecessarily risky action
- The agent follows malicious instructions from untrusted content
- The agent uses approved tools to exfiltrate data in small sanitized-looking chunks
- The agent spams approval queues or creates operational fatigue

Current design response:

- Intent, risk, policy, and approval checks are independent of the model's confidence
- Risk and policy can route public or high-risk actions to human approval
- Connector adapters still enforce their own allowlists and destructive-action blocks

Remaining risk:

- AgentGate governs execution, not model reasoning
- A clever agent can still chain many individually low-risk actions
- Reviewer fatigue remains an operational risk if policy tuning is weak

## Prompt Injection Risks

Representative risks:

- GitHub issue or PR text includes hidden instructions that redirect the agent
- Untrusted tool output poisons future prompts or retrieved context
- A user pastes attacker-controlled content that causes a tool call with the wrong data classification

Mitigations already implemented:

- Runtime governance does not trust the agent alone to authorize tool use
- GitHub write actions still pass through policy, risk, approval, and trust classification
- Sensitive content fields can be protected or routed to approval based on tool and classification context

Remaining risk:

- Deterministic intent and risk checks are guardrails, not a full prompt-injection firewall
- There is no full model-content provenance system or per-step content isolation yet

## Tool Misuse Risks

Representative risks:

- Posting internal data to a public GitHub repository
- Repeated issue creation or comment spam
- Abusing allowed read actions to assemble sensitive internal state
- Using audit export or Slack as an exfiltration channel

Mitigations already implemented:

- GitHub connector supports only a small safe action set
- Destructive or unknown GitHub actions are blocked at the adapter layer
- Repository allowlists and trust classification influence policy
- Slack is outbound-only, optional, sanitized, and non-blocking
- Audit export sends sanitized events only and blocks private destinations unless explicitly allowed

Remaining risk:

- Connector scope is still only as strong as the deployed credentials
- Static trust lists can drift from enterprise source-of-truth data

## Tenant Isolation Risks

Representative risks:

- Cross-tenant record access by guessed IDs or copied credentials
- Background jobs processing data for the wrong tenant
- Shared export or connector state leaking another tenant's data

Mitigations already implemented:

- Business data is tenant-scoped by design
- Tenant-aware auth and query filtering are core architecture constraints
- Jobs, approvals, traces, audit exports, and payload retention records are tenant-scoped

Remaining risk:

- Database-layer row-level security is not implemented yet
- Multi-tenant isolation still depends on correct application-layer enforcement

## Secret Leakage Risks

Representative risks:

- Raw GitHub, Slack, OIDC, audit export, or payload-key secrets committed to the repo
- Secrets written into logs, metrics, traces, or audit exports
- Secrets persisted in connector or tenant config records

Mitigations already implemented:

- Shared secret-reference resolver with fail-closed behavior for unsupported refs
- Raw token-like GitHub config fields are rejected
- Request logging avoids request bodies
- Metrics, readiness, API views, and exports are sanitized
- Repo hygiene now includes secret scanning and a focused public-doc placeholder check
- Audit verification works on sanitized canonical data, so integrity checks do not require exposing raw secrets or decrypted payload content

Remaining risk:

- Environment variables remain a high-trust control plane for the current build
- Only AWS KMS is implemented today; broader external secret-manager and cloud-provider coverage is still missing

## Audit Tampering Risks

Representative risks:

- Deleting or modifying audit events after an incident
- Manipulating export cursors so events are skipped or replayed
- Suppressing traces or failing to correlate a request to a tool action

Mitigations already implemented:

- Gateway and approval flows emit audit and trace records
- Anchored audit events are linked into tenant-scoped hash chains with stored sequence numbers and previous-hash references
- Checkpoint documents summarize verified anchored ranges using safe integrity metadata only and can be written to S3-compatible object storage
- Export cursors are per-destination and explicit
- Request IDs and job records improve correlation

Remaining risk:

- External checkpointing improves evidence survival but still depends on destination controls and does not automatically provide immutability
- Fully privileged operators can still rewrite rows and recompute chain metadata inside the same trust boundary

## Job Execution Risks

Representative risks:

- Duplicate execution of non-idempotent actions
- Jobs stuck in running state without recovery
- Notification or export retries causing noise or backlog
- Worker compromise exposing decrypted execution arguments during trusted execution

Mitigations already implemented:

- Durable jobs table with tenant-scoped idempotency keys
- Worker identity, heartbeat visibility, and explicit lease ownership on running jobs
- Safe stale recovery can requeue retryable jobs while keeping non-idempotent approved execution out of blind replay
- Approved execution checks existing tool-call state
- GitHub writes stay single-attempt only
- Retention purge is idempotent and never decrypts payloads

Remaining risk:

- No lease renewal yet for genuinely long-running job types
- No separate external dead-letter queue or orchestrator-integrated replay workflow yet
- Trusted worker execution remains a sensitive runtime component

## Connector Risks

Representative risks:

- GitHub token abuse or repository scope overreach
- Upstream error confusion causing the wrong local decision
- Connector config drift causing trust misclassification

Mitigations already implemented:

- Narrow GitHub action allowlist
- Repository allowlist enforcement
- Structured upstream error mapping
- Explicit timeouts and read-only retries
- Write retry suppression to avoid duplicate mutations

Remaining risk:

- GitHub App private key resolution is still env-backed in this build
- No live enterprise repository trust synchronization yet

## OIDC And SSO Risks

Representative risks:

- State or nonce replay
- Domain bypass or weak role mapping
- Over-privileged default role behavior
- Local auth remaining enabled when a tenant wants SSO-only posture

Mitigations already implemented:

- Signed state, nonce handling, tenant binding, domain restrictions, JIT provisioning, and audited outcomes
- Explicit role mapping with no automatic `owner` assignment
- Public URL validation in stricter production config

Remaining risk:

- No SAML, broad SCIM identity-governance coverage, or strong centralized deprovisioning flow yet
- Tenant-admin CRUD for OIDC config is still limited

## Audit Export Risks

Representative risks:

- Exporting sanitized but still sensitive operational data to the wrong destination
- Leaking destination credentials
- Using export endpoints for SSRF or internal network probing
- Silent export drift or backlog leaving incident responders blind

Mitigations already implemented:

- Tenant-scoped export configs and per-destination cursors
- Credential references instead of raw tokens at rest
- Endpoint URL validation and private-destination blocking by default
- Safe retry behavior and non-sensitive dashboard status

Remaining risk:

- No signed webhook verification or destination-side handshake yet
- Built-in scheduling now exists, but there is still no separate external dead-letter queue or immutable archive

## Mitigations Already Implemented

Current major control families already in the product:

- Tenant-aware auth, RBAC, JWT auth, and optional tenant-scoped OIDC foundation
- Central gateway governance for auth, intent, risk, policy, approval, audit, and trace
- Protected payload storage with trusted-path decryption only
- Secret-reference resolution and production config hardening
- Async job durability with idempotency guardrails
- Audit export sanitization and destination safety validation
- Tenant-scoped tamper-evident audit chaining, verification, and safe integrity metadata export
- Structured request logging, readiness checks, metrics, security headers, and rate limiting
- GitHub adapter safety restrictions, governed Jira and MCP connector foundations, and Slack notification sanitization

## Remaining Risks

Top residual risks in the current repository state:

- External checkpoint anchoring is now available as a foundation, but immutable evidence still depends on destination-side WORM controls
- No proxy-aware forwarded-IP trust model or advanced per-key abuse policy yet
- No tenant-scoped key hierarchy and no broader cloud/Vault key-provider coverage beyond AWS KMS
- No lease renewal or separate external dead-letter queue
- No tenant-managed GitHub App installation workflow or stronger connector trust sync
- No SAML, broad SCIM identity-governance coverage, or full identity lifecycle controls
- No formal load, chaos, or adversarial prompt-injection test program in-repo

## Recommended Next Mitigations

Priority-ordered next steps:

1. Enable destination-side WORM controls such as S3 Object Lock on top of the new checkpoint foundation so incident evidence can survive compromise of the primary datastore with a stronger immutability story.
2. Move payload and connector secrets to a real secret manager or KMS-backed provider.
3. Add proxy-aware client IP trust, finer per-key abuse policy, and Redis HA guidance beyond the current fixed-window distributed limiter.
4. Add lease renewal, richer dead-letter workflows, and stronger distributed worker orchestration before scaling asynchronous execution further.
5. Add tenant-managed GitHub App installation workflows and stronger repository trust synchronization from an enterprise source of truth.
6. Add SAML, broader SCIM identity-governance coverage, and stronger identity lifecycle controls for enterprises that require centralized deprovisioning.
7. Add stronger automated operator guidance and alerting for checkpoint failures, destination drift, and missing WORM retention.
8. Add threat-driven load tests, abuse-case regression tests, and connector-specific security drills.
9. Add append-only or signed approval evidence if high-assurance approval accountability is a goal.
10. Publish a recurring security-review cadence that uses the checklist and incident-response package in this directory.
