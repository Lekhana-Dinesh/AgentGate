# Design Partner Evaluation

## Purpose

Use this guide when a prospective design partner or technical reviewer wants to run AgentGate and evaluate whether it is credible for controlled enterprise agent workflows.

For internal founder and operator preparation before outreach, use [Design Partner Outreach](../go-to-market/DESIGN_PARTNER_OUTREACH.md) and [Pre-Pilot Preflight](../go-to-market/PRE_PILOT_PREFLIGHT.md). Those are internal planning materials, not buyer-facing leave-behinds.

## Who Should Evaluate

The best evaluation group usually includes:

- an AI product or platform owner
- a security or governance reviewer
- an infrastructure or platform engineer
- an application engineer who owns a real agent workflow
- an integration owner for GitHub and, if relevant, Jira or an internal MCP server

## Prerequisites

- a local machine that can run Docker Compose, Python, and Node, or a self-hosted environment for the production-style profile
- ability to run the seeded demo environment
- willingness to evaluate both runtime control behavior and operational reality

Optional but useful:

- a GitHub test repository or GitHub App installation
- an internal Jira test project if Jira is part of the evaluation
- an internal allowlisted HTTP MCP server only if MCP is part of the evaluation
- a Slack workspace for notification testing
- an S3-compatible object store for external audit checkpoint evaluation

## Local Setup

Fastest local path:

1. Copy `.env.example` to `.env`.
2. Run `docker compose up --build`.
3. Seed the demo tenant with `docker compose exec api python -m app.db.seed`.
4. Log in to `http://localhost:3000` with the demo admin.
5. Open `/onboarding` before the live scenario so the team sees current setup posture without inspecting secrets or raw config.

Local evaluation works well for:

- control-plane UX review
- approval and trace flows
- audit integrity and checkpoint basics
- retention dry runs
- job and scheduled-task behavior
- direct API review with the plain-file collection in `api-collections/http/AgentGate/`
- review of the conservative pilot policy starter pack before a real pilot tenant is opened up

## Self-Hosted Setup

Production-style evaluation path:

1. Review `compose.prod.example.yml`.
2. Read [Self-Hosted Deployment](../operations/self-hosted-deployment.md).
3. Point AgentGate at external PostgreSQL and Redis.
4. Use `AGENTGATE_KEY_PROVIDER=aws_kms` if you want the stronger payload-protection path.
5. Use `AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage` if you want the stronger external-checkpoint story.

This path is better for teams evaluating:

- deployment model fit
- readiness and metrics posture
- worker and scheduler expectations
- AWS KMS and external checkpoint configuration shape

For the first serious evaluation, keep the live workflow GitHub-first. Treat Jira as a constrained second-phase connector and leave MCP disabled unless you control the remote server and can keep its tool allowlist narrow.

## Evaluation Checklist

- Can the team explain what happens before a tool call is allowed to reach an external system?
- Does onboarding give a truthful first-run picture without pretending to auto-configure the platform?
- Can the reviewer find approval, job, trace, and audit evidence for one risky scenario?
- Are sanitized payload views understandable without leaking secrets?
- Can the team see how retention reduces replayable sensitive execution state?
- Can the team verify the audit chain and understand what checkpointing does and does not prove?
- Can the team see a credible self-hosted deployment path?
- Can the team identify where a future integration or control would plug in without rewriting the product?

## Security Questions

- Which secrets stay out of the database today?
- Which execution payload fields are protected at rest?
- How are deactivated users and revoked user-created agent API keys handled?
- What exactly is audited, and what is intentionally sanitized?
- What does the audit hash chain prove?
- What extra evidence protection comes from external checkpointing?
- Which controls are runtime enforcement versus documentation or operator procedure?

## Integration Questions

- Which real connectors exist today, and which are still mock or future work?
- Which parts of setup still require docs, deployment config, or admin APIs outside the onboarding page?
- Does the GitHub connector support the auth mode we would actually want to use?
- How would we add another governed connector without bypassing the gateway?
- Can we route audit history to our SIEM with sanitized data only?
- How would we run approvals, jobs, scheduler, and retention in our target environment?

## Success Criteria

An evaluation is successful if the team can say:

- "We understand the runtime control path."
- "We can see where approvals and policies fit into a real workflow."
- "We trust the product more because the traces, jobs, and audit evidence are inspectable."
- "We understand the current limitations and they are acceptable for a design-partner phase."
- "We can see a path from local proof-of-value to self-hosted evaluation."

If the team wants to move beyond evaluation, use the pilot guardrails in [Pilot Readiness Review](../reviews/PILOT_READINESS_REVIEW.md) and [Pilot Scope](../reviews/PILOT_SCOPE.md) before framing the next phase as a real controlled pilot.

Review and apply the default pilot pack in [Pilot Policy Pack](../operations/pilot-policy-pack.md) so approval coverage is not left to ad hoc manual setup.

## Known Limitations

- This is not a compliance certification package.
- The current deployment profile is self-hosted and Compose-based, not a managed SaaS or Kubernetes platform.
- GitHub is the best first live connector today.
- Jira is better treated as a constrained second-phase option than a default day-one commitment.
- MCP is a narrow HTTP foundation and should stay disabled by default unless the server is internal and tightly allowlisted.
- Minimal SCIM Users provisioning exists, but broad SCIM identity governance, SAML, and broader external secret-manager integrations are not complete.
- External checkpointing is stronger than database-only integrity, but it is not full immutability unless the destination enforces WORM or Object Lock semantics.
- Browser E2E and load-testing foundations exist, but they are intentionally lightweight.
- Onboarding is a safe status-and-navigation layer, not a full setup wizard or a connector secret-management UI.

## Feedback Form And Questions

Ask evaluators to answer these questions after the review:

1. What real agent workflow would you test first with AgentGate?
2. Which current control is most compelling?
3. Which missing control blocks broader adoption?
4. Is the self-hosted deployment story credible for your team?
5. Which connector or identity feature would you need next?
6. Did the audit and approval evidence feel strong enough for reviewer workflows?
7. What would prevent you from moving from demo to a scoped design-partner pilot?

## Recommended Use Order

1. Start with [Enterprise Demo Guide](ENTERPRISE_DEMO_GUIDE.md).
2. Run the live flow in [Demo Script](DEMO_SCRIPT.md).
3. Capture artifacts with [Screenshot Checklist](SCREENSHOT_CHECKLIST.md).
4. Hand over [API Evaluation](../operations/api-evaluation.md) for technical reviewers who want to exercise the control-plane APIs directly.
5. If the review is positive, align on [Pilot Scope](../reviews/PILOT_SCOPE.md) before treating the next step as a controlled pilot.
6. Review [Pilot Policy Pack](../operations/pilot-policy-pack.md) before enabling real pilot connectors or traffic.
7. Use this document as the leave-behind evaluation worksheet.
