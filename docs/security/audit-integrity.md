# Audit Integrity

## What this feature is

AgentGate includes a built-in tamper-evident audit-integrity layer for tenant-scoped `AuditEvent` records.

The current implementation links sanitized audit events into a per-tenant hash chain so that later modification, reordering, or selective deletion becomes detectable during verification.

This is a meaningful evidence-integrity control, but it is not the same thing as full immutability.

AgentGate now also includes an external checkpoint foundation. See [External Audit Anchoring](external-audit-anchoring.md).

## What tamper-evident means

For each tenant, newly written audit events receive:

- `event_hash`
- `previous_event_hash`
- `hash_algorithm`
- `chain_scope`
- `sequence_number`
- `anchored_at`

These values form a tenant-scoped chain:

1. Each event has a canonical content hash derived from sanitized audit data.
2. Each event links to the previous anchored event for that tenant.
3. Verification recomputes hashes and chain links to detect inconsistencies.

If an operator or attacker changes a hashed field, deletes an anchored event, or inserts inconsistent chain metadata, verification will report the problem.

## What this does not guarantee

The current design does not provide:

- WORM storage
- database-level append-only enforcement
- protection against a fully privileged database operator rewriting rows and recomputing the chain
- independent external timestamping or notarization
- cryptographic proof that an event existed at a given time outside the AgentGate trust boundary

Because of those limits, AgentGate should describe this control as tamper-evident, not tamper-proof and not fully immutable.

External checkpoints improve this posture, but they still should not be described as fully immutable unless the destination itself enforces WORM or Object Lock semantics.

## Hash-chain design

The current algorithm marker is `sha256_json_v1`.

Each `event_hash` is calculated from canonical sanitized audit-event content, including stable event identifiers and timestamps, but excluding unstable or sensitive values such as:

- raw secrets
- decrypted payloads
- protected payload ciphertext internals
- volatile verification-only fields

The chain is scoped with `chain_scope="tenant:<tenant_id>"`.

`sequence_number` is monotonic within that tenant scope.

`previous_event_hash` links each anchored event to the prior anchored event in that same tenant scope.

This means:

- tenants do not share one global chain
- cross-tenant tampering does not let one tenant rewrite another tenant's sequence
- verification can reason about one tenant independently

## Legacy events and backward compatibility

Older audit rows may exist without integrity metadata.

AgentGate handles those rows honestly:

- status APIs report legacy or unanchored history explicitly
- verification can succeed for anchored segments while still warning that legacy rows exist
- operators can run backfill to anchor historical tenant events in order

Until backfill runs, those historical rows should be treated as legacy evidence rather than fully chained evidence.

## Verification process

Restricted API endpoints are available for owners, admins, and security reviewers:

- `GET /v1/audit-integrity/status`
- `POST /v1/audit-integrity/verify`
- `POST /v1/audit-integrity/backfill`
- `GET /v1/audit-integrity/checkpoints`
- `POST /v1/audit-integrity/checkpoints`
- `GET /v1/audit-integrity/checkpoints/{id}`
- `POST /v1/audit-integrity/checkpoints/{id}/verify`

Verification checks:

- hash algorithm marker
- chain scope
- monotonic sequence continuity
- previous-hash linkage
- current event content against stored `event_hash`

Verification can run across the full tenant history or against bounded anchored windows by event ID or date.
Verification follows the stored sequence numbers. Concurrent writers can record timestamps out of sequence. Date bounds select the complete chain segment from the first to the last matching event so verification can check every link in that segment.

Possible outcomes include:

- `empty`
- `legacy_only`
- `verified`
- `verified_with_legacy`
- `broken`

`broken` means the anchored chain segment does not verify cleanly.

## Backfill behavior

Backfill is tenant-scoped and deterministic.

In `dry_run` mode, AgentGate reports what would be rebuilt without changing stored data.

In real mode, backfill writes chain metadata for legacy history in chronological order. For a fully anchored history, it follows the existing sequence order.

Important tradeoff:

- Backfill can anchor historical rows after the fact.
- Backfill does not prove that those rows were never modified before anchoring.

That is why backfilled history is useful for forward integrity, but it is not a substitute for external immutable archival.

## Export behavior

Sanitized audit export can include safe integrity metadata:

- `event_hash`
- `previous_event_hash`
- `sequence_number`
- `hash_algorithm`

This helps downstream systems preserve verification context without exporting secrets or decrypted payload content.

## External checkpoints

Checkpointing builds on top of the local hash chain:

1. AgentGate selects a tenant-scoped range of already anchored audit events.
2. It verifies chain continuity before writing the checkpoint.
3. It computes a deterministic checkpoint hash from safe integrity metadata only.
4. It stores the checkpoint record and writes a checkpoint document to the configured external anchor.

Current checkpoint destination modes are:

- `local` for development and test
- `object_storage` for S3-compatible external anchoring
- `custom_placeholder` reserved for a future implementation and intentionally fail-closed today

Checkpointing does not export raw audit metadata bodies, decrypted payloads, or secrets.

Checkpoint jobs intentionally avoid self-referential checkpoint audit loops. The durable job row and checkpoint record remain the source of truth for checkpoint attempts.

## Recommended operator workflow

For production-minded deployments:

1. Backfill legacy tenant audit history once after upgrading.
2. Verify chains after upgrade and periodically afterward.
3. Alert on verification failures or unexpected legacy rows.
4. Preserve exported integrity metadata downstream.
5. Enable external checkpointing for stronger evidence integrity outside the primary database.
6. Use Object Lock, WORM retention, or an equivalent storage control if you need a stronger immutability claim.

## Current limitations

- Chain integrity is only as strong as the primary database trust boundary.
- Full-privilege operators can still rewrite rows and recompute hashes.
- The current external checkpoint foundation is not the same thing as a notarized external ledger.
- Object-storage anchoring is stronger than database-only evidence, but it is not full immutability unless WORM or Object Lock is configured on the destination.
- Backfilled history is honest and useful, but not equivalent to original-time anchoring.
- Verification is tenant-scoped and control-plane oriented; it does not independently verify downstream export retention or external-system integrity.
