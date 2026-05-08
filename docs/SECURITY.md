# Security

## Security Review Package

- [Formal Threat Model](security/THREAT_MODEL.md)
- [Security Review Checklist](security/SECURITY_REVIEW_CHECKLIST.md)
- [Incident Response](security/INCIDENT_RESPONSE.md)
- [Audit Integrity](security/audit-integrity.md)
- [External Audit Anchoring](security/external-audit-anchoring.md)
- [Payload Protection](security/payload-protection.md)
- [Key And Secret Management](security/key-and-secret-management.md)
- [Agent API Keys](security/agent-api-keys.md)
- [Identity Lifecycle](security/identity-lifecycle.md)
- [SCIM Provisioning](security/scim.md)
- [Session Hardening](security/session-hardening.md)
- [SSO And OIDC](security/sso-oidc.md)
- [Retention And Purge](security/retention-and-purge.md)

This page summarizes currently implemented controls and deployment guidance.
Use the linked threat model for structured abuse-case analysis and the incident-response playbook for operational response.
For the current private disclosure path, supported review scope, and the placeholder security contact that must be replaced before broader sharing, see the root [Security Policy](../SECURITY.md).

## Threat Model

Formal STRIDE analysis, abuse cases, actors, trust boundaries, and recommended next mitigations live in [security/THREAT_MODEL.md](security/THREAT_MODEL.md).

AgentGate assumes enterprise AI agents may attempt actions that are:

- Outside the original business intent
- Higher risk than the user expected
- Directed at external recipients
- Destructive, irreversible, or financially impactful
- Cross-tenant if isolation breaks

The platform focuses on runtime control and governance, not on claiming perfect prevention of all AI-related failures.

## Current Protections

- Argon2 password hashing
- JWT expiry for local development auth
- Optional HttpOnly browser session mode with CSRF enforcement for unsafe requests
- Tenant-aware query filtering on business objects
- Role-based access control on sensitive endpoints
- API key hashing instead of raw key storage
- API key expirations, revocation timestamps, and scope checks for gateway invocation
- Agent API key lifecycle APIs and browser UI now use metadata-only list responses plus one-time raw secret display at creation
- Policy authoring remains deterministic and tenant-scoped, with browser-side starter templates and enable or disable controls routed through the existing policy APIs instead of a separate engine path
- Structured input validation with Pydantic
- Centralized exception handling without stack trace leakage
- Security headers and scoped CORS configuration
- Audit events for gateway and approval actions
- Request IDs on responses and structured request/error logs for incident triage
- Deterministic fail-closed behavior for malformed policy evaluation during high-risk cases
- Slack approval notifications use sanitized summaries only and never persist raw bot tokens in the database
- Sensitive execution arguments are protected at rest with field-level encryption envelopes and exposed through sanitized API views only
- Payload protection envelopes now carry key metadata so decrypt paths can resolve the correct key by `key_ref` during manual rotation windows
- Payload protection now supports an AWS KMS-backed provider foundation that stores wrapped data keys in envelopes instead of plaintext key material
- Durable async jobs are tenant-scoped, idempotency-keyed, and exposed through sanitized operator APIs only
- Worker-mode jobs now carry explicit lease ownership, heartbeat-backed worker visibility, and stale recovery for safe retryable job types
- Approved execution jobs do not blindly retry non-idempotent writes, reducing duplicate GitHub mutations and similar side effects
- Terminal job review is durable and explicit through `failed` or `retry_exhausted` plus `dead_letter_reason`, and generic manual retry is intentionally blocked for approved execution
- Retention purge now redacts expired protected execution payloads without decrypting them and preserves auditability through sanitized tombstones and audit events
- OIDC login uses signed state validation, nonce binding, tenant-scoped config, domain checks, and exchange tickets so the final AgentGate JWT is not handed to the browser callback URL directly
- SCIM provisioning is tenant-scoped, bearer-token-only, rate limited, audited, and wired into the same deactivation and owner-protection logic as the admin user APIs
- User lifecycle state is enforced on each authenticated request, so deactivated users cannot continue using previously issued JWTs once current-user resolution checks the database row
- Cookie-authenticated browser sessions use the same current-user lookup model, so deactivated users are still rejected without adding a separate server-side session store
- Deactivation revokes active agent API keys created by that user, reducing the chance of orphaned user-owned automation credentials surviving offboarding
- GitHub, Slack, OIDC, and payload-key lookups now use a shared secret-reference resolver that fails closed on missing or unsupported references
- GitHub connector auth now supports local env-token mode plus GitHub App JWT and installation-token exchange with in-memory token caching only
- Jira connector auth now supports env-token and basic-env modes with project-scoped allowlists and single-attempt writes only
- MCP connector support now provides an HTTP-only governed proxy foundation with explicit tool allowlists, trust-domain hints, bounded payload sizes, safe list-tools probing, and single-attempt remote `call_tool` execution
- Audit export jobs now ship sanitized audit events through tenant-scoped destinations with explicit timeouts, bounded retries for safe failures only, and per-config cursors that prevent duplicate exports across runs
- Recurring scheduled tasks are tenant-scoped, use safe non-secret config, and enqueue existing durable jobs rather than executing privileged retention, export, or integrity logic inline inside the scheduler loop
- The admin settings overview is tenant-authenticated, read-only, and limited to safe status summaries instead of raw config bodies, secret refs, tokens, private keys, or decrypted payloads
- Browser operational controls for scheduled tasks, audit exports, and retention remain narrow and non-secret: only owner and admin roles can mutate them, while security reviewers stay read-only
- The onboarding status surface is tenant-authenticated, limited to safe setup posture, and restricted to operator roles that already manage tenant governance
- The tools/connectors surface is tenant-authenticated, intentionally excludes raw tool config, secret refs, env-var token names, auth emails, and decrypted payloads, and only allows narrow non-secret metadata changes for owner/admin roles
- Sensitive control-plane endpoints now have built-in rate limiting with safe `429` responses and optional tenant-scoped audit coverage for privileged throttling events
- The rate limiting layer now supports Redis-backed distributed enforcement for multi-instance deployments while preserving in-memory local development behavior
- Request logs now record request IDs, timing, status, safe error codes, and tenant/user context when known without logging request bodies or decrypted payloads
- Readiness and metrics endpoints now expose safe operational status and aggregate counters without exposing secrets or payload content
- New audit events are now linked into tenant-scoped tamper-evident hash chains, and privileged operators can verify or backfill chain integrity without exposing raw secrets or decrypted payloads
- Tenant-scoped audit-integrity checkpoint jobs can now verify anchored ranges and write safe checkpoint documents to a configured local or S3-compatible external anchor without storing cloud credentials in the database
- Repository CI now includes conservative backend linting, high-confidence Bandit scanning, high-threshold frontend dependency audit, advisory backend dependency audit, Trivy filesystem scanning, and dedicated secret scanning with Gitleaks

