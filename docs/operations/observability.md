# Observability

## What is implemented

AgentGate now ships a lightweight observability baseline:

- structured request logging
- request IDs on responses and error bodies
- safe readiness checks
- aggregate metrics at `GET /metrics`

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

## Metrics

`GET /metrics` returns Prometheus-style text output with safe aggregate values only.

Current metrics include:

- HTTP request counts and latency
- gateway decisions by decision and resulting status
- approval lifecycle totals
- job transition totals
- current job counts by status
- audit export outcomes
- Slack notification outcomes
- retention purge totals
- OIDC login success and failure
- rate-limit rejections

Metrics avoid tenant labels, user labels, raw payload values, and secret material.

## Recommended usage

- scrape `/metrics` from an internal network path
- treat `/ready` as the deployment readiness signal
- propagate `X-Request-ID` from ingress if you already have one
- alert on repeated `rate_limited`, `database_error`, `job_failed`, `retry_exhausted`, and retention purge failures

## Current gaps

- no built-in distributed tracing
- no OpenTelemetry export
- no alert rules or dashboards in-repo
- no long-term metrics backend configuration in this repo
- no worker liveness heartbeat yet
