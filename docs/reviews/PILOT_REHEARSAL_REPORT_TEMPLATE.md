# Pilot Rehearsal Report Template

Use this template after a real production-style rehearsal.

This document is for recording evidence, gaps, and operator decisions after a rehearsal has actually been run.

Do not mark sections as passed unless the relevant command, check, or review really happened.
Do not paste secrets, tokens, cookies, private keys, or raw protected payloads into this report.

## Summary

- Rehearsal date:
- Prepared by:
- Reviewers present:
- Environment type:
  - Example: local demo, isolated staging, production-style self-hosted pilot rehearsal
- Commit or tag tested:
- Deployment mode:
  - Example: `compose.prod.example.yml` baseline with external Postgres and Redis
- Overall recommendation:
  - `go`
  - `conditional go`
  - `no-go`

## Environment Profile

- Public app URL:
- Public API URL:
- Tenant slug tested:
- PostgreSQL mode:
  - Example: external managed PostgreSQL, restored isolated PostgreSQL, local Compose PostgreSQL
- Redis mode:
  - Example: external Redis, local Redis, inline fallback not used
- Key provider or KMS mode:
  - Example: `env`, `aws_kms`
- Browser session mode:
  - Example: `token`, `cookie`
- Rate-limit provider:
  - Example: `in_memory`, `redis`
- Worker mode:
  - Example: dedicated worker service, inline not used
- Scheduler mode:
  - Example: dedicated scheduler service enabled, scheduler not in scope

## Connector Scope

- GitHub in scope:
- Jira in scope:
- MCP in scope:
- Mock or demo tools in scope:
- Any additional connectors or integrations in scope:
- Connector allowlist notes:
- Scope-freeze decision:

## Policy Pack And Governance Results

### Policy Pack Validation

- Command run:
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
  - `SKIP`
- Validator output summary:
- Dry-run or apply path used:
- Reviewer coverage confirmed:
- Notes:

### Governance Coverage Notes

- Approval-required flows exercised:
- Destructive-action blocking reviewed:
- MCP restrictions reviewed if applicable:
- Connector allowlist alignment reviewed:
- Notes:

## Deployment Validation Result

- Command run:
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
- Metrics checked:
- Session mode observed:
- Key findings:
- Notes:

## API Evaluation Result

- API evaluation collection used:
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
  - `SKIP`
- Requests exercised:
- Any manual-only requests used:
- Notes:

## Browser E2E Result

- Browser E2E run:
  - `yes`
  - `no`
- Command or workflow used:
- Result if run:
  - `PASS`
  - `WARN`
  - `FAIL`
- Scope covered:
- Notes:

## Backup And Restore Drill Result

- Restore drill run:
  - `yes`
  - `no`
- Date of drill:
- Environment restored into:
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
  - `SKIP`
- Actual RTO observed:
- Recovery gaps found:
- Notes:

## Audit Integrity And Checkpoint Evidence

### Audit-Integrity Verification Result

- Verification path used:
  - Example: `GET /v1/audit-integrity/status`, `POST /v1/audit-integrity/verify`
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
- Range or tenant reviewed:
- Findings:
- Notes:

### External Checkpoint Verification Result

- External anchoring enabled:
  - `yes`
  - `no`
- Verification path used:
  - Example: latest checkpoint verify plus destination object check
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
  - `SKIP`
- Destination posture reviewed:
  - Example: object versioning, Object Lock, or equivalent
- Findings:
- Notes:

## Observability And Operator Health

### Observability Or Alert Check

- `/ready` monitored:
- `/metrics` internal-only confirmed:
- Logs reviewed:
- Grafana or dashboard review completed:
- Alert rules loaded or reviewed:
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
- Notes:

### Worker And Scheduler Status

- `GET /v1/workers/status` reviewed:
- Worker healthy:
- Scheduler healthy:
- Dead-letter or retry issues observed:
- Result:
  - `PASS`
  - `WARN`
  - `FAIL`
- Notes:

## Known Failures

- Failure 1:
- Failure 2:
- Failure 3:

If none:

- No known failures beyond documented limitations.

## Risk Decisions

- Risk accepted:
- Owner of risk decision:
- Why the risk is acceptable for a controlled pilot:
- Expiration or revisit date:

Repeat for each material risk accepted during rehearsal.

## Required Fixes Before Partner Access

- Fix 1:
- Owner:
- Due before partner access:

- Fix 2:
- Owner:
- Due before partner access:

## Go / No-Go Recommendation

- Recommendation:
  - `go`
  - `conditional go`
  - `no-go`
- Reasoning:
- Conditions required before moving to `go` if not already there:

## Evidence Links, Screenshots, And Log Locations

- Deployment validator output:
- Pilot rehearsal output:
- Policy pack validation output:
- Policy pack dry-run or apply output:
- API evaluation notes or exported request log:
- Browser E2E run or workflow link:
- Restore drill notes:
- Audit-integrity verify output:
- Checkpoint verify output:
- Grafana or monitoring screenshots:
- Worker or scheduler screenshots:
- Relevant log locations:
- Related ticket, issue, or runbook link:

## Limitations Acknowledged In This Rehearsal

- AgentGate remains controlled-pilot ready, not enterprise GA.
- This rehearsal is not a compliance certification.
- External checkpointing is not an immutability claim unless the destination enforces WORM or equivalent controls.
- Self-hosted Compose is not HA, Kubernetes, Helm, or Terraform maturity by itself.
- Any additional environment-specific limitations acknowledged during the rehearsal:
