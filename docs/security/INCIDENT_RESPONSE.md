# Incident Response

This document is the security incident response playbook for AgentGate operators and maintainers.
It assumes the product is used as a runtime governance control plane, which means incidents may involve AI-driven tool use, approval paths, downstream connectors, and tenant-scoped evidence.

Use this document with:

- [Threat Model](THREAT_MODEL.md)
- [Security Overview](../SECURITY.md)
- [Jobs And Workers](../operations/jobs-and-workers.md)
- [Audit Export](../integrations/audit-export.md)

## Initial Triage

In the first response window:

1. Classify the incident type and suspected blast radius.
2. Identify affected tenant IDs, user IDs, agent IDs, tool IDs, approval IDs, job IDs, and request IDs.
3. Preserve evidence before making broad changes when possible, but do not delay secret revocation or containment if the exposure is active.
4. Contain the affected integration, route, tenant workflow, or worker path using the safest available operational control.
5. Capture timestamps, deployment version, environment, and current job-dispatch mode.

## Evidence Collection Checklist

Collect and preserve, in sanitized form where needed:

- Request IDs from API responses or logs
- Tenant ID, tenant slug, user ID, agent ID, and tool ID
- Tool-call ID, approval ID, trace ID, audit event IDs, and job IDs
- GitHub repository, issue, PR, or comment identifiers if the GitHub connector is involved
- OIDC issuer, subject, email, mapped role, and callback outcome if SSO is involved
- Audit export config ID, destination type, and last export status if export is involved
- Relevant time window and deployment version or commit SHA
- Recent structured logs, worker logs, metrics snapshots, and readiness status
- Whether retention purge, export, or execution jobs were inline or worker-driven
- Whether protected payloads were still present, already purged, or failed to decrypt

Do not collect or redistribute:

- Raw secrets, tokens, or `.env` contents unless the secret-rotation workflow requires tightly controlled handling
- Decrypted execution payloads unless absolutely necessary for trusted backend investigation
- Customer data outside the minimum responder set

## Containment Principles

- Prefer application-level disablement or configuration changes over ad hoc database mutation.
- If direct database changes are unavoidable, treat them as emergency operational actions and record them carefully.
- Revoke or rotate exposed credentials immediately.
- Stop or pause worker execution if duplicate writes or unsafe execution is still in progress.
- Keep audit, trace, and log preservation in mind before cleanup.

## Suspected Secret Leak

Examples:

- A GitHub token is committed to the repo
- A Slack bot token appears in logs or screenshots
- A payload-encryption key or OIDC client secret may have been exposed

Immediate actions:

1. Revoke or rotate the exposed secret at the source system.
2. Remove or invalidate the secret from runtime config, deployment variables, and operator tooling.
3. Run `python scripts/check-no-live-secrets.py` and the secret-scan workflow against the branch or commit range in question.
4. Review recent logs, docs, screenshots, and exported audit payloads for spread.

Investigation:

- Determine whether the leaked value was raw, truncated, sanitized, or only referenced by name.
- Identify where the secret was used: GitHub, Slack, OIDC, payload encryption, audit export, or another path.
- Check audit events and request IDs tied to the suspected time window.

Recovery:

- Replace the secret and confirm the new value is injected through the approved secret path.
- If the secret granted external system access, review that system for abuse after the exposure timestamp.

## Agent Executed Unsafe Action

Examples:

- Agent posted sensitive data to a public GitHub issue
- Agent created an unexpected issue or comment
- Agent executed a risky action that should have required approval

Immediate actions:

1. Disable the affected tool, agent, or tenant workflow through the trusted operational path used in your deployment.
2. Stop the worker if additional approved executions may still be queued.
3. Capture the tool call, approval state, trace, and related audit events.
4. If the action touched an external system, revert or contain it there as well.

Investigation:

- Determine whether the action was allowed immediately or executed after approval.
- Inspect intent, risk, policy, and approval decisions for the tool call.
- Review data classifications, repo trust, and connector config relevant to the action.
- Check for prompt injection or untrusted content in the source context.

Recovery:

- Tighten policy, approval, or connector allowlists before re-enabling the path.
- Add regression tests for the missed control.

## Tenant Data Isolation Incident

Examples:

- One tenant can view another tenant's tool calls, approvals, or audit data
- A job executes against the wrong tenant's records

Immediate actions:

1. Treat the incident as high severity even if only metadata was exposed.
2. Disable or restrict the affected endpoint, page, export, or worker workflow.
3. Preserve database identifiers, request IDs, and response samples in sanitized form.

Investigation:

