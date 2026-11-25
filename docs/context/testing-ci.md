# Testing And CI Context

## 1. Purpose

This file summarizes AgentGate's verification commands, CI gates, security scanning, and opt-in browser and load-testing foundations.

## 2. Main files/directories

- `.github/workflows/ci.yml`
- `.github/workflows/quality-security.yml`
- `.github/workflows/secret-scan.yml`
- `.github/workflows/e2e-manual.yml`
- `.github/workflows/terraform-ecs-validate.yml`
- `Makefile`
- `scripts/check-no-live-secrets.py`
- `scripts/validate-deployment.py`
- `api-collections/http/AgentGate/`
- `apps/api/app/tests/`
- `apps/web/e2e/`
- `load-tests/k6/`

## 3. Current capabilities

- Blocking CI for backend compile and tests, frontend build, and Compose validation
- Blocking quality and security gates for Ruff, Bandit, `npm audit` high+, Trivy filesystem scanning, and Gitleaks
- Advisory `pip-audit`
- Alembic migration smoke coverage in CI
- Opt-in Playwright browser E2E for the main operator surfaces plus k6 regression scripts
- Manual API evaluation collection for design-partner and technical reviewer workflows without turning those requests into a blocking CI gate
- Internal pilot rehearsal wrapper that reuses the secret scan, pilot policy-pack validator, deployment validator, and artifact presence checks
- Repo secret-surface checking for docs, config, and workflow changes
- Deployment validation help and Compose validation for operator-facing deployment tooling changes
- A dedicated Linux GitHub Actions path for `deploy/aws/ecs` Terraform `fmt -check`, `init -backend=false`, and `validate` without AWS credentials
- Optional local Terraform format and validation helpers for the ECS/Fargate deployment starter

## 4. Critical invariants / must-not-break rules

- Do not casually weaken blocking CI gates.
- Keep docs, workflow commands, and local verification guidance aligned.
- If you change public docs, env examples, or config surfaces, run `python scripts/check-no-live-secrets.py`.
- Keep fake credentials obviously fake in tests and docs.
- If an area has targeted tests, prefer running those before broader suites when the task is narrow.
- Deployment validation is a manual operator tool; keep it opt-in and avoid turning it into a default PR gate.
- Pilot rehearsal is also an internal operator tool; keep it useful for release or pilot prep without turning it into a noisy default CI gate.

## 5. Security boundaries

- CI scanners are guardrails, not substitutes for manual review.
- Secret scanning is especially important for docs, screenshots, example payloads, workflows, and Compose files.
- Dependency and static scans should stay conservative and low-noise enough to remain usable.

## 6. Known limitations

- `pip-audit` is advisory rather than blocking.
- Playwright is opt-in and not part of the default blocking PR path, even though the manual suite now covers more operator pages.
- The API evaluation collection is for manual reviewer workflows, not a CI or smoke-test replacement.
- k6 scripts are regression tripwires, not production capacity proof.
- The Terraform ECS validation workflow proves module syntax and provider-schema compatibility on Linux, not AWS account readiness or deployment safety.
- There is no full visual-regression or cross-browser matrix.

## 7. Relevant tests

- `apps/api/app/tests/*`
- `apps/web/e2e/*`
- `load-tests/k6/*.js`
- `python scripts/check-no-live-secrets.py`
- `python scripts/validate-deployment.py --help`
- `python scripts/run-pilot-rehearsal.py --help`
- `make aws-ecs-fmt`
- `make aws-ecs-validate`
- `.github/workflows/terraform-ecs-validate.yml`

## 8. When future Codex sessions should read this file

Read this before editing workflows, verification commands, tests, security tooling, load scripts, or public docs and config examples.
