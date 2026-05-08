# Demo Script

## Opening Narrative

"Most teams experimenting with agents can get a workflow working. The hard part is letting that workflow touch real systems without giving the agent blind production access. AgentGate sits in that runtime path. It evaluates each tool call before the external system is touched, routes risky actions for review, protects sensitive execution payloads, and leaves behind a trace and audit record an operator can actually inspect."

## Exact Page Sequence

Use this sequence for the default live walkthrough:

1. `/login`
2. `/`
3. `/demo`
4. `/traces/{trace_id}`
5. `/tool-calls`
6. `/approvals`
7. `/jobs`
8. `/audit-integrity`
9. `/audit-exports`
10. `/retention`
11. `/settings`
12. `/users`

Optional branches:

- `docs/connectors/github.md` for GitHub connector setup and auth model
- `/scheduled-tasks` if the audience cares about recurring controls
- `/ready` and `/metrics` for platform and operations reviewers

## Talking Points

- "This is a control plane for agent actions, not another chat interface."
- "Every tool call is evaluated at runtime before the external system is touched."
- "Approvals, jobs, traces, and audits are first-class operator surfaces."
- "Sensitive execution state is minimized and protected."
- "Audit integrity is tamper-evident, and external checkpoints strengthen evidence preservation outside the primary database."

## Demo Flow

### 1. Login

Explain that local login is the default demo path and OIDC is optional.

### 2. Control Plane Overview

Point to the main operator surface and explain that the product centers on runtime decisions, not model prompts.

### 3. Demo Scenario

Open `/demo` and click `Run Sales Agent Risk Scenario`.

Explain the sequence:

- safe reads happen first
- a risky discount decision is reviewed
- an externalization step triggers stronger governance

### 4. Trace Replay

Open the generated trace and explain that the trace is the decision narrative for one agent run.

Call out:

- intent
- risk
- policy effects
- approval state
- final outcome

### 5. Tool Calls

Open `/tool-calls` and show that operators can review runtime decisions across agents and tools without seeing raw secrets or unsafe execution payloads.

### 6. Approvals

Open `/approvals` and explain that risky actions pause here instead of proceeding automatically.

### 7. Jobs

Open `/jobs` and explain that governance side effects are durable:

- notifications
- approved execution
- audit export
- retention
- audit-integrity verification
- audit checkpointing

## Risky GitHub Action Scenario

Use this only if a GitHub connector is configured.

Suggested narrative:

"Now take the same control model and apply it to a real external tool. A GitHub write is still just a governed tool call. AgentGate does not treat GitHub as a trusted bypass."

Practical flow:

1. Show `docs/connectors/github.md` or the configured tool metadata so the reviewer sees the supported auth model.
2. Explain that `create_issue` or `comment_on_issue_or_pr` is allowed only through the normal gateway path.
3. If you have a real policy configured for GitHub writes, trigger that write and show whether it is allowed or routed for approval.
4. If you do not have a real GitHub environment ready, stop at the config and safety story instead of faking a live mutation.

Key line:

"The important point is not that every GitHub write is always blocked. The point is that GitHub writes are still runtime-governed, policy-checked, auditable actions."

## Approval Workflow Scenario

Use the seeded sales demo for the default approval story.

Explain:

- the agent wanted to continue the workflow
- AgentGate required reviewer intervention for the risky step
- the reviewer decision became part of the trace and audit story
- if Slack is enabled, the notification is a helper channel, not the system of record

## Audit Integrity And Checkpoint Scenario

Open `/audit-integrity`.

Show:

- tenant-scoped chain status
- verify action
- latest checkpoint state
- create checkpoint button if configured

Explain:

- the local hash chain makes audit tampering detectable inside AgentGate
- the checkpoint layer summarizes a verified range and can anchor it outside the primary database
- object storage is a stronger story than database-only evidence
- it is still not correct to claim full immutability unless the destination uses WORM or Object Lock

## Settings And Status Scenario

Open `/settings`.

Explain that this page is intentionally read-only and safe:

- tenant profile
- SSO state
- connector health
- audit export status
- retention status
- scheduled-task status
- key provider readiness
- rate limiter readiness

If the audience includes platform or operations reviewers, also show:

- `GET /ready`
- `GET /metrics`

## Closing Pitch

"AgentGate is for teams that want agents to do real work without pretending runtime governance can be solved by prompts alone. The product already shows the core control plane surfaces: runtime authorization, approval routing, protected payload handling, durable jobs, traceability, audit integrity, and a credible self-hosted path. What it does not claim is just as important: this is not a compliance certification, not a magic immutable ledger, and not a finished managed platform. It is a practical foundation you can evaluate honestly."

## Related Docs

- [Enterprise Demo Guide](ENTERPRISE_DEMO_GUIDE.md)
- [Design Partner Evaluation](DESIGN_PARTNER_EVALUATION.md)
- [Screenshot Checklist](SCREENSHOT_CHECKLIST.md)
- [Existing Demo Scenario](../demo-scenario.md)