- Identify whether the issue is in API auth, query filtering, job processing, export, or UI aggregation.
- Determine all affected tenants and time range.
- Review audit export destinations for possible downstream spread.

Recovery:

- Patch the tenant-scope bug and add a regression test.
- Re-run export or notification assessments if wrong-tenant data may have been replicated externally.

## Audit Export Failure

Examples:

- Export jobs fail repeatedly
- Destination credentials expired
- Cursor drift leaves gaps in downstream audit coverage

Immediate actions:

1. Determine whether this is an availability issue, a confidentiality issue, or both.
2. Check export job status, retry behavior, and destination health.
3. If the wrong destination was configured, disable that config immediately.

Investigation:

- Capture config ID, destination type, last export status, and cursor position.
- Review whether failures are retryable transport problems or permanent auth/configuration problems.
- Confirm whether downstream systems received partial batches.

Recovery:

- Fix credentials or destination configuration.
- Run a controlled dry-run followed by a real export once safe.
- If evidence continuity matters, document the time window with missing downstream coverage.

## Payload Encryption Key Exposure

Examples:

- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` was exposed
- A decrypt-only historical key was leaked

Immediate actions:

1. Rotate the active key immediately.
2. Keep required decrypt-only refs only as long as needed for still-retained historical payloads.
3. Restrict access to workers and trusted execution paths while key handling is under review.

Investigation:

- Determine whether the exposed key was active, decrypt-only, local fallback, or unused.
- Estimate which retained payloads may now be readable by an attacker with database access.
- Review `GET /v1/security/key-status` and key-rotation configuration.

Recovery:

- Move to a freshly generated key and update secret injection.
- Shorten retention or accelerate purge where policy allows if old ciphertext exposure is a concern.
- Plan a future rewrap workflow if historical payload readability must be preserved safely.

## GitHub Connector Abuse

Examples:

- GitHub PAT abuse
- Unexpected public issue creation or comment spam
- Connector used against an out-of-policy repository

Immediate actions:

1. Revoke or rotate the GitHub credential.
2. Disable the affected GitHub tool or narrow its repository allowlist.
3. Review GitHub-side audit logs and repository artifacts for the incident window.

Investigation:

- Check whether the request came through approval or immediate allow.
- Inspect repository trust classification and policy rules that applied.
- Confirm whether the connector config still used `token_env_var` or another approved secret reference.

Recovery:

- Restore access with a reduced-scope credential.
- Tighten allowlists and policy coverage before re-enabling writes.

## OIDC Compromise

Examples:

- Suspicious OIDC login wave
- Incorrect role mapping from IdP claims
- Suspected callback misuse or exchange-ticket abuse

Immediate actions:

1. Disable the affected tenant OIDC configuration through the trusted operational change path.
2. Review local-auth fallback exposure for the tenant and decide whether temporary local-only access is safer.
3. Invalidate impacted sessions if session rotation is required by your deployment model.

Investigation:

- Capture issuer, subject, email, mapped role, tenant slug, and failure or success events.
- Review state, nonce, domain filtering, and role-mapping assumptions.
- Determine whether the issue is with AgentGate validation, IdP configuration, or both.

Recovery:

- Correct role mappings, redirect URLs, allowed domains, or IdP client credentials.
- Re-enable OIDC only after a clean end-to-end validation.

## Worker Or Job Duplicate Execution

Examples:

- Approved execution runs twice
- Repeated notification or export jobs create operational noise
- Worker crash or retry behavior creates ambiguity about write completion

Immediate actions:

1. Pause workers or scale them down to stop further execution.
2. Identify the job type, idempotency key, tenant ID, and tool-call or approval linkage.
3. Check the external system for duplicate side effects, especially GitHub issues or comments.

Investigation:

- Determine whether the duplicate came from retry logic, manual rerun, stale state, or operator action.
- Inspect job status transitions, `ToolCall.status`, and approval execution records.
- Confirm whether the action type was supposed to be retryable.

Recovery:

- Clean up external side effects carefully.
- Patch the idempotency or worker-state bug and add a regression test.

## Rollback And Containment Actions

Common containment levers:

- Disable a tool, agent, or tenant workflow
- Disable Slack notifications
- Disable or narrow GitHub connector repository allowlists
- Disable a tenant audit export destination
- Disable a tenant OIDC config
- Rotate or revoke GitHub, Slack, OIDC, export, or payload-key secrets
- Stop workers when queued execution is unsafe
- Switch operational workflow to manual approval or dry-run mode until controls are repaired

Choose the narrowest control that safely contains the incident.
Avoid broad emergency changes that destroy evidence or create additional authorization gaps.
