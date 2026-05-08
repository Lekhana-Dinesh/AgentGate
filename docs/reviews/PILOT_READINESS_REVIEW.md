# Pilot Readiness Review

Review date: 2026-05-07

Scope note:
This is a controlled-pilot readiness audit based on the repository's current docs, workflows, deployment assets, security package, demo package, API evaluation materials, and high-level operator surfaces. It is not a source-level penetration test, a live production incident review, or a compliance assessment.

## Executive Verdict

Verdict: conditional go for a narrow, high-touch design-partner pilot.

AgentGate is ready for a controlled pilot if the pilot is:

- limited to a small number of hands-on design partners
- scoped to governed engineering or internal operations workflows
- deployed in the production-style self-hosted profile, not as a casual local demo
- run with explicit operator ownership, monitoring, and backup or restore drills
- sold honestly as a runtime governance foundation, not as enterprise GA or a compliance-ready platform

AgentGate is not ready for a broad self-serve launch, enterprise-wide rollout, or claims of mature managed-platform operations.

## What Is Strong

- The core runtime-governance story is credible: gateway, intent, risk, policy, approvals, audit, traces, and governed adapters all reinforce the same control plane.
- The security posture is stronger than a typical early-stage agent product: payload protection, KMS support, cookie-session hardening, lifecycle enforcement, rate limiting, audit integrity, and external checkpointing all exist as real product surfaces.
- The operator story is unusually complete for a pilot-stage repo: onboarding, settings, tools visibility, jobs, audit integrity, audit exports, retention, scheduled tasks, deployment validation, observability starter assets, and backup or restore guidance are all present.
- The evaluation package is strong: demo guide, script, screenshot checklist, API collection, deployment validator, browser E2E foundation, and load-test tripwires make the product easier to assess without reverse-engineering the repo.

## Pilot-Ready Capabilities

- Governed tool-call interception with tenant-aware auth, approval routing, audit, and traces
- GitHub connector for read actions plus controlled issue or comment writes
- Jira connector foundation for constrained reads and tightly scoped writes
- MCP governed proxy foundation for allowlisted internal tools when used conservatively
- OIDC login, cookie-session browser mode, and minimal SCIM-driven provisioning or deprovisioning
- Durable jobs, worker recovery, scheduled tasks, retention dry-runs, audit exports, audit integrity verification, and external checkpointing
- Self-hosted deployment with external Postgres and Redis, runtime validation, and operator runbooks

## Launch Blockers, If Any

There is no hard repo-level blocker for a narrow controlled pilot.

There are, however, go or no-go conditions that must be satisfied before contacting design partners:

- Freeze the supported pilot connector set and disable everything outside that scope.
- Complete one production-style rehearsal using the real deployment profile, not only local Docker Compose.
- Run one backup or restore drill and one audit-integrity checkpoint verification drill in the intended deployment shape.
- Decide whether the pilot will make any external evidence-integrity claims beyond database-local tamper evidence. If not using WORM or Object Lock, say so plainly.
- Align partner-facing messaging with current limitations, especially around SAML, SCIM depth, secret management, HA, and immutable evidence.

## High-Priority Pre-Pilot Fixes

- Freeze the first pilot to GitHub-first governed workflows, with Jira optional and MCP disabled by default unless the MCP server is internal and narrowly allowlisted.
- Build one internal reference deployment that uses the production-style profile, external Postgres and Redis, a dedicated worker, cookie mode for browser operators, and Redis-backed rate limiting.
- Run an internal operator rehearsal with `python scripts/run-pilot-rehearsal.py`, then complete the production-style follow-up steps it intentionally leaves manual.
- Pair that rehearsal with the deployment validator, API collection, demo flow, browser E2E smoke path, and backup or restore guide end to end.
- Review and apply the shipped default pilot policy pack for pilot environments so approval coverage is not left to ad hoc manual setup.
- Clean up external-facing documentation drift before broad sharing. The repo now has more shipped foundations than some older summary language implies, and enterprise buyers will notice inconsistency.

## Medium-Priority Follow-Ups

