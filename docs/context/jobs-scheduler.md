# Jobs And Scheduler Context

## 1. Purpose

This file covers durable jobs, worker behavior, retry policy, dead-letter review, and recurring scheduled task behavior.

## 2. Main files/directories

- `apps/api/app/models/job.py`, `worker.py`, `scheduled_task.py`
- `apps/api/app/services/job_service.py`, `worker_service.py`, `scheduled_task_service.py`
- `apps/api/app/jobs/dispatcher.py`
- `apps/api/app/worker.py`, `apps/api/app/scheduler.py`
- `apps/api/app/api/routes/jobs.py`, `workers.py`, `scheduled_tasks.py`
- `docs/operations/jobs-and-workers.md`
- `docs/operations/scheduled-tasks.md`
- `docs/operations/job-reliability.md`

## 3. Current capabilities

- Durable jobs for Slack notifications, approved execution, audit export, retention purge, audit-integrity verification, audit-integrity checkpointing, and connector health checks
- `inline` and `worker` dispatch modes
- Worker heartbeat, lease ownership, stale-job recovery, dead-letter-style terminal review, and safe manual retry rules
- Tenant-scoped scheduled tasks for retention, export, integrity verify, integrity checkpoint, and connector health checks
- Scheduler-side idempotent enqueue behavior with overlap suppression
- Browser visibility for scheduled tasks plus owner/admin-only enable, disable, and run-now controls that still enqueue through the same durable job path

## 4. Critical invariants / must-not-break rules

- The `jobs` table is the durable source of truth.
- Redis is an accelerator, not the authoritative execution ledger.
- The scheduler only enqueues durable jobs. It must not run privileged retention, export, or integrity logic inline.
- Approved execution jobs must not be blindly retried.
- Job payloads and job APIs must remain sanitized.
- Tenant isolation applies to job rows, scheduled tasks, and job-owned domain objects.
- Security reviewers may inspect scheduled tasks, but only owner and admin roles may mutate schedule state or trigger manual enqueue actions.

## 5. Security boundaries

- Protected payload decryption happens only inside trusted job handlers when execution truly needs it.
- Export, retention, and checkpoint jobs must not decrypt or expose protected payloads casually.
- Worker and scheduler APIs expose safe operational metadata only.
- Retry behavior is a security boundary because duplicate writes can become real external side effects.
- Scheduled-task browser controls are a narrow operational surface only; they must not become a generic config editor or a path for storing secret material.

## 6. Known limitations

- The worker and scheduler are simple process loops, not a full orchestrator.
- No lease-renewal mechanism exists yet for genuinely long-running work.
- No separate external dead-letter queue exists yet.
- Scheduler cron is UTC-only and overlap-avoiding, not leader-elected or calendar-aware.
- Scheduled-task creation and full config editing remain API-driven in the current build even though enable, disable, and run-now are available in the browser for owner/admin roles.

## 7. Relevant tests

- `apps/api/app/tests/test_jobs_async.py`
- `apps/api/app/tests/test_job_reliability.py`
- `apps/api/app/tests/test_scheduled_tasks.py`
- `apps/api/app/tests/test_retention_purge.py`
- `apps/api/app/tests/test_audit_export.py`
- `apps/api/app/tests/test_audit_integrity_checkpoints.py`

## 8. When future Codex sessions should read this file

Read this before editing async execution, worker claiming, retry logic, durable job schemas, scheduled-task behavior, or queue-related operator surfaces.
