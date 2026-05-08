# Observability And Ops Context

## 1. Purpose

This file covers readiness, metrics, structured logging, rate limiting, operator settings, and lightweight operational regression tools.

## 2. Main files/directories

- `apps/api/app/core/metrics.py`
- `apps/api/app/services/readiness_service.py`, `rate_limit_service.py`, `settings_service.py`, `dashboard_service.py`
- `apps/api/app/api/routes/metrics.py`, `settings.py`, `dashboard.py`
- `apps/web/app/settings/page.tsx`
- `observability/prometheus/prometheus.yml`
- `observability/prometheus/alert-rules.yml`
- `observability/grafana/agentgate-overview-dashboard.json`
- `docs/operations/observability.md`
- `docs/operations/observability-package.md`
- `docs/operations/rate-limiting.md`
- `docs/operations/admin-settings.md`
- `docs/operations/load-testing.md`

## 3. Current capabilities

- `GET /health`, `GET /ready`, and `GET /metrics`
- Structured request logging with request IDs and safe error metadata
- Safe readiness summaries for database, jobs, scheduler config, key provider, integrations, and rate limiter
- Prometheus-style aggregate metrics without tenant or payload labels
- Tenant-authenticated read-only settings overview for safe control-plane status
- Endpoint-specific rate limiting with in-memory local mode and Redis-backed distributed mode
- Starter Prometheus scrape config, alert rules, and Grafana dashboard assets for the current metric surface
- k6 regression scripts for health, auth, gateway, jobs, audit integrity, and limiter exercise

## 4. Critical invariants / must-not-break rules

- `/ready`, `/metrics`, logs, and settings must not leak secrets, decrypted payloads, raw tokens, or unsafe config bodies.
- Rate-limit keys must stay normalized and hashed before storage.
- Redis-backed limiter failure is fail-closed by default on protected endpoints.
- The settings overview stays read-only and safe-summary only.
- Observability output remains aggregate and operational, not tenant-data rich.

## 5. Security boundaries

- Readiness and metrics are operator surfaces, not data APIs.
- Settings overview mixes tenant-authenticated and deployment-level safe status, but must never cross into secret disclosure.
- Rate limiting is part of the abuse-control boundary for sensitive control-plane routes.
- Logs are useful for triage only if they remain sanitized.

## 6. Known limitations

- No distributed tracing or OpenTelemetry export exists yet.
- The observability package is still only a starter set of assets, not a full monitoring stack or alert program.
- The limiter is fixed-window and not yet proxy-trust-aware.
- Readiness does not prove a worker or scheduler is actively healthy beyond safe config status.

## 7. Relevant tests

- `apps/api/app/tests/test_operational_hardening.py`
- `apps/api/app/tests/test_settings_overview.py`
- `load-tests/k6/smoke.js`
- `load-tests/k6/jobs.js`
- `load-tests/k6/rate_limit.js`
- `python scripts/check-no-live-secrets.py`

## 8. When future Codex sessions should read this file

Read this before editing readiness, metrics, request logging, rate limiting, operator settings, Prometheus or Grafana starter assets, or ops-facing regression scripts.
