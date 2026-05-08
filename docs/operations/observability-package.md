# Observability Package

AgentGate now includes a starter observability package under `observability/`.

This package is intentionally practical and limited:

- it uses the existing `GET /metrics` surface
- it assumes Prometheus and Grafana already exist or will be provided by the operator
- it does not change AgentGate runtime behavior
- it does not claim production SLOs or a managed monitoring platform

## Included Assets

- `observability/prometheus/prometheus.yml`
- `observability/prometheus/alert-rules.yml`
- `observability/grafana/agentgate-overview-dashboard.json`

## What The Package Covers

The starter dashboard and alert rules cover only metrics that AgentGate already emits today:

- API request rate
- API request latency
- API 5xx error rate
- gateway decisions
- approval lifecycle counts
- durable job counts and transitions
- dead-letter counts
- worker counts
- stale job recovery and lease expiration
- scheduler enqueue and error activity
- scheduled tasks due now
- rate-limit allowed, blocked, and backend-error behavior
- audit export outcomes
- retention purge activity
- OIDC login outcomes

The package intentionally does not include panels or alerts for:

- audit integrity verification or checkpointing metrics, because no dedicated metrics exist yet
- SCIM provisioning metrics, because no dedicated metrics exist yet
- local email/password auth metrics, because no dedicated metrics exist yet
- a true worker heartbeat metric, because the current metric surface exposes worker counts rather than heartbeat timestamps

## Prometheus

The example Prometheus file scrapes:

- `GET /metrics`

It does not scrape:

- `GET /health`
- `GET /ready`

Those endpoints return JSON, not Prometheus exposition text. If you want alerting on `/ready`, add a separate HTTP probe such as `blackbox_exporter` or another external availability probe.

## Metrics Must Stay Internal

Do not expose `/metrics` to the public internet.

Recommended controls:

- bind the API service on a private or loopback interface where possible
- allow Prometheus scraping only from an internal network segment
- place `/metrics` behind reverse-proxy or ingress ACLs
- avoid sending `/metrics` through public CDN or edge paths

Even though AgentGate metrics are aggregate and sanitized, they still reveal operational shape, error rates, and workload patterns.

## Grafana Import

1. Create or select a Prometheus datasource in Grafana.
2. Import `observability/grafana/agentgate-overview-dashboard.json`.
3. When prompted, map `DS_PROMETHEUS` to your Prometheus datasource.
4. Save the imported dashboard in your operations folder.

The dashboard is intentionally a starter, not a complete NOC wallboard.

## Alert Rules

Load `observability/prometheus/alert-rules.yml` into your Prometheus rule path.

The shipped alerts are example thresholds for:

- API scrape down
- readiness failing through an external probe if you add one
- sustained 5xx rate
- rate limiter backend errors
- dead-letter or retry-exhausted job increases
- persistent dead-letter backlog
- stale recovery spikes
- no active workers
- scheduler errors
- audit export failures

These thresholds are conservative examples. Tune them to your own traffic and incident tolerance.

## What Each Alert Means

`AgentGateApiDown`

- Prometheus cannot scrape AgentGate `/metrics`.
- Check the API process, reverse proxy, service routing, and network policy first.

`AgentGateReadinessFailing`

- Your external `/ready` probe is failing.
- Inspect the `/ready` payload for database, key provider, rate limiter, and integration readiness details.

`AgentGateHigh5xxRate`

- The API is serving too many 5xx responses for a sustained period.
- Review request logs, recent deploys, database reachability, Redis reachability, and worker-side job side effects.

`AgentGateRateLimiterBackendErrors`

- The limiter backend is erroring, usually around Redis.
- Confirm Redis health and whether your deployment is failing closed as intended.

`AgentGateJobDeadLetterIncrease`

- Jobs are entering failed or retry-exhausted review states.
- Inspect the Jobs UI or `GET /v1/jobs`, then retry only after you understand the side-effect risk.

`AgentGateDeadLetterBacklogPresent`

- Dead-lettered jobs are lingering.
- Clear the backlog deliberately rather than letting failures normalize.

`AgentGateStaleRecoverySpike`

- Running jobs are being recovered after lease expiry.
- Check worker crashes, restarts, lease sizing, and unexpectedly long-running jobs.

`AgentGateNoActiveWorkers`

- No running workers are visible through the current worker gauge.
- Check the worker service, broker connectivity, and `/v1/workers/status`.

`AgentGateSchedulerErrors`

- Scheduled task dispatch is failing.
- Inspect scheduler logs, scheduled-task configuration, and job broker availability.

`AgentGateAuditExportFailures`

- Audit export jobs are failing.
- Check export destination config status, outbound network access, credentials, and the underlying durable job records.

## When To Use This Package

Use it:

- after first self-hosted deployment
- after upgrades
- when standing up staging
- when validating that `/metrics` is being scraped correctly

Use it together with:

- `docs/operations/self-hosted-deployment.md`
- `docs/operations/production-runbook.md`
- `docs/operations/deployment-validation.md`
- `docs/operations/backup-and-restore.md`

## Limitations

- no in-repo Prometheus or Grafana container deployment is shipped
- no blackbox exporter deployment is shipped
- no audit-integrity/checkpoint metrics exist yet
- no SCIM or local-auth metric family exists yet
- no trace backend, logs backend, or long-term metrics store is configured in-repo
- no SLO or paging policy is claimed by this package
