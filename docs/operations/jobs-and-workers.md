# Jobs And Workers

## Overview

AgentGate now uses a durable `jobs` table for:

- `approval_notification.slack`
- `approval_execution.tool_call`
- `audit_export.placeholder`
- `retention_purge.placeholder`

The jobs table is the source of truth. Redis is optional and only accelerates publication and worker wakeups.
The `retention_purge.placeholder` wire value is now backed by a real retention handler; the string remains for compatibility with the current enum and migration footprint.
The `audit_export.placeholder` wire value is also now backed by a real export handler; the string remains for compatibility with the current enum and migration footprint.

## Modes

### Inline mode

- Set `AGENTGATE_JOB_DISPATCH_MODE=inline`
- Default for local `.env.example`
- API requests create job records and immediately execute them after the main transaction commits
- Best for local development, tests, and single-process workflows

### Worker mode

- Set `AGENTGATE_JOB_DISPATCH_MODE=worker`
- Run `python -m app.worker`
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
- `AGENTGATE_JOB_SLACK_MAX_ATTEMPTS=3`
- `AGENTGATE_JOB_SLACK_RETRY_BACKOFF_SECONDS=30`
- `AGENTGATE_AUDIT_EXPORT_TIMEOUT_SECONDS=5`
- `AGENTGATE_JOB_AUDIT_EXPORT_MAX_ATTEMPTS=3`
- `AGENTGATE_JOB_AUDIT_EXPORT_RETRY_BACKOFF_SECONDS=30`
- `AGENTGATE_JOB_RETENTION_MAX_ATTEMPTS=2`
- `AGENTGATE_JOB_RETENTION_RETRY_BACKOFF_SECONDS=60`
- `GET /ready` reports safe job backend status and whether Redis publication is reachable when configured.
- `GET /metrics` exposes aggregate job transition counters plus current job counts by status.

## Retry behavior

- Slack notification jobs retry only for explicitly retryable upstream outcomes such as rate limiting or upstream unavailability.
- Inline mode keeps local behavior simple and uses a single best-effort Slack attempt.
- Approved execution jobs do not automatically retry because the current supported write actions are not safely idempotent.
- Audit export jobs retry only for explicitly safe upstream failures such as network errors, timeouts, `429`, or `5xx` responses.
- Retention purge jobs can retry at the job level because the purge operation is idempotent and never decrypts payloads. Already-purged tool calls are skipped safely.
- Failed retries can end in `retry_exhausted`.

## Idempotency model

- Each job has a tenant-scoped unique `idempotency_key`.
- Slack approval jobs use one key per approval request.
- Approved execution jobs use one key per approval request.
- Approved execution also checks `ToolCall.status` before dispatch so a completed tool call is not executed twice.
- Audit export jobs use one durable run record per manual trigger, while each destination config keeps its own `last_exported_at` and `last_exported_event_id` cursor so successfully exported events are not resent on later runs.
- Retention purge uses per-request jobs plus per-tool-call redaction state, so the same tool call is not purged twice.

## Safety notes

- Job payloads are sanitized in APIs and UI views.
- Approved execution decrypts protected execution arguments only inside the trusted worker/inline job handler.
- Audit export never decrypts protected execution arguments. It only sends sanitized `AuditEvent` views and re-sanitizes metadata before delivery.
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

## Current limitations

- The built-in worker is a simple process loop, not a full distributed orchestration platform.
- There is no dead-letter queue yet.
- There is no stale-running-job recovery or lease-based claim renewal yet.
- There is no built-in recurring scheduler that enqueues retention purge automatically; operators must call the retention API or schedule it externally.
- There is no built-in recurring scheduler for audit export either; operators must call the export run API or schedule it externally.
