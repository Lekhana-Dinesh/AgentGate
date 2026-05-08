# Pre-Pilot Preflight

This document is internal founder and operator material.

Use it before outreach, before a live demo, and before inviting a design partner into a real pilot environment. The goal is to stop avoidable overclaiming and prevent the team from offering a pilot that the current repo and operating model cannot support honestly.

## Purpose

A design-partner motion goes badly when sales language outruns deployment reality.

This checklist is meant to keep AgentGate in the right lane:

- controlled-pilot ready
- GitHub-first by default
- Jira as constrained optional second-phase scope
- MCP disabled by default unless the remote server is internal and tightly allowlisted
- self-hosted and operator-guided
- honest about identity, evidence, observability, and recovery limitations

## Repo Readiness Checklist Before Outreach

Do not start outreach if the repo package itself is confusing.

Confirm:

- [README.md](../../README.md) points evaluators to the current pilot and demo material
- [Pilot Readiness Review](../reviews/PILOT_READINESS_REVIEW.md) and [Pilot Scope](../reviews/PILOT_SCOPE.md) match the story you plan to tell
- [Design Partner Evaluation](../demo/DESIGN_PARTNER_EVALUATION.md) and [Enterprise Demo Guide](../demo/ENTERPRISE_DEMO_GUIDE.md) match the actual pilot boundary
- [Pilot Rehearsal](../operations/pilot-rehearsal.md) exists and matches the actual internal operator flow
- [Pilot Policy Pack](../operations/pilot-policy-pack.md) reflects the conservative default approval posture you want for real partner traffic
- [Deployment Validation](../operations/deployment-validation.md), [Backup And Restore](../operations/backup-and-restore.md), and [Observability Package](../operations/observability-package.md) are present and linkable
- `python scripts/check-no-live-secrets.py` passes on the docs and examples you plan to share
- `python scripts/run-pilot-rehearsal.py --skip-live-api` passes for the repo package you plan to share
- no buyer-facing material implies managed SaaS, enterprise GA, compliance certification, full immutability, SAML, or broad SCIM identity governance
- the outreach owner can explain in one sentence why GitHub is first, Jira is optional, and MCP is off by default

## Environment Readiness Checklist

Before discussing a real pilot environment, confirm:

- the team has one reference deployment using the production-style profile rather than only local developer Compose
- the reference deployment has passed `python scripts/run-pilot-rehearsal.py` with live validation enabled
- PostgreSQL is external
- Redis is external
- a dedicated `worker` is running
- a dedicated `scheduler` is running if recurring tasks are enabled
- browser operators use `AGENTGATE_AUTH_SESSION_MODE=cookie`
- rate limiting uses `AGENTGATE_RATE_LIMIT_PROVIDER=redis`
- demo credentials are disabled in the real pilot environment
- secrets are injected through runtime environment or equivalent deployment-managed secret handling
- the team can explain exactly which auth mode and connector credentials are in scope for the pilot

## Demo Readiness Checklist

Before a founder-led or solutions-led demo, confirm:

- the seeded demo flow works end to end
- `/onboarding`, `/`, `/demo`, `/approvals`, `/jobs`, `/audit-integrity`, and `/settings` are the core path
- the presenter can explain runtime authorization in plain language
- the presenter has one honest sentence on current limitations
- the demo story is seeded-mock-first or GitHub-first
- Jira is shown only if the team deliberately wants second-phase scope in the conversation
- MCP is not shown unless the remote server is internal, tightly allowlisted, and explicitly part of the review
- the presenter knows what not to claim about compliance, immutability, SAML, SCIM depth, and managed operations

## Policy Pack Readiness Checklist

Before partner use, confirm:

- the default pilot pack has been reviewed
- the pack has been validated with the policy-pack validator
- the pack has been dry-run or applied against the intended pilot tenant
- at least one approval-required path has been exercised
- GitHub repository allowlists are reviewed
- if Jira is enabled, project, issue-type, transition, and assignee allowlists are reviewed
- if MCP is enabled, the server is internal, tool names are narrowly scoped, and approval coverage is explicit
- destructive actions remain blocked or tightly constrained
- reviewer staffing exists for the approvals the pack will generate

## Backup And Restore Readiness Checklist

Before calling an environment pilot-ready, confirm:

- PostgreSQL backup ownership is assigned
- backup frequency and retention are defined
- restore can target an isolated environment
- the same secret-manager or secret-injection shape can be recreated in recovery
- the KMS path can be re-established if AWS KMS is used
- one restore drill has been run
- `make verify-restore` has succeeded in the recovery environment
- audit-integrity status was checked after restore
- latest checkpoint verification was checked if external anchoring is enabled
- actual RTO and recovery gaps were recorded

## Observability Readiness Checklist

Before partner traffic, confirm:

- `/ready` is monitored
- `/metrics` is internal-only
- Prometheus scraping is configured or an equivalent internal metrics collector exists
- the starter alert rules are loaded or replaced with stricter internal equivalents
- structured logs are collected for `api`, `worker`, `scheduler`, and ingress
- `GET /v1/workers/status` is part of the operator health review
- the team understands the observability package is a starter asset set, not a full monitoring platform

## Security Messaging Checklist

Before any buyer or reviewer call, make sure the team will say these points consistently:

- AgentGate is controlled-pilot ready, not enterprise GA
- the product is self-hosted and operator-guided today
- GitHub is the strongest first live connector
- Jira is a constrained optional second-phase connector
- MCP is a narrow HTTP foundation and should stay disabled by default unless the server is internal and tightly allowlisted
- minimal SCIM Users foundation exists, but broad SCIM identity governance does not
- SAML does not exist today
- external audit checkpointing improves evidence survivability, but immutability requires destination-side WORM or Object Lock
- backup and restore guidance exists, but disaster recovery is still operator-managed
- observability starter assets exist, but no full monitoring platform is claimed
- the production-style Compose profile is credible for a pilot, but it is not HA, Kubernetes, Helm, or Terraform maturity

## Explicit No-Go Conditions

Do not start outreach for a real pilot if any of these are true:

- the team cannot explain the pilot scope in one paragraph
- the intended first workflow is not narrow enough to keep GitHub-first or seeded-mock-first
- the prospect requires SAML before engagement
- the prospect requires broad SCIM identity governance before engagement
- the prospect requires managed SaaS, enterprise HA, or Kubernetes-first packaging
- the prospect expects unrestricted MCP access
- the team has not rehearsed the demo and cannot explain the evidence or approval model
- no security reviewer is available to participate
- no pilot rehearsal run has been completed for either the repo package or the intended pilot environment
- no restore drill has been completed
- no deployment validation run has been completed on the intended environment shape
- buyer-facing messaging still implies compliance claims or immutable evidence claims that the deployment cannot support

## Recommended Sequence

Use this sequence:

1. Complete this preflight.
2. Run [Pilot Rehearsal](../operations/pilot-rehearsal.md) for the repo package and, when ready, for the intended environment.
3. Use [Design Partner Outreach](DESIGN_PARTNER_OUTREACH.md) for the first contact.
4. Run the buyer conversation using [Design Partner Evaluation](../demo/DESIGN_PARTNER_EVALUATION.md) and [Enterprise Demo Guide](../demo/ENTERPRISE_DEMO_GUIDE.md).
5. If the prospect is serious, align on [Pilot Scope](../reviews/PILOT_SCOPE.md).
6. Before partner traffic, confirm the conditions in [Pilot Readiness Review](../reviews/PILOT_READINESS_REVIEW.md).
