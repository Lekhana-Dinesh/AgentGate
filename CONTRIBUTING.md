# Contributing

AgentGate is a production-minded control plane for enterprise AI agents. Contributions should preserve the existing runtime governance model rather than bypass it for convenience.

Future Codex sessions should read `docs/AGENTGATE_CODEX_HANDOFF.md` first, then read only the relevant `docs/context/*.md` files before editing.

## Engineering Principles

- Keep the runtime decision path deterministic, testable, and fail-closed.
- Preserve tenant isolation in every query, service, API response, and background job.
- Never bypass gateway authorization, policy, risk, approval, audit, or trace controls.
- Do not expose decrypted payloads, raw secrets, or tokens in code, logs, fixtures, screenshots, or docs.
- Document limitations honestly when a feature is partial, local-only, or still scaffolding.

## Local Setup

### Backend

```bash
cd apps/api
python -m pip install -e .[dev]
python -m alembic upgrade head
python -m app.db.seed
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Optional worker

```bash
cd apps/api
AGENTGATE_JOB_DISPATCH_MODE=worker python -m app.worker
```

### Frontend

```bash
cd apps/web
npm install
npm run dev
```

### Docker Compose

```bash
docker compose up --build
```

Copy `.env.example` to `.env` for local work. Keep `.env` untracked and never commit real secrets, tokens, customer data, cookies, or production credentials.

## Verification Before Opening A PR

Run the same checks that CI runs:

```bash
cd apps/api
python -m compileall app
python -m pytest app/tests -q -o cache_dir=.tmp/pytest_cache

cd ../web
npm run build

cd ../..
docker compose config
```

Quality and security commands:

```bash
make lint
make security-scan
make audit-deps
make verify-all
```

If you changed deployment docs, Compose surfaces, or Dockerfiles, also run:

```bash
make prod-config-check
```

If you changed deployment validation, readiness expectations, production runbooks, or startup guidance, also run:

```bash
python scripts/validate-deployment.py --help
```

When a local or staging stack is available, run:

```bash
make validate-deployment
```

Optional manual load and performance regression commands:

```bash
make load-smoke
make load-gateway
make load-all
```

If you changed gateway behavior, login, jobs, audit integrity, readiness, or rate limiting, run the relevant k6 scripts from `load-tests/k6/` when practical. These checks are intentionally non-blocking and are documented in `docs/operations/load-testing.md`.

Optional browser E2E smoke commands:

```bash
make e2e-install
make e2e
make e2e-headed
```

If you changed login, session handling, navigation, or key dashboard pages, run the Playwright suite from `apps/web/e2e/` when practical. These checks are intentionally small and non-blocking, and are documented in `docs/operations/e2e-testing.md`.

If you changed self-hosted deployment behavior, keep `compose.prod.example.yml`, `docs/operations/self-hosted-deployment.md`, `docs/operations/production-runbook.md`, and `docs/operations/production-readiness-checklist.md` aligned.

Direct commands behind those targets:

- `cd apps/api && python -m ruff check app`
- `cd apps/api && python -m bandit -c bandit.yaml -r app -iii`
- `cd apps/api && python -m pip_audit --progress-spinner off`
- `cd apps/web && npm audit --audit-level=high`
- `trivy fs --config .trivy.yaml .`

## Release And Versioning

AgentGate uses lightweight pre-1.0 tags in the form `v0.x.y`.

For maintainers, a `controlled-pilot release` means a curated release for private evaluation or narrow design-partner pilot work. It is not shorthand for enterprise GA, managed SaaS operations, compliance readiness, or HA maturity.

Before cutting a tag:

- update `CHANGELOG.md`
- run `make release-check`
- keep README, pilot docs, and release-facing claims aligned
- use `docs/operations/release-checklist.md` as the maintainer checklist

CI behavior:

- Blocking: compile/tests, frontend build, compose validation, Ruff, Bandit, `npm audit` high+, Trivy high and critical findings, and Gitleaks.
- Advisory: `pip-audit` currently reports in CI without blocking because Python advisory severity data is not clean enough yet for a low-noise hard gate.
- k6 load tests are intentionally not part of the default blocking PR workflow. They are an opt-in local or manually triggered regression tool, not a claim of production capacity.
- Playwright browser E2E is intentionally opt-in for local runs and available through a manual workflow. It is not part of the default blocking PR workflow.
- The production deployment profile is a self-hosted Compose example and is validated with `make prod-config-check`, not with a full production environment bring-up in CI.
- The deployment validator is an operator smoke tool for running environments, not a default blocking CI gate.

If you changed schema-affecting models or Alembic state, also run:

```bash
cd apps/api
AGENTGATE_DATABASE_URL=sqlite:///./migrate_check.db python -m alembic upgrade head
```

## Coding Standards

### Backend

- Keep FastAPI routers thin and push business logic into services.
- Use Pydantic request and response models for typed API contracts.
- Keep security-critical logic explicit. Avoid hidden fallbacks and magic behavior.
- Add tests for new policy, intent, risk, auth, approval, retention, export, or secret-handling behavior.
- Prefer SQLite-compatible local and test paths unless a PostgreSQL-only behavior is truly required.

### Frontend

- Use the typed API client in `apps/web/lib/api.ts`.
- Preserve the existing admin dashboard patterns instead of introducing a new design system ad hoc.
- Handle loading, error, and empty states on data-driven pages.
- Keep operational and security language clear, precise, and enterprise-focused.

## Migration Rules

- If SQLAlchemy models change, decide deliberately whether an Alembic migration is required.
- Keep migrations additive and review rollback or downgrade implications.
- Do not sneak schema changes into unrelated pull requests.
- Mention any operational rollout considerations for migrations that affect production data, jobs, approvals, retention, or audit behavior.

## Security And Repo Hygiene

- Never commit `.env` files, SQLite databases, caches, build outputs, or `node_modules`.
- Never commit real GitHub, Slack, OIDC, JWT, API, or encryption secrets.
- Keep demo credentials and placeholder tokens in docs and tests clearly fake and sanitized.
- Prefer targeted suppressions for false positives. Use narrow Ruff per-file ignores, narrowly scoped dependency exceptions, and `# nosec <rule>` only when the code path is understood and documented.
- Use `SECURITY.md` for responsible disclosure guidance. Do not report live vulnerabilities in public issues.

## Pull Request Expectations

- Explain what changed and why it belongs in AgentGate.
- Call out security impact, migration impact, and operator-facing behavior changes.
- Update docs and examples when env vars, APIs, workflows, or deployment expectations change.
- Include screenshots for meaningful dashboard changes when practical.
