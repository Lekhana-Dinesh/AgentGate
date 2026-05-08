# Enterprise Demo Guide

## Purpose

Use this guide for a practical live demo of AgentGate to a design partner, buyer committee, investor, or technical reviewer.

The goal is to show how AgentGate governs real agent tool use at runtime without pretending the product is a finished compliance platform or a fully managed cloud service.

## Product Story

AgentGate exists for teams that want AI agents to use real enterprise tools without giving those agents blind, unmanaged production access.

The product story is:

1. The agent asks to do something meaningful in a live workflow.
2. AgentGate intercepts the tool call before the external system is touched.
3. AgentGate applies identity, tenant scope, intent, risk, policy, payload protection, approval routing, audit, and trace controls.
4. The team gets a clear decision path, operator review surface, and evidence trail instead of a black box.

## Buyer Pain

Lead with the pain a buyer already understands:

- agents can create real external side effects, not just answer chat questions
- enterprises need runtime authorization, not only prompt rules
- reviewers need approvals, traces, jobs, and evidence they can inspect later
- security teams want safer payload handling and stronger audit evidence than a plain application log
- platform teams want something they can run locally first and self-host later

## What To Show First

Show the operator experience before showing low-level architecture.

Recommended first view:

1. `/onboarding`
2. `/` Control Plane Overview
3. `/demo` Demo Scenario

That sequence helps the audience understand the product outcome before the technical details.

## 10-Minute Demo Flow

1. Log in with the seeded demo admin account.
2. Open `/onboarding` and show the safe first-run checklist plus the recommended next step.
3. Open `/` and explain that AgentGate is a control plane for agent actions, not another chat UI.
4. Open `/demo` and run `Run Sales Agent Risk Scenario`.
5. Open the generated trace and show that each tool call received an explicit decision path.
6. Open `/approvals` and explain how risky actions pause for reviewer control.
7. Open `/jobs` and explain that side effects such as notifications, approved execution, export, retention, and checkpointing run through durable jobs.
8. Open `/audit-integrity` and show verify plus checkpoint status.
9. Open `/settings` and close on safe operational visibility without exposing secrets.

## 30-Minute Technical Walkthrough

1. Start with `/onboarding` and explain that AgentGate now gives a safe first-run status view instead of forcing operators straight into docs and raw APIs.
2. Move to `/` and explain the product boundary: agent requests in, governed tool execution out.
3. Run the sales demo on `/demo`.
4. Open the trace replay and walk through intent, risk, policy, approval, and final outcome.
5. Open `/tool-calls` and show sanitized request and response views.
6. Open `/approvals` and explain reviewer gating.
7. Open `/jobs` and explain durable workflow handling, worker mode, and retry boundaries.
8. Open `/audit` and `/audit-integrity` to show evidence continuity.
9. If checkpointing is configured, create or verify a checkpoint and explain local chain versus external anchor.
10. Open `/audit-exports` and explain how sanitized audit history can move to external systems without exposing raw secrets.
11. Open `/retention` and explain replayable payload minimization.
12. Open `/users` and `/settings` to show identity lifecycle and safe readiness or integration status.
13. If GitHub is configured, show the GitHub connector docs and a safe GitHub write scenario that still goes through the same gateway.

## Expected Screenshots And Pages

Use these pages for live demo prep and leave-behind material:

- `/` Control Plane Overview
- `/onboarding`
- `/demo` Demo Scenario
- `/traces/[id]` Trace Replay
- `/tool-calls`
- `/approvals`
- `/jobs`
- `/audit-integrity`
- `/audit-exports`
- `/retention`
- `/scheduled-tasks`
- `/users`
- `/settings`
- `docs/connectors/github.md`
- `/ready` and `/metrics` if the audience cares about operator posture

See [SCREENSHOT_CHECKLIST.md](SCREENSHOT_CHECKLIST.md) for the concrete capture list.

## How To Explain Runtime Authorization

Use plain language:

"AgentGate does not trust the agent just because the user asked for a result. It evaluates every tool call at runtime before the external system is touched."

Then explain the actual checks:

- who is calling
- which tenant owns the action
- which agent and tool are in scope
- what the request appears to be doing
- how risky it is
- which deterministic policies apply
- whether human approval is required
- what should be protected, audited, and traced

Avoid turning this into a policy-engine lecture too early. The buyer needs to hear "runtime control before side effects" first.

## How To Explain Approvals, Jobs, Audit Integrity, And External Anchoring

Approvals:

- risky actions pause in a reviewer inbox instead of running immediately
- the approval step is part of the runtime path, not an afterthought

Jobs:

- long-running or operational follow-up work is durable
- AgentGate uses explicit jobs for notifications, approved execution, retention, exports, and audit checkpointing
- this keeps operator workflows visible and safer than hiding side effects inside a single request

Audit integrity:

- audit events are tenant-scoped and linked into a tamper-evident hash chain
- operators can verify the chain and backfill older history honestly

External anchoring:

- checkpoints summarize a verified range of audit events and can write that summary outside the primary database
- this is stronger evidence preservation than database-only integrity
- it is not a valid immutability claim unless the destination itself uses WORM or Object Lock semantics

## What Not To Claim

Do not claim:

- SOC 2, ISO, or other compliance certification
- full immutability by default
- complete secret-manager coverage
- SAML or broad SCIM identity-governance support
- managed SaaS operations
- multi-region scale proof
- production throughput numbers from the lightweight load-test suite
- live customer adoption unless you have real permission to say it

## Suggested Prep

- Seed the demo tenant with `python -m app.db.seed` or `docker compose exec api python -m app.db.seed`.
- Decide whether the demo is local developer mode or self-hosted production-style mode.
- For the default live story, keep the workflow seeded-mock-first or GitHub-first. Treat Jira as optional follow-on scope, and do not show MCP unless the server is internal and tightly allowlisted.
- If using GitHub, configure either `AGENTGATE_GITHUB_TOKEN` or GitHub App settings first.
- If using external checkpoints, prefer S3-compatible object storage over local-file mode for a stronger story.
- Keep one honest sentence ready on what is implemented today versus what remains roadmap work.

## Related Docs

- [Design Partner Evaluation](DESIGN_PARTNER_EVALUATION.md)
- [API Evaluation](../operations/api-evaluation.md)
- [Demo Script](DEMO_SCRIPT.md)
- [Screenshot Checklist](SCREENSHOT_CHECKLIST.md)
- [Existing Demo Scenario](../demo-scenario.md)
- [GitHub Connector](../connectors/github.md)
- [Audit Integrity](../security/audit-integrity.md)
- [External Audit Anchoring](../security/external-audit-anchoring.md)
