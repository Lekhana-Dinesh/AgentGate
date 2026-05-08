# Security Review Checklist

Use this checklist for feature reviews, pull requests, operational change reviews, and pre-release security signoff.
Mark non-applicable items as `N/A` with a short reason rather than silently skipping them.

Related docs:

- [Security Overview](../SECURITY.md)
- [Threat Model](THREAT_MODEL.md)
- [Incident Response](INCIDENT_RESPONSE.md)
- [Audit Integrity](audit-integrity.md)
- [External Audit Anchoring](external-audit-anchoring.md)
- [Payload Protection](payload-protection.md)
- [Key And Secret Management](key-and-secret-management.md)
- [SSO And OIDC](sso-oidc.md)
- [Retention And Purge](retention-and-purge.md)
- [Jobs And Workers](../operations/jobs-and-workers.md)
- [Audit Export](../integrations/audit-export.md)
- [Deployment Hardening](../operations/deployment-hardening.md)

## Auth And RBAC Checklist

- [ ] New API routes require authentication unless they are intentionally public.
- [ ] Role checks follow least privilege and match existing AgentGate role semantics.
- [ ] Local auth, OIDC, API key, and approval paths still fail closed on malformed or missing inputs.
- [ ] JWT, API key, and OIDC flows do not log secrets, tokens, passwords, exchange tickets, or raw upstream assertions.
- [ ] OIDC role mapping changes do not implicitly grant `owner` or other privileged roles without explicit intent.
- [ ] Security-sensitive endpoints return safe errors without leaking auth state, tenant existence, or secret material.

## Tenant Isolation Checklist

- [ ] Every read and write path preserves tenant scope.
- [ ] Background jobs, exports, traces, approvals, and retention logic keep the originating tenant context.
- [ ] Tests cover any new cross-tenant access risk or tenant-boundary logic.
- [ ] New IDs or lookup patterns cannot be used to read or mutate another tenant's objects by guessing identifiers.
- [ ] Dashboard pages and API responses avoid mixed-tenant aggregates unless that behavior is explicitly intended.

## Secret Management Checklist

- [ ] Raw secrets are not stored in the database, API payload examples, or UI state.
- [ ] New integrations use the shared secret-reference or env-var resolution path.
- [ ] Unsupported or missing secret references fail closed.
- [ ] Logs, metrics, readiness, traces, audit exports, and Slack messages do not expose secrets.
- [ ] Production configuration changes do not weaken secret requirements or re-enable local fallbacks.
- [ ] Public docs and examples pass `python scripts/check-no-live-secrets.py`.

## Payload Protection Checklist

- [ ] Sensitive execution arguments are still protected before persistence.
- [ ] Only trusted backend execution paths decrypt protected payloads.
- [ ] Public APIs and UI views continue to expose sanitized payload summaries only.
- [ ] Purge behavior remains idempotent and does not decrypt archived payloads.
- [ ] Approved execution still fails closed if the required protected payload has been purged or is invalid.
- [ ] New sensitive fields or connector-specific bodies are reviewed for protection and redaction behavior.

## Connector Safety Checklist

- [ ] Connector actions are explicitly allowlisted and validated.
- [ ] Destructive or unknown actions are blocked at the adapter layer, not only by policy.
- [ ] Retry behavior does not duplicate non-idempotent writes.
- [ ] Repository, recipient, or destination trust classification is preserved where relevant.
- [ ] Connector config rejects raw tokens or unsafe secret input forms.
- [ ] Upstream errors are mapped to safe, actionable local error codes.

## Job And Worker Checklist

- [ ] Job creation preserves tenant context and uses stable idempotency keys where needed.
- [ ] Inline and worker modes behave consistently enough for correctness and testability.
- [ ] Worker heartbeat and worker-status visibility expose only safe operational metadata.
- [ ] Lease ownership, stale recovery, and terminal dead-letter behavior are covered by tests and documented honestly for PostgreSQL versus SQLite.
- [ ] Jobs that can safely retry are retryable; non-idempotent jobs remain single-attempt unless stronger safeguards exist.
- [ ] Manual retry paths do not allow blind replay of non-idempotent writes such as approved execution.
- [ ] New job types include safe operator visibility without exposing payload secrets.
- [ ] Worker-side execution does not broaden access to decrypted payloads beyond the trusted path.
- [ ] Failure, retry exhaustion, and backlog behavior are observable through logs, metrics, or dashboards.

## Audit And Export Checklist

- [ ] Audit events remain sanitized at write time and before export.
- [ ] New audit events remain anchored into the correct tenant-scoped chain, or any legacy/unanchored behavior is explicitly documented and tested.
- [ ] Verification paths detect broken sequence, previous-hash mismatch, or event-hash mismatch for anchored history.
- [ ] Audit checkpoint records are tenant-scoped, expose only safe metadata, and do not store cloud credentials, raw audit metadata bodies, or decrypted payload content.
- [ ] External checkpoint documents are derived from safe integrity metadata only and do not create self-referential checkpoint loops that cause endless checkpoint churn.
- [ ] External checkpoint verification detects missing external documents, checkpoint-hash drift, or mismatched checkpoint boundaries.
- [ ] Any S3-compatible anchor path is documented honestly as tamper-evident evidence preservation, not as full immutability unless destination-side WORM or Object Lock is actually configured.
- [ ] Export destinations are tenant-scoped and credential-safe.
- [ ] Raw secrets, decrypted payloads, and encrypted envelope internals are never exported.
- [ ] Export payloads include only safe integrity metadata and never require raw secrets or decrypted payload content.
- [ ] Cursor behavior, dry-run behavior, and duplicate-prevention logic remain intact.
- [ ] New audit events contain enough context for investigation without leaking secret material.
- [ ] Security-sensitive changes include a clear incident-response and operator-observability story.

## Frontend Security Checklist

- [ ] Frontend pages do not render decrypted payloads, raw secrets, or unsafe debug state.
- [ ] Auth tokens, cookies, and redirect flows are handled with existing security assumptions in mind.
- [ ] OIDC and login UX changes do not introduce open redirects or origin confusion.
- [ ] Error states and operator tooling do not reveal internal stack traces or sensitive configuration.
- [ ] New pages respect RBAC expectations and avoid cross-tenant assumptions in queries or UI summaries.

## Deployment Checklist

- [ ] Production mode requires strong JWT secrets, explicit CORS, valid public URLs, and payload-encryption configuration.
- [ ] Local demo credentials and insecure development fallbacks are disabled outside development and test.
- [ ] Reverse proxy or ingress settings preserve TLS, host, and request-ID assumptions.
- [ ] Metrics, readiness, and health endpoints are exposed only as broadly as intended.
- [ ] Rate limits are configured for the expected traffic model and not silently disabled in production.
- [ ] Secret scanning, CI validation, and public-doc checks are part of the release workflow.

## Incident Response Checklist

- [ ] The relevant playbook in [Incident Response](INCIDENT_RESPONSE.md) has been reviewed for this feature or change area.
- [ ] Operators can identify request IDs, tenant IDs, tool-call IDs, approval IDs, and job IDs when things go wrong.
- [ ] There is a documented containment path for disabling the affected integration, route, or workflow.
- [ ] Audit, trace, and metrics coverage is sufficient to support post-incident reconstruction.
- [ ] Any new secret or credential has a realistic rotation and revocation plan.
