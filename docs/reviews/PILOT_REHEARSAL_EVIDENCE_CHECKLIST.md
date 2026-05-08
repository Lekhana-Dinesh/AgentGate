# Pilot Rehearsal Evidence Checklist

Use this checklist after a production-style rehearsal to make sure the team captured enough evidence to support a real go or no-go decision.

Do not attach secrets, tokens, cookies, private keys, or raw protected payloads.

## Core Command Outputs

- [ ] `python scripts/run-pilot-rehearsal.py` output for the intended environment
- [ ] `python scripts/validate-deployment.py` output or equivalent live validator output
- [ ] `python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json` output
- [ ] policy-pack dry-run or apply output
- [ ] `python scripts/check-no-live-secrets.py` output for the share package if docs changed

## Screenshots

- [ ] `/onboarding` or settings posture screenshot if part of the rehearsal story
- [ ] `/jobs` screenshot showing visible operator job state
- [ ] `/audit-integrity` screenshot
- [ ] `/scheduled-tasks` screenshot if recurring tasks are in scope
- [ ] `/audit-exports` screenshot if export is in scope
- [ ] `/users` or `/settings` screenshot if identity or readiness posture was reviewed

## Logs And Monitoring Evidence

- [ ] log location for `api`
- [ ] log location for `worker`
- [ ] log location for `scheduler` if enabled
- [ ] ingress or reverse-proxy log location if used
- [ ] `GET /v1/workers/status` evidence or screenshot
- [ ] Grafana or dashboard screenshots if observability is in scope
- [ ] alert-rule review note or screenshot

## Audit Integrity And Checkpoint Evidence

- [ ] audit-integrity verify output or status capture
- [ ] latest checkpoint verify output if external anchoring is enabled
- [ ] destination object or storage confirmation if external anchoring is enabled
- [ ] note confirming whether WORM or Object Lock exists or does not exist

## Restore Drill Evidence

- [ ] restore drill notes
- [ ] actual RTO captured
- [ ] recovery gaps captured
- [ ] post-restore validator output
- [ ] post-restore audit-integrity check result

## API And Browser Coverage

- [ ] API evaluation notes or saved output
- [ ] browser E2E result if run
- [ ] GitHub Actions or CI result links relevant to the release or rehearsal

## Governance And Scope Evidence

- [ ] connector scope freeze note
- [ ] GitHub allowlist review note
- [ ] Jira allowlist review note if Jira is in scope
- [ ] MCP restriction review note if MCP is in scope
- [ ] reviewer staffing confirmation
- [ ] approval-path exercise evidence

## Limitations Acknowledged

- [ ] controlled-pilot, not enterprise GA
- [ ] no compliance claim
- [ ] no immutability claim without destination-side WORM or equivalent
- [ ] no managed SaaS claim
- [ ] no HA, Kubernetes, or Terraform maturity claim by default

## Final Packaging

- [ ] completed [PILOT_REHEARSAL_REPORT_TEMPLATE.md](PILOT_REHEARSAL_REPORT_TEMPLATE.md)
- [ ] evidence links or file paths added to the report
- [ ] known failures recorded
- [ ] risk decisions recorded
- [ ] go, conditional go, or no-go recommendation recorded
