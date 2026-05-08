# Share Package

This document is internal guidance for private sharing with a design partner, technical reviewer, or buyer committee member.

The goal is to send enough material to make AgentGate credible without overwhelming the reviewer or accidentally implying enterprise GA scope.

## Default Private Reviewer Package

Send these first:

- [README.md](../../README.md)
- [Enterprise Demo Guide](../demo/ENTERPRISE_DEMO_GUIDE.md)
- [Design Partner Evaluation](../demo/DESIGN_PARTNER_EVALUATION.md)
- [Pilot Scope](PILOT_SCOPE.md)
- [Pilot Readiness Review](PILOT_READINESS_REVIEW.md)
- `docs/operations/api-evaluation.md`
- [Deployment Validation](../operations/deployment-validation.md)
- [Pilot Policy Pack](../operations/pilot-policy-pack.md)

Why this package works:

- `README.md` gives the repo-level product, capability, and setup framing
- `Enterprise Demo Guide` gives the live narrative
- `Design Partner Evaluation` gives the reviewer a structured way to assess fit
- `Pilot Scope` keeps the first pilot narrow and honest
- `Pilot Readiness Review` tells the reviewer the team understands current limits
- `API Evaluation` helps technical reviewers exercise the product directly
- `Deployment Validation` shows there is a real operator smoke path
- `Pilot Policy Pack` shows the approval and guardrail story is not ad hoc

## Add For Security-Heavy Reviewers

Send these when the audience includes a security reviewer or asks for more depth:

- [Security Policy](../../SECURITY.md)
- [Security Overview](../SECURITY.md)
- `docs/security/THREAT_MODEL.md`

Use the threat model selectively. It is appropriate for a serious security conversation, but it does not need to be in every first email.

## Add For Platform Or Operations Reviewers

Send these when the audience includes infrastructure, platform, or operations owners:

- [Backup And Restore](../operations/backup-and-restore.md)
- [Observability Package](../operations/observability-package.md)
- [Production Readiness Checklist](../operations/production-readiness-checklist.md)

These docs help when the reviewer wants to understand what "production-style self-hosted pilot" means in practice.

## What Not To Send Initially

Do not send these in the first private outreach unless there is a specific reason:

- internal founder and operator docs such as `docs/go-to-market/DESIGN_PARTNER_OUTREACH.md`
- internal preflight docs such as `docs/go-to-market/PRE_PILOT_PREFLIGHT.md`
- internal review docs such as `docs/reviews/PRIVATE_RELEASE_CANDIDATE_REVIEW.md`
- `CONTRIBUTING.md`
- `docs/AGENTGATE_CODEX_HANDOFF.md`
- the full roadmap as a primary artifact
- low-level screenshot checklists, demo scripts, or internal rehearsal material before interest is established
- a large uncurated repo-doc dump

## Recommended Order

Use this order in most cases:

1. `README.md`
2. `docs/demo/ENTERPRISE_DEMO_GUIDE.md`
3. `docs/demo/DESIGN_PARTNER_EVALUATION.md`
4. `docs/reviews/PILOT_SCOPE.md`
5. `docs/reviews/PILOT_READINESS_REVIEW.md`
6. `docs/operations/api-evaluation.md`
7. `docs/operations/deployment-validation.md`
8. `docs/operations/pilot-policy-pack.md`

Add the security or operations supplements only after the reviewer signals that level of interest.

## Suggested Cover Note

Use a short note like this:

```text
Sharing a small private review package for AgentGate.

The product is best understood as a controlled-pilot-ready runtime control plane for enterprise AI agent tool use. The strongest first live path is GitHub-first and self-hosted. Jira is optional second-phase scope, and MCP stays off by default unless it is internal and tightly allowlisted.

The attached links cover the live demo story, evaluator workflow, recommended pilot boundary, and the core operator validation and policy materials.
```

