# Pilot Rehearsal

Use the pilot rehearsal runner before partner outreach, before a live demo tied to a real environment, and before calling a controlled-pilot deployment ready.

The goal is to give the team one repeatable internal command that checks the repo package, core pilot artifacts, and an optional running environment without pretending to prove enterprise production readiness.

## What It Runs

The rehearsal runner is `scripts/run-pilot-rehearsal.py`.

It reuses existing safe checks where possible:

- `python scripts/check-no-live-secrets.py`
- `python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json`
- `python scripts/validate-deployment.py` when live deployment inputs are provided
- `python scripts/check-recovery-readiness.py` when you are preparing a restore drill or upgrade window
- required-doc and artifact presence checks for pilot docs, API evaluation files, policy-pack files, and observability starter assets

It does not call external connectors, create audit checkpoints, run retention purge, or mutate connector credentials.

When live deployment validation runs, the rehearsal wrapper also preserves the validator's redacted evidence summary so operators can capture one safe snapshot of:

- health and readiness posture
- worker availability
- GitHub connector readiness and probe status
- audit-integrity checkpoint posture
- metrics-path warnings or internal-only notes

## When To Run It

Run rehearsal:

- before design-partner outreach that points reviewers at the repo
- before a founder-led or operator-led live demo
- after significant pilot-doc or deployment-tooling changes
- before declaring a self-hosted environment internally pilot-ready
- after major packaging, auth, or policy-pack changes that could affect the pilot story

## Commands

Repo-only or docs-first rehearsal:

```bash
python scripts/run-pilot-rehearsal.py --skip-live-api
```

Local seeded stack rehearsal:

```bash
python scripts/run-pilot-rehearsal.py --local
```

Or from the repo root:

```bash
make pilot-rehearsal-local
```

Production-style environment rehearsal:

```bash
python scripts/run-pilot-rehearsal.py \
  --api-url https://api.agentgate.example.com \
  --web-url https://agentgate.example.com \
  --tenant-slug customer-tenant \
  --email owner@example.com \
  --password '<password>'
```

Optional skips:

- `--skip-live-api`
- `--skip-policy-pack`
- `--skip-doc-checks`

## Inputs

Live deployment validation needs:

- `--api-url`
- `--web-url`
- `--tenant-slug`
- `--email`
- `--password`

`--local` fills these with the seeded local demo defaults unless you override them explicitly.

## PASS, WARN, And FAIL

- `PASS`: all automated checks passed and no required step was skipped
- `WARN`: automated checks passed, but one or more checks were skipped, usually because live validation was intentionally not run
- `FAIL`: one or more automated checks failed

Treat `WARN` as acceptable for repo-package review. Do not treat it as enough for a real partner environment if live deployment validation was skipped.

## What It Proves

The rehearsal runner is useful for confirming:

- the repo package still contains the expected pilot docs and evaluation artifacts
- public docs and examples do not contain obvious live-secret patterns
- the default pilot policy pack still validates cleanly
- a running AgentGate environment can pass the existing safe deployment smoke validator when credentials are provided
- a running AgentGate environment can emit a redacted evidence summary for operator review and rehearsal records

## What It Does Not Prove

The rehearsal runner does not prove:

- worker throughput or scheduler liveness beyond the existing deployment validator surface
- GitHub, Jira, MCP, Slack, OIDC, SCIM, AWS, or other external integrations
- backup retention, restore success, or disaster-recovery readiness by itself
- audit-checkpoint survivability in external storage
- HA, Kubernetes, Helm, Terraform, or managed-operations maturity
- compliance, immutability, or enterprise-GA readiness

Use `scripts/check-recovery-readiness.py` separately when you want non-destructive PASS or WARN or FAIL output for:

- backup confirmation
- restore-target readiness
- rollback decision points
- Redis recovery expectations
- audit-checkpoint recovery review
- redacted recovery evidence capture

## Required Manual Follow-Ups

Before partner traffic, still do all of the following:

- run one production-style rehearsal using the intended deployment shape
- complete one restore drill in an isolated environment
- verify audit-integrity status and the latest checkpoint after restore or before launch
- dry-run or apply the pilot policy pack against the real tenant after reviewing allowlists
- confirm owner or admin plus security reviewer staffing
- freeze connector scope so GitHub stays first, Jira stays optional, and MCP stays off by default unless explicitly reviewed

After a production-style rehearsal actually happens, record the result with:

- [Pilot Rehearsal Report Template](../reviews/PILOT_REHEARSAL_REPORT_TEMPLATE.md)
- [Pilot Rehearsal Evidence Checklist](../reviews/PILOT_REHEARSAL_EVIDENCE_CHECKLIST.md)

Treat those as the evidence package that moves the team from repo-package ready to rehearsal-evidence ready.

## Related Docs

- [Deployment Validation](deployment-validation.md)
- [Self-Hosted Evaluation](self-hosted-evaluation.md)
- [Backup And Restore](backup-and-restore.md)
- [Pilot Policy Pack](pilot-policy-pack.md)
- [API Evaluation](api-evaluation.md)
- [Pilot Rehearsal Report Template](../reviews/PILOT_REHEARSAL_REPORT_TEMPLATE.md)
- [Pilot Rehearsal Evidence Checklist](../reviews/PILOT_REHEARSAL_EVIDENCE_CHECKLIST.md)
- [Pilot Readiness Review](../reviews/PILOT_READINESS_REVIEW.md)
- [Pilot Scope](../reviews/PILOT_SCOPE.md)
- [Pre-Pilot Preflight](../go-to-market/PRE_PILOT_PREFLIGHT.md)
