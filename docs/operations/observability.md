# Observability

## What is implemented

AgentGate now ships a lightweight observability baseline:

- structured request logging
- request IDs on responses and error bodies
- safe readiness checks
- aggregate metrics at `GET /metrics`
- a starter Prometheus, Grafana, and alert-rules package under `observability/`

This is intentionally a foundation, not a full metrics, tracing, and alerting stack.

## Request logging

Request logs now include:

- `request_id`
- `method`
- `path`
- `status_code`
- `duration_ms`
- `tenant_id` when known
- `user_id` when known
- `error_code` when the request ends in a handled error

They do not log:

- raw request bodies
- tokens, passwords, cookies, or secrets
- decrypted execution payloads

## Health endpoints

- `GET /health`
  - lightweight liveness indicator
- `GET /ready`
  - database connectivity
  - job backend/config summary
  - key-provider summary
  - safe integration/config summary
  - rate-limiter provider summary and Redis connectivity when configured

## Metrics

`GET /metrics` returns Prometheus-style text output with safe aggregate values only.

Current metrics include:

- HTTP request counts and latency
- gateway decisions by decision and resulting status
- approval lifecycle totals
- job transition totals
- current job counts by status
- current dead-letter job counts
- active worker counts by effective status
- job lease expiration totals
- stale job recovery totals
- retry totals by job type and trigger
- audit export outcomes
- Slack notification outcomes
- retention purge totals
- OIDC login success and failure
- rate-limit allow and block totals by provider and scope
- rate-limit backend error totals by provider and scope

Metrics avoid tenant labels, user labels, raw payload values, and secret material.

See `docs/operations/observability-package.md` for the starter Prometheus scrape file, example alert rules, and Grafana dashboard JSON that match the current metric surface.

## Recommended usage

- scrape `/metrics` from an internal network path
- treat `/ready` as the deployment readiness signal
- propagate `X-Request-ID` from ingress if you already have one
- use `scripts/validate-deployment.py` after startup or upgrade to combine readiness checks with real operator login and safe control-plane API reachability
- alert on repeated `rate_limited`, `database_error`, `job_failed`, `retry_exhausted`, lease-expiration spikes, stale recovery spikes, and retention purge failures
- alert on `rate_limiter_unavailable` if Redis-backed rate limiting is required for the environment

## Load testing complement

AgentGate also includes a lightweight k6 regression suite under `load-tests/k6/`.

- use it to exercise `/health`, `/ready`, login, gateway paths, jobs, audit integrity, and opt-in rate-limited behavior
- treat it as a regression signal, not a production benchmark
- keep using `/metrics` and `/ready` alongside k6 results so latency regressions and operational state can be interpreted together

See `docs/operations/load-testing.md` for setup and commands.

## Current gaps

- no built-in distributed tracing
- no OpenTelemetry export
- no managed Prometheus, Grafana, or alert-routing deployment in-repo
- no long-term metrics backend configuration in this repo
- no true worker-heartbeat timestamp metric yet; the current package uses worker-count and stale-recovery signals instead
