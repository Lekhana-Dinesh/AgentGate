# Load Testing

AgentGate ships a lightweight k6-based load and performance regression foundation under `load-tests/k6/`.

This is intentionally practical rather than heavyweight:

- it is for local regression checks and operator rehearsal
- it is not an official production benchmark suite
- it does not claim capacity numbers for your environment

Future Codex sessions should update these scripts when changing auth, gateway, jobs, audit integrity, or rate-limiting behavior.

## What Is Covered

Current scripts:

- `load-tests/k6/smoke.js`
  - `GET /health`
  - `GET /ready`
- `load-tests/k6/auth.js`
  - `POST /v1/auth/login`
- `load-tests/k6/gateway.js`
  - happy-path gateway execution
  - optional approval-path exercise
- `load-tests/k6/jobs.js`
  - `GET /v1/jobs`
  - `GET /v1/jobs/{job_id}`
  - optional dry-run retention job refresh to keep job coverage realistic
- `load-tests/k6/integrity.js`
  - `GET /v1/audit-integrity/status`
  - optional `POST /v1/audit-integrity/verify`
- `load-tests/k6/rate_limit.js`
  - opt-in rate-limited login behavior

These scripts are intentionally conservative and do not try to emulate full production traffic mixes.

## Prerequisites

- k6 OSS installed locally
- AgentGate API reachable
- seeded demo data available

The repo does not require k6 for normal CI or day-to-day development.

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

The seeded local demo credentials are:

- tenant slug: `demo-agentgate`
- admin: `admin@demo.agentgate.example.com` / `AgentGate123!`
- reviewer: `reviewer@demo.agentgate.example.com` / `AgentGate123!`

The default k6 scripts assume the seeded admin account and the seeded `SalesProposalAgent`. Override them with environment variables if your environment differs.

## API Base URL And Auth

Core k6 environment variables:

- `AGENTGATE_K6_BASE_URL`
  - defaults to `http://127.0.0.1:8000`
- `AGENTGATE_K6_TENANT_SLUG`
  - defaults to `demo-agentgate`
- `AGENTGATE_K6_EMAIL`
  - defaults to `admin@demo.agentgate.example.com`
- `AGENTGATE_K6_PASSWORD`
  - defaults to `AgentGate123!`
- `AGENTGATE_K6_TOKEN`
  - optional pre-fetched bearer token
- `AGENTGATE_K6_AGENT_NAME`
  - defaults to `SalesProposalAgent`
- `AGENTGATE_K6_AGENT_ID`
  - optional explicit agent ID override
- `AGENTGATE_K6_INCLUDE_APPROVAL_PATH=true`
  - enables the approval-path branch in `gateway.js`
- `AGENTGATE_K6_INCLUDE_INTEGRITY_VERIFY=true`
  - enables `POST /v1/audit-integrity/verify` in `integrity.js`
- `AGENTGATE_K6_VUS`
  - overrides the default virtual-user count
- `AGENTGATE_K6_DURATION`
  - overrides the default test duration
- `AGENTGATE_K6_SLEEP_SECONDS`
  - overrides the per-iteration pause

You can let k6 log in automatically, or fetch a token manually:

```bash
curl -s http://127.0.0.1:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@demo.agentgate.example.com","password":"AgentGate123!","tenant_slug":"demo-agentgate"}'
```

Then export the returned token as `AGENTGATE_K6_TOKEN` if you want to reuse it.

## Running Against Local Docker Compose

Bring up the stack:

```bash
docker compose up --build
```

Seed the demo tenant:

```bash
docker compose exec api python -m app.db.seed
```

Run a quick smoke profile:

```bash
k6 run load-tests/k6/smoke.js
```

Because the default Compose profile already exposes the API on `http://127.0.0.1:8000`, no extra base-url configuration is required unless you changed the port.

## Common Commands

From the repo root:

```bash
make load-smoke
make load-gateway
make load-all
```

Direct k6 commands:

```bash
k6 run load-tests/k6/smoke.js
k6 run load-tests/k6/auth.js
k6 run load-tests/k6/gateway.js
k6 run load-tests/k6/jobs.js
k6 run load-tests/k6/integrity.js
AGENTGATE_K6_INCLUDE_APPROVAL_PATH=true k6 run load-tests/k6/gateway.js
```

The `rate_limit.js` scenario is intentionally separate because it expects a deliberately rate-limited environment:

```bash
AGENTGATE_K6_EXPECT_RATE_LIMITED=true k6 run load-tests/k6/rate_limit.js
```

## Rate-Limit Scenario Setup

Local development keeps endpoint rate limiting disabled by default. To exercise `rate_limit.js`, start AgentGate with explicit rate-limiter settings such as:

```bash
AGENTGATE_RATE_LIMIT_ENABLED=true \
AGENTGATE_RATE_LIMIT_PROVIDER=in_memory \
AGENTGATE_RATE_LIMIT_LOGIN_LIMIT=2 \
AGENTGATE_RATE_LIMIT_LOGIN_WINDOW_SECONDS=60 \
docker compose up --build
```

Then run:

```bash
AGENTGATE_K6_EXPECT_RATE_LIMITED=true k6 run load-tests/k6/rate_limit.js
```

That scenario treats `200` and `429` as expected outcomes and requires at least one `429` to prove the limiter is actually engaging.

## Threshold Philosophy

The bundled thresholds are conservative regression tripwires:

- smoke endpoints target a `p(95)` under `500ms`
- smoke endpoints target a `p(95)` under `1000ms`
- auth, jobs, and routine operational endpoints target a `p(95)` under `1500ms`
- gateway and audit-integrity verification paths target a `p(95)` under `2000ms`
- checks must pass at a very high rate

Interpretation:

- a threshold failure means performance likely regressed for the exercised path
- a passing threshold does not mean production capacity is proven
- results depend heavily on local machine, database, runtime mode, and whether jobs run inline or through the worker

## What These Tests Do Not Prove

- production throughput or concurrency ceilings
- multi-tenant fairness under real-world load
- cross-region behavior
- Redis saturation behavior at scale
- queue-depth resilience under prolonged worker pressure
- browser or end-to-end UI performance

Use these scripts as an early warning system, not as a substitute for environment-specific performance engineering.
