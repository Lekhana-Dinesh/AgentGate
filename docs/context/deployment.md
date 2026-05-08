# Deployment Context

## 1. Purpose

This file covers local and self-hosted deployment surfaces, environment validation, Compose profiles, and production-minded operator expectations.

## 2. Main files/directories

- `docker-compose.yml`
- `compose.prod.example.yml`
- `scripts/validate-deployment.py`
- `apps/api/app/core/config.py`
- `apps/api/app/services/readiness_service.py`
- `docs/operations/backup-and-restore.md`
- `docs/operations/deployment-hardening.md`
- `docs/operations/self-hosted-deployment.md`
- `docs/operations/production-runbook.md`
- `docs/operations/production-readiness-checklist.md`

## 3. Current capabilities

- Local Compose stack for API, web, worker, Postgres, and Redis
- Separate self-hosted production-style Compose profile using external Postgres and Redis
- Production-minded config validation for secrets, URLs, rate limiting, key provider setup, and audit-anchor mode
- Optional production-minded browser session hardening with secure cookie validation and CSRF requirements
- Optional tenant-scoped SCIM bearer-token bindings through env or secret-ref-style configuration
- Dedicated worker and scheduler deployment path
- AWS KMS-backed payload protection support
- Object-storage external audit anchoring support for production-minded checkpointing
- Post-start deployment validation for health, readiness, login, and safe operator API reachability
- Lightweight pilot rehearsal runner that wraps the secret scan, pilot policy-pack validation, deployment validator, and required artifact checks
- Operator guidance for PostgreSQL backup scope, restore order, and post-restore validation using the existing deployment validator plus audit-integrity follow-up checks

## 4. Critical invariants / must-not-break rules

- Do not weaken production validation to make unsafe configs pass silently.
- Cookie mode outside development/test must keep secure cookies and CSRF enabled.
- SCIM token bindings must remain runtime-injected secret references, not literal secrets in repo files or database config.
- Production-like environments must not rely on local-file audit anchoring.
- Keep public app and API URLs aligned with real externally reachable origins.
- Do not store runtime credentials in git-tracked files or database config.
- Do not treat PostgreSQL backup alone as complete recovery if external audit-anchor storage, KMS access, or deployment-level secrets are not recoverable.
- Redis remains an accelerator and distributed limiter backend, while the database remains the durable job source of truth.

## 5. Security boundaries

- TLS termination is expected outside AgentGate.
- Cookie-session deployments depend on correct external HTTPS origins and cookie settings.
- SCIM bearer tokens are deployment-level secrets and are intentionally separate from browser auth.
- `/metrics` should remain on an internal path where possible.
- Secret injection belongs to environment or secret-manager workflows, not repo files.
- Worker, scheduler, and audit-anchor credentials are deployment-level concerns, not tenant secrets.
- Backup archives and restore workflows belong to operator infrastructure, not application runtime state.

## 6. Known limitations

- The production deployment story is Compose-based, not Kubernetes, Helm, or Terraform.
- Readiness does not fully prove worker or scheduler liveness.
- The deployment validator is a smoke test only; it does not prove worker throughput, scheduler progress, or external connector reachability.
- The pilot rehearsal runner is an operator wrapper, not a replacement for production-style rehearsal, restore drills, or checkpoint verification.
- Backup and restore remain operator-managed. AgentGate does not schedule backups or verify external backup retention for you.
- The limiter is fixed-window and not yet proxy-trust-aware.
- SCIM token rotation is deployment-managed only in the current build; there is no tenant-admin token issuance UI or API.
- External checkpoint anchoring is stronger than DB-only evidence, but not immutable without destination-side WORM or Object Lock.
- Cookie mode is intended for browser operators. Bearer and API-key flows still matter for machine clients and automation.

## 7. Relevant tests

- `docker compose config`
- `docker compose -f compose.prod.example.yml config`
- `python scripts/validate-deployment.py --help`
- `python scripts/run-pilot-rehearsal.py --help`
- `make verify-restore`
- `apps/api/app/tests/test_operational_hardening.py`
- `apps/api/app/tests/test_scim.py`
- `apps/api/app/tests/test_session_hardening.py`
- Backend compile and migration smoke in `.github/workflows/ci.yml`

## 8. When future Codex sessions should read this file

Read this before editing env vars, Compose files, startup validation, readiness expectations, deployment docs, or production operator guidance.
