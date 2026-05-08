# Jobs And Workers

## Overview

AgentGate now uses a durable `jobs` table for:

- `approval_notification.slack`
- `approval_execution.tool_call`
- `audit_export.placeholder`
- `retention_purge.placeholder`
- `audit_integrity_verify.placeholder`
- `audit_integrity_checkpoint.placeholder`
- `connector_health_check.placeholder`

The jobs table is the source of truth. Redis is optional and only accelerates publication and worker wakeups.
The `retention_purge.placeholder` wire value is now backed by a real retention handler; the string remains for compatibility with the current enum and migration footprint.
The `audit_export.placeholder` wire value is also now backed by a real export handler; the string remains for compatibility with the current enum and migration footprint.
Worker mode now also records worker heartbeat and claims running jobs with explicit leases.
Recurring scheduled tasks are managed separately through the `scheduled_tasks` table and the `python -m app.scheduler` loop, which only enqueues durable jobs and never runs retention, export, or integrity logic inline.

## Modes

### Inline mode

- Set `AGENTGATE_JOB_DISPATCH_MODE=inline`
- Default for local `.env.example`
- API requests create job records and immediately execute them after the main transaction commits
- Best for local development, tests, and single-process workflows

### Worker mode

- Set `AGENTGATE_JOB_DISPATCH_MODE=worker`
- Run `python -m app.worker`
- Worker mode writes safe worker heartbeat state to the `workers` table
- Worker mode claims due jobs with `locked_by`, `locked_at`, and `lease_expires_at`
- Stale running jobs can be requeued safely or moved into terminal dead-letter review depending on job type
- API requests create durable job rows and return without executing notification or approved-execution work inline
- API requests create durable job rows and return without executing notification, approved-execution, or retention work inline
- Best for compose stacks and production-minded deployments

## Worker command

```bash
cd apps/api
python -m app.worker
```

Useful environment variables:

- `AGENTGATE_JOB_DISPATCH_MODE=worker`
- `AGENTGATE_JOB_BROKER=database` or `redis`
- `AGENTGATE_REDIS_URL=redis://host:6379/0`
- `AGENTGATE_JOB_REDIS_QUEUE_NAME=agentgate:jobs`
- `AGENTGATE_JOB_POLL_INTERVAL_SECONDS=2`
- `AGENTGATE_JOB_WORKER_BATCH_SIZE=10`
- `AGENTGATE_JOB_STALE_RECOVERY_BATCH_SIZE=25`
- `AGENTGATE_JOB_LEASE_SECONDS=300`
- `AGENTGATE_WORKER_HEARTBEAT_INTERVAL_SECONDS=5`
- `AGENTGATE_WORKER_STALE_AFTER_SECONDS=30`
- `AGENTGATE_JOB_SLACK_MAX_ATTEMPTS=3`
- `AGENTGATE_JOB_SLACK_RETRY_BACKOFF_SECONDS=30`
- `AGENTGATE_AUDIT_EXPORT_TIMEOUT_SECONDS=5`
- `AGENTGATE_JOB_AUDIT_EXPORT_MAX_ATTEMPTS=3`
- `AGENTGATE_JOB_AUDIT_EXPORT_RETRY_BACKOFF_SECONDS=30`
- `AGENTGATE_JOB_RETENTION_MAX_ATTEMPTS=2`
- `AGENTGATE_JOB_RETENTION_RETRY_BACKOFF_SECONDS=60`
- `AGENTGATE_JOB_AUDIT_INTEGRITY_CHECKPOINT_MAX_ATTEMPTS=3`
- `AGENTGATE_JOB_AUDIT_INTEGRITY_CHECKPOINT_RETRY_BACKOFF_SECONDS=30`
- `GET /ready` reports safe job backend status and whether Redis publication is reachable when configured.
- `GET /metrics` exposes aggregate job transition counters plus current job counts by status, dead-letter counts, lease expirations, retries, stale recovery, and worker counts.
- `GET /v1/workers` and `GET /v1/workers/status` expose safe worker identity and heartbeat state for privileged operators.

## Scheduler command

```bash
cd apps/api
python -m app.scheduler
```

Useful environment variables:

- `AGENTGATE_SCHEDULER_POLL_INTERVAL_SECONDS=5`
- `AGENTGATE_SCHEDULER_BATCH_SIZE=25`
- `GET /ready` reports safe scheduler config status including the poll interval and supported task types.
- `GET /metrics` exposes current due scheduled-task counts, current last-status counts, scheduler enqueue totals, and scheduler error totals.

See `docs/operations/scheduled-tasks.md` for the recurring task model, task types, and external-orchestrator tradeoffs.

## Worker heartbeat and leases

- Each worker gets a `worker_id`, hostname, process ID, safe metadata, and periodic heartbeat.
- Claimed jobs record `locked_by`, `locked_at`, and `lease_expires_at`.
- PostgreSQL uses `FOR UPDATE SKIP LOCKED` for safer multi-worker claim behavior.
- SQLite remains fine for local and test usage, but it is not the production concurrency model for multi-worker execution.

## Stale recovery and dead-letter behavior

