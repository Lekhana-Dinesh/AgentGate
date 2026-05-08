# Audit Integrity Context

## 1. Purpose

This file covers audit-event sanitization, tenant-scoped hash chaining, verification and backfill, audit export integrity metadata, and external checkpoint anchoring.

## 2. Main files/directories

- `apps/api/app/models/audit_event.py`, `audit_export_config.py`, `audit_integrity_checkpoint.py`
- `apps/api/app/audit/integrity.py`
- `apps/api/app/services/audit_service.py`, `audit_export_service.py`, `audit_integrity_service.py`, `audit_integrity_checkpoint_service.py`
- `apps/api/app/security/audit_anchoring.py`
- `apps/api/app/api/routes/audit.py`, `audit_exports.py`, `audit_integrity.py`
- `docs/security/audit-integrity.md`
- `docs/security/external-audit-anchoring.md`
- `docs/operations/backup-and-restore.md`
- `docs/integrations/audit-export.md`

## 3. Current capabilities

- Sanitized tenant-scoped audit events written on key control-plane actions
- Per-tenant tamper-evident hash chaining using canonical sanitized audit content
- Status, verify, and backfill flows for anchored versus legacy audit history
- Tenant-scoped audit export with safe integrity metadata and per-destination cursors
- Tenant-scoped checkpoint creation, verification, and optional external anchoring to local or S3-compatible object storage
- Scheduled checkpoint jobs and manual checkpoint enqueue APIs
- Narrow browser controls for owner/admin operators to enable or disable audit-export configs and trigger manual runs without exposing secret refs or destination credentials
- Recovery guidance that pairs database restore validation with checkpoint-history and external-anchor verification

## 4. Critical invariants / must-not-break rules

- Audit events remain tenant-scoped and sanitized on write.
- Chain hashing must use safe canonical content, not decrypted payloads or raw secrets.
- Audit export and checkpoint documents must never include raw secrets, unsafe metadata, or protected envelope internals.
- Do not claim tamper-proof or immutable storage unless the destination truly enforces WORM or Object Lock semantics.
- Checkpoint jobs must avoid self-referential checkpoint loops.
- Do not treat a PostgreSQL restore as complete evidence recovery if the external checkpoint destination was not retained separately.
- Security reviewers may inspect audit-export status, but only owner and admin roles may enable, disable, or run audit-export jobs from the browser.

## 5. Security boundaries

- The local hash chain lives inside the primary database trust boundary.
- External checkpoints improve evidence survivability outside that boundary, but destination security still matters.
- Object-storage credentials stay in env, IAM, or secret refs, never in the database.
- Verification endpoints are privileged tenant-scoped operator workflows.
- Backup and recovery of checkpoint object storage is an operator responsibility outside the database backup path.
- Audit-export browser controls must remain safe-summary and non-secret; they are not a tenant-facing credential editor.

## 6. Known limitations

- The built-in chain is tamper-evident, not a notarized immutable ledger.
- Full-privilege operators could still rewrite weakly protected data and recompute hashes.
- Backfill is honest and useful, but not equivalent to original-time anchoring.
- `custom_placeholder` anchoring is not implemented yet.
- Restoring PostgreSQL without the matching external checkpoint objects weakens the recovery story for externally anchored evidence.
- Audit-export destination creation and detailed endpoint/filter editing remain API-driven in the current build even though enable/disable and manual run are now available in the browser for owner/admin roles.

## 7. Relevant tests

- `apps/api/app/tests/test_audit_integrity.py`
- `apps/api/app/tests/test_audit_integrity_checkpoints.py`
- `apps/api/app/tests/test_audit_export.py`
- `load-tests/k6/integrity.js`

## 8. When future Codex sessions should read this file

Read this before editing audit-event schema, integrity hashing, verify or backfill flows, audit export behavior, checkpoint creation, or external anchor handling.
