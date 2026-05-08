# External Audit Anchoring

## Purpose

AgentGate now includes a tenant-scoped audit-checkpoint foundation that can anchor audit-chain checkpoints outside the primary database trust boundary.

The goal is stronger evidence integrity, not magic immutability claims.

## What checkpointing proves

When a checkpoint is created successfully, AgentGate:

1. Selects a tenant-scoped range of already anchored audit events.
2. Verifies chain continuity for that range before writing a checkpoint.
3. Computes a deterministic checkpoint hash from safe integrity metadata only.
4. Stores the checkpoint record in AgentGate.
5. Writes a checkpoint document to the configured external anchor destination.

That proves:

- the selected anchored audit range existed in a specific tenant-scoped integrity state when the checkpoint was written
- later mutation, deletion, or replay of that range is detectable by recomputing the checkpoint hash
- an external copy of that checkpoint document can survive compromise of the primary database, depending on where it is stored

## What checkpointing does not prove

Checkpointing does not automatically provide:

- full immutability
- WORM guarantees
- legal-hold retention
- independent timestamp authority
- protection from a privileged operator who can rewrite both the database and a weak external destination

Do not describe this feature as immutable unless the external destination actually enforces WORM or Object Lock semantics.

## Local Hash Chain Versus External Checkpoint

### Local database hash chain

The built-in audit chain is tenant-scoped tamper evidence inside AgentGate:

- each audit event has `event_hash`
- each event links to `previous_event_hash`
- verification detects broken sequence, wrong previous hash, or content drift

That is strong tamper evidence inside the application trust boundary, but it still lives in the primary database.

### External checkpoint

The checkpoint layer summarizes a verified tenant-scoped range of anchored audit events and writes a checkpoint document outside the primary database.

That external document can later be compared to the current database state.

## Checkpoint Contents

Checkpoint hashing and external documents use only safe integrity metadata such as:

- tenant ID
- chain scope
- event IDs
- sequence numbers
- stored event hashes
- stored previous-event hashes
- anchored timestamps

They do not include:

- raw secrets
- decrypted payloads
- protected envelope internals
- unsafe audit-event metadata bodies
- AWS credentials or secret references

## External Anchor Modes

### `local`

- intended for development and test only
- writes checkpoint documents to a configured local filesystem path
- useful for local validation and operator understanding
- not a meaningful external enterprise trust boundary by itself

### `object_storage`

- writes checkpoint documents to S3-compatible object storage
- supports bucket, prefix, region, and optional `endpoint_url`
- can be used with AWS S3, MinIO, or LocalStack-style environments
- does not store AWS credentials in the database

### `custom_placeholder`

- reserved for a future external anchor integration
- current builds fail closed instead of pretending a custom anchor exists

## S3 And WORM Recommendation

For production-minded deployments:

- use `AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage`
- write to a dedicated bucket or prefix with tight IAM
- prefer bucket versioning
- prefer S3 Object Lock or another real WORM control if you need stronger evidence preservation
- monitor failed or retry-exhausted checkpoint jobs

Without Object Lock, versioning, or an equivalent retention control, object storage is still better than database-only evidence, but it is not full immutability.

## Verification Flow

Checkpoint verification at `POST /v1/audit-integrity/checkpoints/{id}/verify` does three things:

1. Re-reads the tenant-scoped checkpoint range from the current database.
2. Re-verifies the underlying audit-chain continuity and recomputes the checkpoint hash.
3. Re-reads the external checkpoint document and compares it to the stored record.

If the chain, checkpoint hash, or external document no longer match, verification returns `broken`.

## Scheduler And Jobs

Manual checkpoint creation always goes through the durable jobs path.

- `POST /v1/audit-integrity/checkpoints` enqueues a checkpoint job
- inline mode still uses the same job handler after commit
- worker mode returns a queued job
- scheduled tasks can periodically enqueue checkpoint jobs with `task_type=audit_integrity_checkpoint`

If no newly anchored audit events are available, the job returns a safe `no_new_events` result instead of pretending a new checkpoint was written.

## Limitations

- checkpoint records still exist in AgentGate and are therefore not themselves an immutable ledger
- the current implementation uses safe integrity metadata, not a full external notarization service
- local-file anchoring is for development and test only
- custom external anchoring is not implemented yet
- if object-storage credentials or bucket policy are weak, the external evidence copy is also weak
- checkpoint operations are visible through job records and checkpoint records, but the system intentionally avoids self-referential checkpoint audit loops that would create infinite checkpoint churn