- If a worker disappears after claiming a job, another worker can detect lease expiry.
- Safe retryable jobs are requeued with a new due time and an audit event.
- Non-retryable jobs, especially approved execution, are moved to terminal operator review instead of being replayed automatically.
- Terminal review state is represented on the job row with `status=failed` or `status=retry_exhausted` plus `dead_letter_reason`.
- `POST /v1/jobs/{id}/retry` can requeue safe terminal jobs, but approved execution remains blocked to avoid duplicate writes.

## Retry behavior

- Slack notification jobs retry only for explicitly retryable upstream outcomes such as rate limiting or upstream unavailability.
- Inline mode keeps local behavior simple and uses a single best-effort Slack attempt.
- Approved execution jobs do not automatically retry because the current supported write actions are not safely idempotent.
- Approved execution jobs also do not support the generic manual retry endpoint.
- Audit export jobs retry only for explicitly safe upstream failures such as network errors, timeouts, `429`, or `5xx` responses.
- Retention purge jobs can retry at the job level because the purge operation is idempotent and never decrypts payloads. Already-purged tool calls are skipped safely.
- Audit-integrity checkpoint jobs can retry for safe external-anchor failures such as transient object-storage errors. They still fail closed if the underlying tenant audit chain is broken.
- Failed retries can end in `retry_exhausted`.

## Idempotency model

- Each job has a tenant-scoped unique `idempotency_key`.
- Slack approval jobs use one key per approval request.
- Approved execution jobs use one key per approval request.
- Approved execution also checks `ToolCall.status` before dispatch so a completed tool call is not executed twice.
- Audit export jobs use one durable run record per manual trigger, while each destination config keeps its own `last_exported_at` and `last_exported_event_id` cursor so successfully exported events are not resent on later runs.
- Retention purge uses per-request jobs plus per-tool-call redaction state, so the same tool call is not purged twice.
- Audit-integrity checkpoint jobs create one checkpoint record per attempt and only advance the tenant checkpoint boundary when a verified range is successfully anchored.

## Safety notes

- Job payloads are sanitized in APIs and UI views.
- Approved execution decrypts protected execution arguments only inside the trusted worker/inline job handler.
- Audit export never decrypts protected execution arguments. It only sends sanitized `AuditEvent` views and re-sanitizes metadata before delivery.
- Audit-integrity checkpointing also never decrypts protected execution arguments and only writes safe integrity metadata to checkpoint records and anchor documents.
- Retention purge never decrypts archived execution arguments. It replaces expired protected payloads with a tombstone marker and updates `payload_redaction_status`.
- Payload decryption inside jobs uses the stored envelope `key_ref`, so manual key rotation can preserve old ciphertext readability when matching decrypt-only refs are still configured.
- GitHub write actions are single-attempt to avoid duplicate issues or comments.
- Notification failure never changes the approval decision.

## Audit export operations

- Create a destination with `POST /v1/audit-exports`.
- Trigger a dry-run with `POST /v1/audit-exports/{id}/run` and `{"dry_run": true}`.
- Trigger a real export with `POST /v1/audit-exports/{id}/run` and `{"dry_run": false}`.
- Inspect non-sensitive config status with `GET /v1/audit-exports/{id}/status`.
- Splunk HEC and Datadog-compatible destinations require `token_env_var` or `secret_ref`; generic webhook destinations may omit auth but should usually still authenticate in production.
- Export runs are tenant-scoped and per-destination. One tenant can export to multiple external sinks without sharing a cursor.

## Retention operations

- Preview purge impact with `POST /v1/retention/purge` and `{"dry_run": true}`.
- Run real purge with `POST /v1/retention/purge` and `{"dry_run": false}`.
- Use `GET /v1/retention/status` for tenant-scoped counts of eligible, purged, legal-hold, failed, and still-active protected payloads.
- Real purge only redacts `ToolCall.request_payload.execution_arguments`. Sanitized `request_payload.arguments`, decision metadata, traces, and audit references remain.
- If an approval is later executed after its protected payload has already been purged, the approved-execution job fails closed instead of rehydrating missing state.

## Audit checkpoint operations

- Trigger a manual checkpoint with `POST /v1/audit-integrity/checkpoints`.
- Review checkpoint records with `GET /v1/audit-integrity/checkpoints` and `GET /v1/audit-integrity/checkpoints/{id}`.
- Re-verify an anchored checkpoint with `POST /v1/audit-integrity/checkpoints/{id}/verify`.
- Checkpoint creation always runs through the durable jobs path. The API enqueues the job and does not perform the full chain verification and external write inline.
- Scheduled tasks can periodically enqueue checkpoint jobs with `task_type=audit_integrity_checkpoint`.
- External checkpointing is stronger than database-only evidence, but it is not a valid immutability claim unless the destination itself enforces WORM or Object Lock semantics.

## Current limitations

- The built-in worker is a simple process loop, not a full distributed orchestration platform.
- There is no lease-renewal mechanism yet for genuinely long-running job types.
- There is no separate external dead-letter queue yet; dead-letter review is represented on terminal job rows.
- The built-in scheduler is a simple poll loop, not a leader-elected fleet scheduler or full cron platform.
- Cron scheduling is UTC-only and intentionally overlap-avoiding; missed intervals collapse into one future enqueue rather than replaying every missed tick.
