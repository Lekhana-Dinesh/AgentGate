# Design Partner Outreach

This document is internal founder and operator material.

Do not send it to prospects as a buyer-facing leave-behind. Use it to keep outreach, qualification, and pilot-next-step language consistent with AgentGate's current controlled-pilot posture.

## Purpose

Use this guide when you want to approach a design partner without overselling AgentGate as enterprise GA, managed SaaS, or a compliance-ready platform.

The goal is to start conversations with teams that have a real runtime-governance problem, a hands-on workflow owner, and enough security or platform maturity to evaluate a narrow self-hosted pilot honestly.

## Target Buyer Profile

Best-fit first design partner profile:

- AI platform or developer-platform team
- engineering productivity or internal tooling owner
- security or governance reviewer willing to inspect approvals, audit evidence, and deployment posture
- platform or infrastructure engineer who can run a self-hosted evaluation
- workflow owner with a real GitHub-centered use case

Best-fit team traits:

- already experimenting with agent-assisted engineering workflows
- worried about uncontrolled external side effects
- willing to run a controlled pilot instead of demanding turnkey SaaS
- comfortable evaluating a production-style self-hosted deployment
- able to staff at least one reviewer role, not just one enthusiastic builder

Poor-fit first design partners:

- teams whose baseline requirement is managed SaaS
- teams that require SAML before any evaluation starts
- teams expecting full SCIM identity governance, self-serve connector setup, or Kubernetes-first packaging on day one
- teams that want broad MCP-powered remote execution across unknown trust domains
- teams shopping only for a compliance badge rather than a runtime control product

## Who To Contact First

Contact the operational owner before the broad buyer committee.

Recommended first contact order:

1. AI platform, developer-platform, or engineering productivity owner
2. workflow owner who feels the real agent-side-effect pain
3. security or governance reviewer who will influence approval and audit requirements
4. infrastructure owner if the team is interested enough to discuss a self-hosted evaluation

Avoid starting with:

- procurement
- generic innovation teams with no workflow owner
- executive buyers who will immediately ask for enterprise GA packaging

## Pain Statement

Use one clear problem statement:

"Teams want agents to use real tools, but they do not want those agents touching external systems through blind credentials and weak prompt-only guardrails. AgentGate sits in the runtime path, evaluates each tool call before side effects happen, and gives reviewers approvals, traces, jobs, and audit evidence they can inspect."

Supporting pain points:

- agent workflows can now create real external side effects
- prompt rules alone do not provide runtime authorization
- security teams need inspectable approvals and evidence, not black-box execution
- platform teams need a self-hostable control point, not another chat wrapper

## Short Outreach Message

Use this when you need a concise first touch:

```text
Subject: Controlled pilot for governed agent tool use

We're working on AgentGate, a runtime control plane for AI agent tool calls.

The problem we're focused on is simple: teams want agents to use real systems like GitHub, but they do not want those agents operating with blind production access or prompt-only guardrails.

AgentGate sits in the execution path before the external system is touched, then applies policy, risk, approval, audit, and trace controls.

We're looking for a small number of hands-on design partners for a narrow, self-hosted, GitHub-first pilot. This is not a managed SaaS pitch or a compliance pitch. It is a controlled pilot for teams that want to evaluate runtime governance honestly.

If that problem is active on your side, I can send a short technical overview and a suggested pilot shape.
```

## Longer Technical Outreach Message

Use this when the prospect is already technical or has asked for more detail:

```text
Subject: Agent runtime governance design-partner pilot

We're building AgentGate as a runtime governance layer for enterprise AI agents.

Instead of trusting an agent because a user asked for an outcome, AgentGate intercepts each tool call before the target system is touched and evaluates identity, tenant scope, intent, risk, policy, approval routing, payload protection, audit, and trace handling.

Today the strongest first live path is a GitHub-first controlled pilot. The repo also includes a constrained Jira connector and a narrow HTTP MCP foundation, but we position Jira as optional second-phase scope and keep MCP disabled by default unless the remote server is internal and tightly allowlisted.

The product is best evaluated as a self-hosted controlled pilot, not as enterprise GA. We have a production-style Compose deployment profile, a pilot policy pack, deployment validation, backup and restore guidance, and observability starter assets. We do not position it as managed SaaS, compliance-certified infrastructure, full SCIM identity governance, or an immutability system by default.

If you're evaluating agent workflows that need runtime approval, audit evidence, and safer connector execution, we can walk through a narrow pilot shape and show exactly where the current boundaries are.
```

## Discovery Questions

Ask these before offering a pilot:

- What real agent workflow are you trying to govern first?
- Which external systems would the agent need to touch in the first 30 to 60 days?
- Is the first meaningful workflow GitHub-centered, or are you already assuming Jira, outbound messaging, or MCP-based internal tools?
- What side effects would make your security team uncomfortable if they happened without approval?
- Who would actually review risky actions in a pilot?
- Would you evaluate this as a self-hosted deployment run by your team, by us in a guided session, or both?
- Is local username and password auth acceptable for a pilot, or is SSO mandatory before you can engage?
- Do you require SAML, broad SCIM identity governance, managed secret resolution, HA, Kubernetes, or compliance artifacts before a pilot can start?
- Would an internal-only GitHub-first pilot still be valuable if broader connector scope comes later?
- What evidence would a reviewer need to see to trust the runtime path?

## Qualification Checklist

Advance only if most of these are true:

- there is a named workflow owner
- there is a named security or governance reviewer
- the first workflow can be kept GitHub-first or seeded-mock-first
- the team accepts a controlled self-hosted pilot instead of demanding managed SaaS
- the team understands this is not enterprise GA
- the team can run a production-style rehearsal environment
- the team can tolerate local auth or OIDC for pilot identity if SAML is not available
- the team does not require broad SCIM identity governance to start
- the team accepts Jira as optional second-phase scope
- the team accepts MCP staying off unless it is internal and tightly allowlisted
- the team is willing to run backup or restore and observability checks as part of pilot readiness

Disqualify or delay if any of these are true:

- they want unrestricted MCP as a broad enterprise tool bus
- they want compliance promises instead of a controlled pilot
- they have no reviewer staffing model
- they need HA, Kubernetes, or managed operations as day-one requirements
- they expect us to claim immutable evidence without destination-side WORM or Object Lock

## What Not To Promise

Do not promise:

- enterprise GA readiness
- managed SaaS operations
- compliance certification
- SAML support
- broad SCIM identity governance
- full external secret-manager coverage
- immutable evidence by default
- HA, Kubernetes, Helm, or Terraform maturity
- broad safe MCP enablement across unknown trust domains
- hands-off self-serve onboarding
- customer references unless you have explicit permission

## Recommended Call Flow

Use a simple founder-friendly structure:

1. Start with the pain, not the architecture.
2. Ask what real workflow they would govern first.
3. Confirm whether GitHub-first scope is acceptable.
4. Explain the product boundary: tool requests in, governed execution out.
5. Show the demo or evaluation path only after the workflow conversation is grounded.
6. Be explicit about what exists today versus what remains roadmap work.
7. End with one narrow next step, not an open-ended enterprise rollout discussion.

## Follow-Up Email Template

Use this after a positive first call:

```text
Subject: AgentGate design-partner next steps

Thanks for the conversation today.

Based on what we discussed, the most credible first evaluation looks like:

- workflow: [insert GitHub-first workflow]
- deployment shape: self-hosted controlled pilot
- reviewers: [insert owner/admin and security reviewer]
- connector scope: GitHub first, with Jira only if we deliberately opt it in later
- MCP posture: disabled unless we jointly review an internal, tightly allowlisted server

To keep this honest, we would frame the next phase as a controlled pilot rather than enterprise production rollout. The current product is strongest on runtime governance, approvals, traces, audit evidence, and self-hosted evaluation. It is not a managed SaaS offering, a compliance certification package, or a full identity-governance platform.

If the scope above still fits, the next step is to align on pilot success criteria, deployment ownership, and the minimal workflow we want to run end to end.
```

## Pilot Next-Step Language

Use this when the prospect is interested and you want to propose a concrete pilot:

```text
The next step I would recommend is not a broad rollout. It is a narrow controlled pilot.

We would keep the first live workflow GitHub-first, run the production-style self-hosted profile, apply the conservative pilot policy pack, validate deployment readiness, run one backup or restore drill, and make sure a real reviewer participates in at least one approval path.

If that works and your team still sees value, we can discuss whether Jira belongs in a second phase. We would keep MCP disabled unless there is a tightly scoped internal server and a clear reason to turn it on.
```

## Internal Use Notes

Before sending outreach:

- review [Pilot Readiness Review](../reviews/PILOT_READINESS_REVIEW.md)
- keep the pilot boundary aligned with [Pilot Scope](../reviews/PILOT_SCOPE.md)
- make sure the policy story is grounded in [Pilot Policy Pack](../operations/pilot-policy-pack.md)
- do not invite a partner into a live environment until the checks in [Pre-Pilot Preflight](PRE_PILOT_PREFLIGHT.md) are complete