- Broader secret-manager coverage beyond env-backed resolution and IAM-style injection
- Stronger session administration such as per-session inventory or remote kill controls
- Proxy-aware abuse controls and richer API-key restrictions
- Audit-integrity and checkpoint-specific metrics and alerts
- Stronger worker orchestration such as lease renewal and richer dead-letter workflows
- Richer browser-side config UX for connectors and identity settings
- SAML and fuller SCIM coverage for customers that require centralized identity governance

## Security Posture Review

Overall assessment: strong for a controlled pilot, not high-assurance by default.

Strengths:

- Sensitive execution payloads are protected at rest and sanitized in operator views.
- The product avoids storing many raw secrets in the database and fails closed on unsupported secret-reference patterns.
- Cookie-session mode, CSRF enforcement, current-user reload checks, and lifecycle-based rejection of deactivated users are solid pilot-stage controls.
- Audit integrity and external checkpointing make the evidence story materially stronger than ordinary app logging.
- Connector write retry suppression and approval gating are the right default posture for side-effecting actions.

Residual risks:

- Local auth still exists alongside OIDC.
- Secret resolution is still env-first rather than backed by a broader external secret manager.
- Database row-level security is not present at the database layer.
- External checkpointing is not an immutability claim unless the destination truly enforces WORM or Object Lock semantics.
- MCP remains a high-risk surface if partners try to use it as a broad remote execution channel.

## Deployment And Operations Review

Overall assessment: credible for a small self-hosted pilot, not yet a mature platform operations story.

Strengths:

- Production-style Compose profile exists and assumes the right external dependencies.
- Deployment validation, backup or restore guidance, production runbook, and readiness checklist are all present.
- Observability starter assets and alert rules are available.
- Worker and scheduler are treated as first-class operator concerns rather than hidden background loops.

Gaps:

- The deployment story is Compose-based only. There is no Kubernetes, Helm, Terraform, or HA reference architecture.
- Readiness does not fully prove worker or scheduler liveness.
- The observability package is a starter set, not a full monitoring program.
- Backup and restore remain operator-managed, and Redis recovery is intentionally left to deployment-specific practice.

## Identity And Access Review

Overall assessment: good enough for a pilot if partner identity requirements are moderate.

Strengths:

- OIDC, cookie mode, RBAC, lifecycle enforcement, owner lockout protection, and API-key controls are all present.
- Minimal SCIM provisioning and deprovisioning exists and uses the same lifecycle enforcement path.
- Deactivated users are blocked on future authenticated requests rather than only at login time.

Gaps:

- No SAML.
- SCIM is intentionally minimal and not a full identity-governance surface.
- Local auth remains available, which some enterprises will view as a posture compromise even if the deployment chooses not to use it.
- There is no server-side session inventory or remote session revocation model.

## Connector And Governance Review

Overall assessment: the governance model is strong; connector maturity is uneven.

Strengths:

- The gateway remains the mandatory execution path.
- Connector actions are bounded, allowlisted, audited, and approval-aware.
- GitHub is the strongest current real connector and is suitable for a first pilot use case.
- Jira and MCP both have credible safety boundaries and clear limitations.

Gaps:

- GitHub is still the most mature connector; Jira and MCP are better treated as targeted or second-phase pilot options.
- MCP should not be treated as unrestricted enterprise tool access.
- Connector management in the UI is visibility-first, not full browser CRUD.
- Trust classification and allowlists still depend heavily on operator discipline and config hygiene.

## Audit And Evidence Review

Overall assessment: strong for tamper-evident pilot evidence, but do not oversell it.

Strengths:

- Tenant-scoped audit chains, verification, export, and checkpointing are real product capabilities.
- Checkpoints and external anchoring materially improve survivability beyond DB-local evidence.
- Backup or restore guidance explicitly includes audit-integrity verification after recovery.

Gaps:

- The built-in model is tamper-evident, not tamper-proof.
- No notarization service exists.
- No checkpoint-specific metric family exists yet.
- Claims of immutable evidence require real destination-side WORM or Object Lock controls that are external to AgentGate.

## Frontend And Operator UX Review

Overall assessment: good for guided pilots, not self-serve.

