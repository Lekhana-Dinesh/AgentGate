# Job Reliability

## Overview

AgentGate now includes a production-minded async job reliability foundation built on the existing durable `jobs` table.

This foundation adds:

- worker identity and heartbeat tracking
- job leases and worker ownership markers
- stale-running recovery for safe retryable jobs
- terminal dead-letter review state using `failed` or `retry_exhausted` plus `dead_letter_reason`
- manual retry for safe job types only

The goal is stronger operational safety without requiring Redis, Celery, or other heavy infrastructure for local development.

## Worker identity and heartbeat

When running `python -m app.worker`, AgentGate registers a worker record with:

- `worker_id`
- `hostname`
- `process_id`
- `status`
- `last_heartbeat_at`
- `started_at`
- `stopped_at`
- safe metadata

Heartbeat is written periodically while the worker loop is alive.

Useful endpoints:

- `GET /v1/workers`
- `GET /v1/workers/status`

These endpoints expose safe operational metadata only. They do not expose tenant payloads, secrets, or decrypted job inputs.

## Lease model

Workers do not execute due jobs blindly.

When a worker claims a job, AgentGate sets:

- `locked_by`
- `locked_at`
- `lease_expires_at`

This gives each running job an explicit owner and lease window.

Current behavior:

- PostgreSQL-oriented deployments use row locking with `FOR UPDATE SKIP LOCKED` for safer multi-worker claiming.
- SQLite remains supported for local development and tests, but it is not a production-grade multi-worker locking story.

## Stale-running recovery

If a worker crashes or disappears after claiming a job, the lease eventually expires.

The worker loop now scans for stale `running` jobs whose `lease_expires_at` is in the past.

Recovery behavior depends on job type:

- Slack notification: requeue if attempts remain
- audit export: requeue if attempts remain
- retention purge: requeue if attempts remain
- approved execution: do not auto-retry

Recovery writes audit events so operators can see when AgentGate requeued a job or moved it to terminal review.

## Dead-letter behavior

AgentGate does not yet have a separate dead-letter table or external DLQ service.

Instead, terminal review state is represented on the durable job row itself with:

- `status=failed` for non-retryable terminal failures
- `status=retry_exhausted` for retryable jobs that used their safe retry budget
- `dead_letter_reason` for explicit terminal reason tracking

This gives operators a durable review queue without adding heavy infrastructure.

Useful API paths:

- `GET /v1/jobs?dead_lettered=true`
- `GET /v1/jobs/{id}`
- `POST /v1/jobs/{id}/retry`

## Manual retry policy

Manual retry is intentionally conservative.

Allowed:

- Slack notification jobs
- audit export jobs
- retention purge jobs

Blocked:

- approved execution jobs

Approved execution remains blocked because current supported write actions are not safely idempotent enough for blind operator replay.

## Retry policy by job type

- `approval_notification.slack`
  - auto-retry for safe transient upstream outcomes such as rate limiting or temporary unavailability
  - manual retry allowed
- `audit_export.placeholder`
  - auto-retry for safe transient upstream outcomes such as timeouts, network errors, `429`, or `5xx`
  - manual retry allowed
- `retention_purge.placeholder`
  - auto-retry allowed because purge is idempotent and does not decrypt archived payloads
  - manual retry allowed
- `approval_execution.tool_call`
  - no auto-retry
  - no manual retry through the generic retry endpoint

## Recommended configuration

Key settings:

- `AGENTGATE_JOB_DISPATCH_MODE`
- `AGENTGATE_JOB_BROKER`
- `AGENTGATE_JOB_POLL_INTERVAL_SECONDS`
- `AGENTGATE_JOB_WORKER_BATCH_SIZE`
- `AGENTGATE_JOB_STALE_RECOVERY_BATCH_SIZE`
- `AGENTGATE_JOB_LEASE_SECONDS`
- `AGENTGATE_WORKER_HEARTBEAT_INTERVAL_SECONDS`
- `AGENTGATE_WORKER_STALE_AFTER_SECONDS`

Production guidance:

- use PostgreSQL for multi-worker deployments
- treat SQLite as local/test only for job concurrency
- keep `AGENTGATE_JOB_LEASE_SECONDS` comfortably above normal job runtime
- keep `AGENTGATE_WORKER_STALE_AFTER_SECONDS` above the heartbeat interval
- alert on `failed`, `retry_exhausted`, and repeated stale recovery

## Limitations

- There is still no lease-renewal mechanism for very long-running job types.
- There is still no separate external dead-letter queue.
- SQLite support is honest and useful for tests, but not a substitute for PostgreSQL row-lock behavior.
- Worker heartbeat proves process liveness only within AgentGate's own datastore trust boundary.
- Approved execution remains intentionally conservative and may require manual investigation rather than generic retry.