## Current Limitations

- Local email/password auth remains available alongside optional OIDC; this is not yet a pure enterprise-SSO-only deployment model
- Cookie mode is stateless and does not yet include server-side session inventory, per-session admin revocation, or remote session kill controls
- No GCP KMS, Azure Key Vault, or HashiCorp Vault provider implementation yet; the current build ships the env-backed provider plus an AWS KMS-backed payload-protection provider foundation
- External checkpoint anchoring now exists as a foundation, but there is still no built-in notarization service and no valid immutability claim unless the destination itself enforces WORM or Object Lock semantics
- No database row-level security policies at the database layer
- The Redis-backed limiter currently uses fixed windows and is not yet proxy-trust-aware for forwarded client IP handling
- No per-key IP allowlisting or signed request scheme for agent API keys yet
- GitHub env-token auth remains available for development, but production should prefer GitHub App installation-token auth with the private key injected through the runtime environment or a future secret manager
- GitHub repository trust classification currently depends on connector config and runtime hints, not a live enterprise source of truth
- GitHub read retries are bounded and write retries are intentionally disabled to avoid duplicate mutations
- GitHub App private key resolution is still env-backed in this build; there is no tenant-managed installation discovery or webhook-driven sync yet
- The browser API-key lifecycle surface is intentionally narrow: create, list, and revoke only, with no bulk rotation, per-key IP policy, or secret recovery after creation
- Jira is intentionally minimal: no destructive actions, no attachment writes, no webhook sync, and no tenant-admin credential UI yet
- MCP is intentionally narrow: HTTP transport only, tools-only support, no stdio or streaming sessions, no prompts/resources surfaces, and no unrestricted remote tool execution
- Onboarding is intentionally narrow: it does not provision external integrations, manage secrets, or replace the existing admin APIs for agents, tools, identity, or settings
- Tool management in the browser is intentionally narrow: the current `/tools` page can review and edit non-secret metadata for a small connector set, but it still does not edit secret-backed connector configuration or accept raw credentials
- Policy management in the browser is intentionally narrow: guided starter creation, JSON preview, and enable or disable only, with deeper edits and policy-pack apply workflows remaining API or script driven
- Operational browser controls are intentionally narrow: scheduled-task creation, detailed audit-export destination editing, secret wiring, and real retention purge policy changes remain outside the settings UI
- Slack configuration is environment-scoped in this build; there is no tenant-managed Slack app installation flow yet
- Slack notifications are outbound alerts only. There is no signed interactive Slack approval flow in this version
- Payload encryption is still environment-scoped and not tenant-scoped key material
- The built-in worker and scheduler loops are suitable for production-minded deployments and now include safe recurring enqueue behavior, but they are not yet a fully managed distributed orchestration system with lease renewal, leader election, a separate external dead-letter queue, or fleet-wide autoscaling
- Legal hold is data-model enforced, but there is not yet a dedicated legal-hold administration workflow or external records-management integration
- OIDC currently supports one practical active provider path per tenant login entrypoint and does not yet include full tenant-admin CRUD or SAML support
- SCIM is intentionally minimal: there is no Groups API, no role-sync workflow, and no tenant-admin SCIM token issuance or rotation surface
- `client_secret_ref` is modeled, but this build only resolves environment-variable secrets out of the box. External secret-manager resolution is still a follow-on step
- Automated vulnerability feeds and static scanners are useful, but they do not replace manual threat modeling, code review, or deployment-specific security review

## Repository Tooling

Current automated repo tooling focuses on low-noise, practical coverage:

- `Ruff` for conservative backend Python linting
- `Bandit` for high-confidence Python security findings in `apps/api/app`
- `pip-audit` for backend dependency exposure review
- `npm audit --audit-level=high` for frontend dependency exposure review
- `Trivy` filesystem scanning for high and critical dependency and misconfiguration findings
- `Gitleaks` for secret detection

Current CI gate behavior:

- Blocking: Ruff, Bandit, `npm audit` high+, Trivy high and critical findings, existing backend tests, frontend build, Docker Compose validation, and Gitleaks
- Advisory: `pip-audit` currently runs without blocking because Python advisory severity filtering is not clean enough yet for a low-noise hard gate

False-positive guidance:

- Prefer fixing the issue first.
- Use targeted `# nosec <rule>` suppressions only when the code path is understood and the reason is documented.
- Prefer narrow Ruff per-file ignores over broad rule disables.
- Keep Trivy or dependency-audit exceptions specific and time-bounded if they become necessary.

## Future Enterprise Controls

- Broader SCIM coverage such as groups, richer filters, role mapping, and managed token lifecycle
- SSO/SAML/OIDC expansion and richer admin lifecycle controls
- SIEM coverage expansion beyond the current webhook, Splunk HEC, and Datadog-compatible export foundation
- Stronger immutable audit log pipelines and destination-side WORM enforcement
- Broader KMS and external secret-manager integrations
- VPC deployment patterns
- SOC 2 operational process controls
- Data retention and deletion policies

## Secure Deployment Guidance

