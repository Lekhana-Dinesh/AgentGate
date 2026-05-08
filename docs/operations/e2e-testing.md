# Browser E2E Testing

AgentGate includes a small Playwright-based browser E2E foundation under `apps/web/e2e/`.

This suite is intentionally narrow:

- it validates the most important operator-facing flows
- it assumes a locally running or Compose-backed stack
- it is opt-in and not part of the default blocking PR path

The goal is confidence in real user flows, not broad UI automation coverage.

## What The Suite Covers

Current coverage:

- login page renders
- local demo login succeeds
- dashboard overview loads after login
- sidebar navigation reaches key pages
- onboarding page renders setup guidance and safe operator actions
- onboarding links route into tools, settings, and policy surfaces
- settings page renders safe status sections
- tools page renders connector visibility without showing secret-like values
- users page renders identity lifecycle status
- scheduled tasks page renders task status or empty-state guidance
- audit integrity page renders checkpoint and verification sections
- audit exports page renders export status or empty-state guidance
- retention page renders status cards and dry-run controls
- sign out clears the browser session

The suite does not depend on live GitHub, Jira, MCP, Slack, AWS, or external SSO.

## Prerequisites

- backend API running
- frontend running
- demo data seeded
- Playwright Chromium installed locally

Default E2E environment variables:

- `AGENTGATE_E2E_BASE_URL`
  - defaults to `http://127.0.0.1:3000`
- `AGENTGATE_E2E_API_BASE_URL`
  - defaults to `http://127.0.0.1:8000` for the documented local startup commands
- `AGENTGATE_E2E_EMAIL`
  - use the seeded local demo admin unless you override it
- `AGENTGATE_E2E_PASSWORD`
  - use the seeded local demo admin password unless you override it
- `AGENTGATE_E2E_TENANT_SLUG`
  - use the seeded local demo tenant unless you override it

The test code defaults to the documented demo tenant for local convenience. Do not treat these demo credentials as production configuration.

## Seed Demo Data

Local backend:

```bash
cd apps/api
python -m alembic upgrade head
python -m app.db.seed
```

Docker Compose:

```bash
docker compose up --build
docker compose exec api python -m app.db.seed
```

## Start The App Locally

Backend:

```bash
cd apps/api
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd apps/web
NEXT_PUBLIC_API_BASE_URL=${AGENTGATE_E2E_API_BASE_URL:-http://127.0.0.1:8000} npm run dev
```

If you are using Docker Compose, the default local URLs already line up with the Playwright defaults:

- web: `http://127.0.0.1:3000`
- api: `http://127.0.0.1:8000`

## Install And Run Playwright

From the repo root:

```bash
make e2e-install
make e2e
make e2e-headed
```

Direct frontend commands:

```bash
cd apps/web
npm run e2e:install
npm run e2e
npm run e2e:headed
```

The suite uses a small Playwright setup project to authenticate once, save browser storage state, and then reuse that authenticated state for the authenticated operator tests.

The new operator-surface coverage stays manual on purpose:

- it assumes seeded local demo data rather than mocking every page contract in-browser
- it avoids screenshot diffs and timing-sensitive flows
- it focuses on render safety, navigation, and narrow safe UI actions such as onboarding dismiss/reset
- it does not turn Playwright into a blocking every-PR gate

## Optional Environment Overrides

Example custom run:

```bash
AGENTGATE_E2E_BASE_URL=http://127.0.0.1:3000 \
AGENTGATE_E2E_API_BASE_URL=http://127.0.0.1:8000 \
AGENTGATE_E2E_EMAIL=admin@demo.agentgate.example.com \
AGENTGATE_E2E_PASSWORD=AgentGate123! \
AGENTGATE_E2E_TENANT_SLUG=demo-agentgate \
cd apps/web && npm run e2e
```

If your shell does not support inline environment assignments, export or set those values first and then run the same command.

## Reports And Artifacts

Playwright outputs are intentionally untracked:

- `apps/web/playwright-report/`
- `apps/web/test-results/`
- `apps/web/e2e/.auth/`

The suite keeps traces, screenshots, and video only when useful for failure debugging.

## Limitations

- no cross-browser matrix yet; Chromium only
- no screenshot-diff or visual-regression coverage
- no seeded approval action workflow exercised in-browser yet
- no destructive user or connector mutation flows covered in-browser
- no live connector probing against external SaaS services
- no browser coverage for GitHub, Slack, OIDC, or AWS-backed integrations
- assumes seeded demo data and reachable local services
- not part of blocking PR CI by default

Use this suite as a reliable operator smoke test, not as proof of complete frontend correctness.
