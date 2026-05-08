# Release Checklist

Use this checklist before tagging or sharing an AgentGate release with private reviewers, design partners, or internal pilot operators.

This is a lightweight pre-1.0 process. It is meant to create consistency, not to imply enterprise GA, managed SaaS operations, or automated release engineering.

## Release Naming

Use pre-1.0 semantic-version-style tags:

- `v0.x.y`

Suggested intent:

- bump `y` for small docs, packaging, or low-risk operator-surface changes
- bump `x` for materially broader controlled-pilot scope, new operator workflows, or notable evaluator-facing capability additions

For now, treat every `v0.x.y` tag as pre-1.0.

If a release is intended for private reviewers or a narrow design-partner motion, call it a `controlled-pilot release`.

Do not describe a release as:

- enterprise GA
- compliance-ready
- managed SaaS
- HA-ready by default

## Before You Tag

Confirm the release goal:

- docs-only hygiene release
- private technical review package
- controlled-pilot release for a real high-touch pilot motion

Freeze the story before tagging:

- GitHub-first if the release is meant for live pilot discussion
- Jira only if you are intentionally offering constrained second-phase scope
- MCP off by default unless the release clearly documents internal-only and tightly allowlisted use

## Changelog And Docs

- update [CHANGELOG.md](../../CHANGELOG.md)
- add or refine the high-level release notes under `Unreleased`
- make sure README, pilot docs, and evaluator docs still describe the same product posture
- make sure no doc drifts into enterprise GA, compliance, immutability, or managed-platform claims
- confirm demo/evaluation docs still match the real pilot boundary

## Local Release Check

Run the lightweight local helper:

```bash
make release-check
```

Today that wraps:

- `python scripts/check-no-live-secrets.py`
- `python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json`
- `python scripts/run-pilot-rehearsal.py --skip-live-api`

This is a repo-package check, not a proof that a running environment is pilot-ready.

## CI And Verification

Before tagging, review the current CI posture:

- `.github/workflows/ci.yml`
- `.github/workflows/quality-security.yml`
- `.github/workflows/secret-scan.yml`

Expected baseline:

- backend compile and tests pass
- frontend build passes
- `docker compose config` passes
- quality and security workflows stay green or intentionally reviewed if advisory-only

If the change area warrants it, also run the relevant manual checks:

- `make prod-config-check`
- `make e2e`
- targeted k6 scripts

## Policy Pack And Secret Hygiene

- run `python scripts/check-no-live-secrets.py`
- run `python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json`
- confirm any policy-pack docs and pilot guidance still match the shipped pack
- confirm no example, screenshot, or workflow file contains live credentials

## Pilot Rehearsal

Always run the repo-package rehearsal:

```bash
python scripts/run-pilot-rehearsal.py --skip-live-api
```

If the release will support a real pilot environment, also run the live rehearsal against that environment:

```bash
python scripts/run-pilot-rehearsal.py \
  --api-url https://api.agentgate.example.com \
  --web-url https://agentgate.example.com \
  --tenant-slug customer-tenant \
  --email owner@example.com \
  --password '<password>'
```

Before any controlled-pilot tag or shared release that will be used for real partner access, require these artifacts:

- completed [Pilot Rehearsal Report Template](../reviews/PILOT_REHEARSAL_REPORT_TEMPLATE.md)
- completed [Pilot Rehearsal Evidence Checklist](../reviews/PILOT_REHEARSAL_EVIDENCE_CHECKLIST.md)
- links to the captured validator, policy-pack, restore, and audit-integrity evidence referenced by that report

## Deployment Validation

If the release is intended for a running environment:

- run `python scripts/validate-deployment.py` directly or through the rehearsal runner
- confirm the real environment shape matches the release story
- do not treat repo-only checks as enough for partner traffic

## Backup And Restore

If the release will be used for a controlled pilot:

- confirm one restore drill has been completed recently enough to trust the current runbook
- confirm `make verify-restore` succeeds in the recovery environment
- confirm audit-integrity follow-up checks were completed after restore
- confirm checkpoint verification was reviewed if external anchoring is in scope

Do not tag a pilot-facing release as "ready" if restore discipline is still hypothetical.
Do not tag a pilot-facing release as "ready" if the rehearsal report and evidence package do not exist.

## Docs Consistency Check

Before tagging, skim these docs together:

- `README.md`
- `CHANGELOG.md`
- `docs/reviews/PILOT_READINESS_REVIEW.md`
- `docs/go-to-market/PRE_PILOT_PREFLIGHT.md`
- `docs/reviews/PRIVATE_RELEASE_CANDIDATE_REVIEW.md`

Look for drift around:

- controlled-pilot versus GA language
- GitHub-first versus broader connector claims
- audit integrity versus immutability wording
- backup guidance versus DR automation wording
- self-hosted Compose versus HA/Kubernetes expectations

## Tag And Release Steps

Suggested lightweight flow:

1. finish the doc and verification pass
2. update `CHANGELOG.md`
3. commit the release-ready state
4. create an annotated tag such as `v0.3.0`
5. prepare a short release note or private-share note using the changelog plus current limitations
6. send only the curated review package appropriate for the audience

Keep the release note short and honest:

- what changed
- what the release is for
- what is still out of scope

## Rollback Notes

If a release tag turns out to overstate readiness or ship confusing evaluator material:

- stop sharing that tag or release note
- correct the docs and changelog
- cut a follow-up `v0.x.y` tag rather than rewriting history
- if a live pilot environment is involved, re-run deployment validation, pilot rehearsal, and restore-check expectations after the corrective change

Do not use changelog or release-note language to paper over a real pilot-readiness gap.
