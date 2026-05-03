# Security

## Threat Model

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
- Tenant-aware query filtering on business objects
- Role-based access control on sensitive endpoints
- API key hashing instead of raw key storage
- API key expirations, revocation timestamps, and scope checks for gateway invocation
- Structured input validation with Pydantic
- Centralized exception handling without stack trace leakage
- Security headers and scoped CORS configuration
- Audit events for gateway and approval actions
- Request IDs on responses and structured request/error logs for incident triage
- Deterministic fail-closed behavior for malformed policy evaluation during high-risk cases
- Slack approval notifications use sanitized summaries only and never persist raw bot tokens in the database
- Sensitive execution arguments are protected at rest with field-level encryption envelopes and exposed through sanitized API views only
- Payload protection envelopes now carry key metadata so decrypt paths can resolve the correct key by `key_ref` during manual rotation windows
- Durable async jobs are tenant-scoped, idempotency-keyed, and exposed through sanitized operator APIs only
- Approved execution jobs do not blindly retry non-idempotent writes, reducing duplicate GitHub mutations and similar side effects
- Retention purge now redacts expired protected execution payloads without decrypting them and preserves auditability through sanitized tombstones and audit events
- OIDC login uses signed state validation, nonce binding, tenant-scoped config, domain checks, and exchange tickets so the final AgentGate JWT is not handed to the browser callback URL directly
- GitHub, Slack, OIDC, and payload-key lookups now use a shared secret-reference resolver that fails closed on missing or unsupported references
- Audit export jobs now ship sanitized audit events through tenant-scoped destinations with explicit timeouts, bounded retries for safe failures only, and per-config cursors that prevent duplicate exports across runs
- Sensitive control-plane endpoints now have built-in rate limiting with safe `429` responses and optional tenant-scoped audit coverage for privileged throttling events
- Request logs now record request IDs, timing, status, safe error codes, and tenant/user context when known without logging request bodies or decrypted payloads
- Readiness and metrics endpoints now expose safe operational status and aggregate counters without exposing secrets or payload content

## Current Limitations

- Local email/password auth remains available alongside optional OIDC; this is not yet a pure enterprise-SSO-only deployment model
- No cloud KMS provider implementation yet; the current build ships only the env-backed provider and secret-reference scaffolding
- No immutable external audit log sink or write-once archive guarantee
- No database row-level security policies at the database layer
- No distributed rate limiter yet; the current limiter is in-memory and process-local
- No per-key IP allowlisting or signed request scheme for agent API keys yet
- GitHub connector credentials are environment-backed for development, but production should use a KMS or platform secret manager
- GitHub repository trust classification currently depends on connector config and runtime hints, not a live enterprise source of truth
- GitHub read retries are bounded and write retries are intentionally disabled to avoid duplicate mutations
- Slack configuration is environment-scoped in this build; there is no tenant-managed Slack app installation flow yet
- Slack notifications are outbound alerts only. There is no signed interactive Slack approval flow in this version
- Payload encryption is still environment-scoped and not tenant-scoped key material
- The built-in worker loop is suitable for production-minded deployments but is not yet a fully managed distributed orchestration system with leases, dead-letter queues, or fleet-wide autoscaling
- Retention purge is manually enqueued today. There is no built-in scheduler or recurring cron orchestration yet
- Legal hold is data-model enforced, but there is not yet a dedicated legal-hold administration workflow or external records-management integration
- OIDC currently supports one practical active provider path per tenant login entrypoint and does not yet include full tenant-admin CRUD or SAML support
- `client_secret_ref` is modeled, but this build only resolves environment-variable secrets out of the box. External secret-manager resolution is still a follow-on step

## Future Enterprise Controls

- SCIM provisioning
- SSO/SAML/OIDC expansion and admin lifecycle controls
- SIEM coverage expansion beyond the current webhook, Splunk HEC, and Datadog-compatible export foundation
- Immutable audit log pipelines
- KMS integration
- VPC deployment patterns
- SOC 2 operational process controls
- Data retention and deletion policies

## Secure Deployment Guidance

- Replace the development secret key before any shared environment use.
- Use PostgreSQL in non-local deployments.
- Place the API behind a TLS-terminating ingress or gateway.
- Prefer keeping `/metrics` on an internal network path even though the endpoint only exposes aggregate metrics.
- Disable demo seed credentials outside local or isolated demo environments.
- Rotate agent API keys on a schedule and prefer short expirations for non-human integrations.
- Review tool payload retention policy before storing sensitive production data.
- Review and document which retention classes map to your regulatory obligations before enabling recurring purge automation.
- Set `AGENTGATE_PUBLIC_API_URL` and `AGENTGATE_PUBLIC_APP_URL` to the externally reachable origins before enabling OIDC.
- Do not place raw GitHub tokens in tool config; use `token_env_var` and inject the secret from the runtime environment.
- Prefer explicit env secret references such as `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY` if you want production config to align with the future secret-manager wiring model.
- Treat `GET /v1/tools/{tool_id}/health?probe=true` as an operator diagnostic, not a secret-validation bypass or deployment-readiness guarantee.
- Do not store raw Slack bot tokens in tool or tenant config. Inject `AGENTGATE_SLACK_BOT_TOKEN` from the runtime environment or a secret manager.
- Use `GET /v1/security/key-status` as a non-sensitive control-plane check for provider type, active key ref, and warnings. It does not prove cloud KMS integration because this build still uses the env provider only.
- Treat Slack notifications as supplemental operational alerts, not as the authoritative approval system of record.
- Use Slack channel or user IDs that match your reviewer routing model and keep notification content limited to approved redacted summaries.
- Run a dedicated worker process whenever `AGENTGATE_JOB_DISPATCH_MODE=worker`; otherwise notification, approved execution, retention, and audit export jobs will remain queued.
- Treat the jobs table as the durable source of truth even when Redis publication is enabled; Redis is an accelerator, not an authoritative execution ledger.
- Set `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` or a resolvable `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF` to a valid Fernet key in any non-development environment.
- If you rotate payload keys manually, keep prior decrypt-only refs in `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS` until required historical ciphertext is rewrapped or allowed to age out.
- Treat the development/test payload-encryption fallback as local convenience only, never as a production deployment pattern.
- Audit and alert on `payload_redaction_status="purge_failed"` or retention jobs ending in `failed` or `retry_exhausted`.
- Review OIDC role mappings carefully before enabling broad enterprise groups. Avoid defaulting privileged roles unless you have deliberate claim governance from the IdP side.
- Review audit export destinations before enabling them in production. Prefer HTTPS endpoints, destination-side authentication, bounded batch sizes, and external monitoring for `failed` or `retry_exhausted` export jobs.
- Leave `AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS=false` in production unless you intentionally export to a private sink and understand the SSRF tradeoff.
- Treat audit export as sanitized replication, not as permission to lower the sensitivity classification of AgentGate audit data. Downstream SIEM retention and access controls still matter.