- Replace the development secret key before any shared environment use.
- Use PostgreSQL in non-local deployments.
- Place the API behind a TLS-terminating ingress or gateway.
- Prefer keeping `/metrics` on an internal network path even though the endpoint only exposes aggregate metrics.
- Use `AGENTGATE_RATE_LIMIT_PROVIDER=redis` for production-like multi-instance deployments and treat `AGENTGATE_ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION=true` as an explicit short-term exception only.
- Disable demo seed credentials outside local or isolated demo environments.
- Rotate agent API keys on a schedule and prefer short expirations for non-human integrations.
- Review tool payload retention policy before storing sensitive production data.
- Review and document which retention classes map to your regulatory obligations before enabling recurring purge automation.
- Review each scheduled task config for tenant scope, safe filters, and schedule cadence before enabling it. Scheduled task config must never be used as a secret store.
- Set `AGENTGATE_PUBLIC_API_URL` and `AGENTGATE_PUBLIC_APP_URL` to the externally reachable origins before enabling OIDC.
- For browser operators in production, prefer `AGENTGATE_AUTH_SESSION_MODE=cookie`, `AGENTGATE_COOKIE_SECURE=true`, `AGENTGATE_COOKIE_SAMESITE=lax`, and `AGENTGATE_CSRF_ENABLED=true`.
- Do not place raw GitHub tokens or GitHub App private keys in tool config. Use `token_env_var`, `private_key_env_var`, or `private_key_secret_ref` and inject the secret from the runtime environment or a secret manager.
- For production GitHub connector auth, prefer `auth_mode=github_app` with the minimum required GitHub App permissions: `Metadata` read, `Pull requests` read, and `Issues` read/write if you want issue creation or comments.
- Keep GitHub App installation tokens in memory only. AgentGate does not persist installation tokens, JWTs, or Authorization headers.
- Do not place raw Jira bearer tokens, Jira API tokens, passwords, or auth emails in tool config. Inject them through environment or a secret manager workflow.
- Keep Jira `project_allowlist`, `issue_type_allowlist`, `transition_allowlist`, and `assignee_allowlist` as narrow as the business workflow allows.
- Treat Jira writes the same way as GitHub writes: routed through gateway controls and never blindly retried.
- Do not place raw MCP bearer tokens, API keys, Authorization headers, or secret-bearing header maps in tool config. Inject credentials through environment or a secret manager workflow.
- Keep MCP `allowed_tool_names` narrow, use `blocked_tool_names` for explicit deny cases, and prefer `trust_domain=internal` only when you actually control the remote MCP boundary.
- Treat external or unknown MCP servers as higher-risk dependencies and route them through approval policies before allowing side-effecting `call_tool` operations.
- Do not expose shell, admin, delete, transfer, or other dangerous MCP tools unless you intentionally want them blocked or approval-gated by policy.
- MCP `call_tool` is intentionally single-attempt. Do not build blind retry behavior around remote side-effecting tool calls.
- For production payload protection, prefer `AGENTGATE_KEY_PROVIDER=aws_kms` with `AGENTGATE_AWS_REGION` and `AGENTGATE_AWS_KMS_KEY_ID`. Use a KMS alias where possible so `key_ref` remains stable and operator-readable.
- Prefer explicit env secret references such as `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY` if you want production config to align with the future secret-manager wiring model.
- Treat `GET /v1/tools/{tool_id}/health?probe=true` as an operator diagnostic, not a secret-validation bypass or deployment-readiness guarantee.
- Do not store raw Slack bot tokens in tool or tenant config. Inject `AGENTGATE_SLACK_BOT_TOKEN` from the runtime environment or a secret manager.
- Use `GET /v1/security/key-status` as a non-sensitive control-plane check for provider type, readiness, active key ref, safe AWS region metadata, and warnings. It does not expose plaintext key material, wrapped data keys, or cloud credentials.
- Treat Slack notifications as supplemental operational alerts, not as the authoritative approval system of record.
- Use Slack channel or user IDs that match your reviewer routing model and keep notification content limited to approved redacted summaries.
- Run a dedicated worker process whenever `AGENTGATE_JOB_DISPATCH_MODE=worker`; otherwise notification, approved execution, retention, and audit export jobs will remain queued.
- Run a dedicated scheduler process with `python -m app.scheduler` whenever recurring scheduled tasks are enabled in `worker` mode.
- Treat the jobs table as the durable source of truth even when Redis publication is enabled; Redis is an accelerator, not an authoritative execution ledger.
- Use PostgreSQL for multi-worker production deployments. SQLite remains acceptable for local development and tests, but not for high-assurance concurrent job claiming.
- Treat built-in cron scheduling as UTC-only and overlap-avoiding. If you need tenant-local time zones, stronger missed-run replay guarantees, or cluster-level leadership, use an external orchestrator against the same APIs.
- Keep `AGENTGATE_JOB_LEASE_SECONDS` comfortably above expected job runtime and keep `AGENTGATE_WORKER_STALE_AFTER_SECONDS` above the heartbeat interval.
- For `AGENTGATE_KEY_PROVIDER=env`, set `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` or a resolvable `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF` to a valid Fernet key in any non-development environment.
- For `AGENTGATE_KEY_PROVIDER=aws_kms`, require IAM permissions for `kms:DescribeKey`, `kms:GenerateDataKey`, and `kms:Decrypt` on the configured KMS key.
- If you rotate payload keys manually, keep prior decrypt-only refs in `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS` until required historical ciphertext is rewrapped or allowed to age out.
- Treat the development/test payload-encryption fallback as local convenience only, never as a production deployment pattern.
- Audit and alert on `payload_redaction_status="purge_failed"` or retention jobs ending in `failed` or `retry_exhausted`.
- Review OIDC role mappings carefully before enabling broad enterprise groups. Avoid defaulting privileged roles unless you have deliberate claim governance from the IdP side.
- Review who is allowed to deactivate or reactivate users, and validate that each tenant keeps at least one active owner account before operational cutover.
- Treat deactivation as the supported user offboarding path in the current build. Reactivation restores access, but previously revoked agent API keys must be recreated deliberately.
- If you enable SCIM, inject one strong bearer token per tenant through environment or a secret manager workflow, keep it separate from browser auth, and rotate it with the same care as other machine credentials.
- Review audit export destinations before enabling them in production. Prefer HTTPS endpoints, destination-side authentication, bounded batch sizes, and external monitoring for `failed` or `retry_exhausted` export jobs.
- Leave `AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS=false` in production unless you intentionally export to a private sink and understand the SSRF tradeoff.
- Treat audit export as sanitized replication, not as permission to lower the sensitivity classification of AgentGate audit data. Downstream SIEM retention and access controls still matter.
- Treat the built-in audit hash chain as a strong tamper-evident control inside AgentGate's primary datastore, and treat external checkpoints as a stronger evidence-preservation layer, not as full immutability unless the destination uses WORM or Object Lock.
- For production-minded checkpoint anchoring, prefer `AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage` with a dedicated bucket or prefix, least-privilege IAM, versioning, and destination-side Object Lock if you need stronger evidence-retention claims.
