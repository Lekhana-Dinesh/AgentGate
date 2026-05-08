# Scheduled Tasks

## Overview

AgentGate now includes a built-in recurring scheduler foundation for tenant-scoped operational work.

The scheduler is intentionally simple:

- `ScheduledTask` rows are stored in the primary database
- `python -m app.scheduler` polls for due enabled tasks
- the scheduler claims one due task at a time and enqueues an existing durable job
- the scheduler never runs retention, audit export, audit-integrity verification, or connector health logic inline
- `next_run_at`, `last_run_at`, `last_status`, and `last_error` are updated on the scheduled task row

This keeps local development simple while preserving the existing job handlers and worker safety model.

## Supported Task Types

- `retention_purge`
  - Enqueues the existing retention purge job
  - Config supports safe filters such as `dry_run`, `limit`, `retention_classes`, `tool_name`, and `tool_call_ids`
- `audit_export`
  - Enqueues the existing audit export job
  - Config stores only `audit_export_config_id` plus optional `dry_run`
- `audit_integrity_verify`
  - Enqueues a durable audit-integrity verification job that reuses the existing verification service
  - Config supports optional bounded verification fields such as `start_event_id`, `end_event_id`, `start_date`, and `end_date`
- `audit_integrity_checkpoint`
  - Enqueues a durable audit-integrity checkpoint job that verifies the target range and writes an external checkpoint document through the configured anchor adapter
  - Config is intentionally empty today because destination selection is deployment-scoped, not tenant secret config
- `connector_health_check`
  - Enqueues a durable connector health-check job
  - Current implementation is most useful for GitHub tools and returns `unsupported` for tool types without a health implementation

`stale_job_recovery` is not exposed as a scheduled task because the worker already performs stale recovery continuously.

## Safe Config Model

Scheduled task config is not a secret store.

- Secrets, tokens, passwords, and connector credentials are rejected at API validation time
- Config stores only safe IDs, schedule metadata, and bounded filters
- Responses and logs expose sanitized config only

## How It Works

For each due task:

1. The scheduler selects an enabled row whose `next_run_at <= now`.
2. In PostgreSQL, claim behavior uses `FOR UPDATE SKIP LOCKED` semantics through the normal SQLAlchemy path.
3. The scheduler computes a per-run idempotency key from the task's stable base key plus the run slot.
4. If an in-flight job already exists for that task, the scheduler records `last_status=duplicate` and advances the schedule without enqueueing another run.
5. If no in-flight job exists, the scheduler enqueues the correct durable job through the existing job services.
6. The scheduler records audit events and updates `last_status` to `enqueued` or `failed`.
7. `next_run_at` advances to the next future interval or cron tick.

`last_status` describes scheduler enqueue behavior, not downstream job completion. Final execution state still lives on the durable job row.

Checkpoint jobs can also succeed with a safe `no_new_events` result when no newly anchored audit events are available. That is not treated as a scheduler failure.

## Idempotency Model

- Each scheduled task has a tenant-scoped stable `idempotency_key`
- Each recurring enqueue derives a per-run job key from that base key plus the trigger time
- Overlapping runs are intentionally suppressed
- If a previous run is still `queued` or `running`, the next due tick is marked `duplicate` and AgentGate does not enqueue another copy
- Audit export also preserves its own destination cursor semantics, so repeated scheduled runs do not resend already exported events

## Schedule Kinds

### Interval

- `schedule_kind=interval`
- Requires `interval_seconds`
- Best for simple recurring checks such as retention dry-runs or connector health polling

### Cron

- `schedule_kind=cron`
- Uses a simple five-field UTC cron expression: minute, hour, day-of-month, month, day-of-week
- Example: `0 * * * *` for hourly

Current cron support is intentionally lightweight and UTC-only.

## Local Development

Run the scheduler loop:

```bash
cd apps/api
python -m app.scheduler
```

Recommended local combinations:

- `AGENTGATE_JOB_DISPATCH_MODE=inline`
  - simplest local path
  - the scheduler enqueues and immediately processes safe recurring jobs after commit
- `AGENTGATE_JOB_DISPATCH_MODE=worker`
  - closer to production behavior
  - run both `python -m app.worker` and `python -m app.scheduler`

Useful settings:

- `AGENTGATE_SCHEDULER_POLL_INTERVAL_SECONDS`
- `AGENTGATE_SCHEDULER_BATCH_SIZE`

## Production Deployment

For self-hosted production-style deployments:

1. Run migrations before rolling the API, worker, or scheduler processes.
2. Run a dedicated `worker` process.
3. Run a dedicated `scheduler` process when recurring tasks are enabled.
4. Keep PostgreSQL as the durable source of truth and Redis as an acceleration layer only.
5. Monitor `/ready`, `/metrics`, worker status, and scheduler logs.

The production Compose example now includes a `scheduler` service.

## Metrics And Readiness

`GET /metrics` exposes safe aggregate scheduler metrics:

- current due scheduled-task counts
- current scheduled-task last-status counts
- scheduler enqueue totals
- scheduler error totals

`GET /ready` exposes safe scheduler config status such as:

- loop command
- poll interval
- batch size
- supported task types

## Limitations

- The built-in scheduler is a simple poll loop, not a leader-elected distributed scheduler
- Cron expressions are UTC-only
- Overlapping runs are skipped rather than replayed in parallel
- Missed downtime windows collapse into one future enqueue instead of replaying every missed tick
- Scheduled task status reflects enqueue behavior, not downstream job success
- External time-zone calendars, per-tenant local-time schedules, and richer replay policies are not built in

## When To Use External Cron Or Orchestration Anyway

External scheduling can still be the better choice when you need:

- tenant-local time zones or business-calendar semantics
- explicit missed-run replay policies
- cluster-wide leadership guarantees
- stronger fleet-level observability or autoscaling
- a single orchestration platform across many services

Using external cron or orchestration is still compatible with AgentGate.
You can call the same privileged APIs such as:

- `POST /v1/retention/purge`
- `POST /v1/audit-exports/{id}/run`
- `POST /v1/audit-integrity/verify`
- `POST /v1/audit-integrity/checkpoints`
- `POST /v1/scheduled-tasks/{task_id}/run-now`
