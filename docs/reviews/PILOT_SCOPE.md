# Pilot Scope

Review date: 2026-05-07

This document defines the recommended first controlled-pilot scope for AgentGate.

The goal is to prove runtime governance value without overextending the product into areas that still need more platform maturity.

## Target Buyer And Team

Best-fit first pilot team:

- AI platform or developer-platform team
- engineering productivity or internal tooling owner
- security or governance reviewer willing to participate in approval and audit review
- one hands-on integration owner for GitHub and, if needed, Jira

This is a poor first pilot for teams expecting turnkey SaaS operations, broad self-serve onboarding, or immediate compliance packaging.

## Allowed Use Cases

Recommended day-one use cases:

- GitHub repository metadata reads for internal engineering workflows
- pull-request and issue review workflows that require runtime governance before side effects
- governed GitHub issue creation or commenting for internal or trusted repositories
- approval-driven demonstrations of risky or externalized actions using the seeded mock or demo flows
- audit-integrity, retention dry-run, and operator-evidence review as part of the pilot story

Optional later-phase use cases after the first workflow is stable:

- Jira reads and tightly scoped issue creation or comments in internal or non-customer-facing projects
- Jira transitions only when transition allowlists and approval policies are already tuned
- MCP calls only to internally controlled HTTP MCP servers with narrow allowlists and explicit approval policies

## Recommended Connectors

Recommended by default:

- GitHub
- Mock tools for demo and rehearsal

Allowed only as explicit opt-in:

- Jira with narrow project, issue-type, transition, and assignee allowlists

Disabled by default for the first pilot unless there is a strong internal justification:

- MCP to external or unknown trust domains

## Recommended Deployment Mode

Use the self-hosted production-style profile, not the local developer stack:

- `compose.prod.example.yml` as the operational baseline
- external PostgreSQL
- external Redis
- dedicated `worker`
- dedicated `scheduler` if recurring tasks are enabled
- `AGENTGATE_AUTH_SESSION_MODE=cookie` for browser operators
- `AGENTGATE_RATE_LIMIT_PROVIDER=redis`
- `AGENTGATE_ALLOW_DEMO_CREDENTIALS=false`

Preferred security posture:

- `AGENTGATE_KEY_PROVIDER=aws_kms`
- `AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage` if you want stronger external checkpointing
- destination-side versioning plus Object Lock or equivalent WORM controls if you need stronger evidence-retention claims

Before partner traffic, run `python scripts/run-pilot-rehearsal.py` against the intended environment.
Treat that as a lightweight operator wrapper around the existing validators and artifact checks, not as a substitute for the restore drill below.

## Required Operator Roles

Minimum human roles for the pilot:

- one `owner` or `admin` responsible for deployment and connector configuration
- one `security_reviewer` responsible for approval and audit review
- one engineering workflow owner who validates the business use case

Optional:

- one developer or platform engineer who tests API and gateway flows directly

Do not run the pilot with only a single technical user and no reviewer role coverage.

## Required Monitoring

Before pilot traffic:

- monitor `GET /ready`
- keep `GET /metrics` internal-only and scraped by Prometheus or equivalent
- collect structured logs for `api`, `worker`, `scheduler`, and ingress
- monitor `GET /v1/workers/status`
- load the starter alert rules or a stricter internal equivalent

Minimum alert focus:

- API down or unreadiness
- sustained 5xx rate
- rate-limiter backend errors
- dead-letter or retry-exhausted job increases
- scheduler errors
- audit export failures

## Required Backup And Restore Drill

Before calling the environment pilot-ready:

1. restore PostgreSQL into an isolated environment
2. restore or confirm external checkpoint storage if anchoring is enabled
3. inject the same secret-manager and KMS configuration shape used for the pilot
4. start `api`, `web`, `worker`, and `scheduler`
5. run `make verify-restore`
6. verify `GET /v1/audit-integrity/status`
7. verify the latest checkpoint if external anchoring is enabled
8. record actual RTO and operational gaps

## Required Security Review

Before launch, complete a focused review of:

- the default pilot policy pack and any local overrides
- connector allowlists and trust-domain settings
- approval-required policy coverage for side-effecting writes
- cookie-session configuration, CSRF posture, and public URL alignment
- secret injection model and who can access runtime credentials
- GitHub auth mode, preferably GitHub App instead of long-lived personal tokens
- audit-anchor destination posture and whether WORM or Object Lock is in scope
- backup retention, restore ownership, and incident contacts

## Success Criteria

Treat the pilot as successful only if all of the following are true:

- at least one real workflow runs end to end through the governed gateway
- at least one approval path is exercised and reviewed by a human reviewer
- the default pilot policy pack has been reviewed and applied or deliberately replaced
- operators can inspect jobs, traces, audit events, and audit-integrity status without secret leakage
- the deployment validator passes in the real pilot environment
- one backup or restore drill completes successfully
- the partner team understands current limitations and still wants to continue

## Rollback And Exit Criteria

Rollback or exit the pilot if any of the following occur:

- repeated failures or dead-letter growth on the core pilot workflow
- inability to complete restore verification
- connector scope expands beyond the documented allowlists without a new security review
- the partner requires unsupported capabilities such as SAML, broad SCIM lifecycle automation, self-serve connector secret management, or HA guarantees
- pilot claims start drifting toward compliance or immutability promises that the deployment cannot support
- reviewer fatigue or approval noise makes the workflow operationally unacceptable

Operational rollback steps should include:

- revoke or disable external connector credentials
- disable or narrow the pilot connectors
- stop scheduled tasks that are not required
- preserve audit evidence and job records for review
- remove or quarantine the environment if the pilot is terminated