Strengths:

- Onboarding, settings, tools, jobs, audit integrity, audit exports, retention, scheduled tasks, and users give operators enough surface area to understand the product.
- The `/tools` page is well-scoped and safe-summary-only.
- Demo and evaluation surfaces reduce the time needed to explain the product.

Gaps:

- Onboarding is intentionally narrow and still depends on docs and APIs for real setup.
- The browser does not manage connector secrets or deeper identity configuration.
- Repo markdown docs still carry part of the operator experience instead of the product fully rendering those workflows in-app.

## Documentation And Evaluation Review

Overall assessment: unusually good for a pilot-stage repo, with some consistency cleanup still needed.

Strengths:

- The repo has a real handoff model, domain context files, deployment docs, runbooks, demo package, API collection, and backup or restore guide.
- The deployment validator and API collection make technical review materially easier.
- The docs are generally honest about not claiming compliance, immutability, or managed-platform status.

Gaps:

- Some broad summary language is behind the current repo reality, especially around SCIM and connector maturity.
- Buyers will still need a guided narrative to understand which capabilities are foundational versus recommended for immediate production use.

## Testing And CI Review

Overall assessment: strong for regression confidence, not exhaustive for enterprise assurance.

Strengths:

- Blocking backend compile and tests, frontend build, Compose validation, Ruff, Bandit, npm audit high+, Trivy, and Gitleaks
- Manual Playwright E2E covering the main operator surfaces
- k6 load tripwires for health, auth, gateway, jobs, integrity, and rate limiting
- Manual deployment validation and API evaluation flows

Gaps:

- Playwright is manual, not part of the default PR gate.
- `pip-audit` is advisory only.
- There is no chaos, disaster, or adversarial prompt-injection regression program in-repo.
- Load tests are helpful tripwires but not capacity proof.

## Honest Limitations

- Not enterprise GA
- Not a compliance package
- Not a managed SaaS platform
- Not a high-availability deployment product
- Not a full secret-manager platform
- Not a full identity-governance platform
- Not an immutable evidence system by default
- Not a broad unrestricted MCP execution environment

## Recommended Pilot Scope

Use the safe pilot definition in [PILOT_SCOPE.md](PILOT_SCOPE.md).

Short version:

- target a small engineering or platform team
- start with GitHub-governed workflows
- run self-hosted in the production-style profile
- require owner, admin, and security reviewer participation
- treat Jira and MCP as opt-in, later-phase surfaces rather than day-one commitments

## Recommended Do Not Use For List

- Destructive infrastructure or production-admin automation
- Broad customer-facing outbound messaging without mandatory approvals
- High-volume or HA-critical workloads
- Internet-exposed MCP tool execution with shell, admin, transfer, or delete semantics
- Claims of compliance certification or immutable evidence
- Self-serve partner onboarding without vendor support
- Customers whose baseline requirement is SAML, deep SCIM, managed secret resolution, or Kubernetes-first packaging

## Checklist Before Contacting Design Partners

- Freeze the first pilot scope and supported connector list.
- Confirm one internal pilot environment has passed `scripts/validate-deployment.py`.
- Confirm the repo package has passed `python scripts/run-pilot-rehearsal.py --skip-live-api`.
- Confirm the intended pilot environment has passed `python scripts/run-pilot-rehearsal.py` with live validation enabled.
- Confirm one restore drill has passed `make verify-restore` plus audit-integrity follow-up checks.
- Confirm at least one operator with `owner` or `admin` and one `security_reviewer` will participate.
- Confirm `/metrics`, logs, worker status, and alerting are wired on an internal path.
- Confirm the partner-facing demo and API evaluation materials match the actual planned pilot scope.
- Confirm the pilot policy defaults require approval for external or side-effecting writes.
- Confirm the default pack at `policy-packs/pilot-default/policies.json` has been reviewed against the actual connector allowlists and reviewer staffing model.
- Confirm all partner-facing messaging avoids compliance, immutability, and enterprise-GA claims.
- Confirm demo credentials are not present in the pilot environment.
- Confirm the partner understands the recommended do-not-use list before a kickoff call.
