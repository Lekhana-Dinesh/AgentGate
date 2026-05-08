# Backup And Restore

AgentGate stores durable governance state in PostgreSQL. That means backup and restore discipline is part of the product's security story even though AgentGate does not automate backups for you.

Use this guide with:

- `docs/operations/self-hosted-deployment.md`
- `docs/operations/deployment-validation.md`
- `docs/operations/pilot-rehearsal.md`
- `docs/operations/production-runbook.md`
- `docs/security/audit-integrity.md`
- `docs/security/external-audit-anchoring.md`

## What Must Be Backed Up

At minimum, protect the PostgreSQL database that holds:

- tenants
- users and identity lifecycle state
- agents
- tools and connector configuration records
- policies
- approvals
- traces
- audit events
- audit-integrity checkpoints
- audit export configuration and cursor state
- scheduled tasks
- durable jobs and worker state

Protect these separately from the database:

- external audit-anchor storage if `AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage`
- deployment environment variables or secret-manager entries
- AWS KMS configuration and IAM recovery path if `AGENTGATE_KEY_PROVIDER=aws_kms`
- reverse-proxy, DNS, TLS, and ingress configuration

Redis is operationally important, but it is not the durable source of truth for AgentGate jobs or control-plane state. Treat PostgreSQL as the authoritative recovery target.

## What Must Not Go Into Git

Do not commit any of the following into this repository:

- `.env` files
- local or production database dumps
- raw secrets
- KMS keys
- GitHub, Jira, MCP, Slack, OIDC, or SCIM tokens
- session cookies or browser export files

## Backup Frequency And Recovery Targets

AgentGate does not set your recovery objectives for you. Define and document your own:

- target RPO: how much PostgreSQL-backed control-plane data you can afford to lose
- target RTO: how long AgentGate can be unavailable during a recovery event

As a starting point for a self-hosted deployment:

- take scheduled PostgreSQL backups at least daily
- use more frequent snapshots or WAL archiving if your required RPO is tighter than daily
- run a restore drill at least quarterly and again before major upgrades or infrastructure changes
- keep external audit-anchor object storage retention aligned with the same recovery program

## Backup Commands

Use your platform backup system when available. If you need a direct PostgreSQL dump path, keep credentials outside the shell history and outside git-tracked files.

Generic PostgreSQL example:

```bash
export PGHOST=postgres.internal.example
export PGPORT=5432
export PGDATABASE=agentgate
export PGUSER=agentgate
export PGPASSFILE=/secure/path/.pgpass

pg_dump \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file /secure/backups/agentgate-$(date +%F-%H%M%S).dump
```

Local Compose example:

```bash
docker compose exec -T postgres \
  pg_dump -U agentgate -d agentgate -Fc \
  > /secure/backups/agentgate-local-$(date +%F-%H%M%S).dump
```

Notes:

- store dumps outside the repository working tree
- encrypt backup storage according to your platform standards
- verify backup retention, replication, and access control in the backup system itself
- if you use object-storage audit checkpoints, protect that bucket or prefix with its own retention and access policy

## Restore Procedure

Use a clean PostgreSQL target. Do not restore into an unknown mixed-state database.

Suggested sequence:

1. Stop or isolate write traffic to AgentGate.
2. Provision a clean PostgreSQL instance or database.
3. Restore the chosen backup.
4. Reapply the deployment environment, secret-manager entries, and KMS configuration required for the restored environment.
5. Start or restart the AgentGate `api`, `web`, `worker`, and `scheduler` services against the restored database.
6. Run Alembic migrations for the target revision if the restored database is older than the application revision you are starting.
7. Run deployment validation.
8. Perform audit-integrity and operator-surface checks before reopening traffic.

Generic restore example:

```bash
export PGHOST=postgres-restore.internal.example
export PGPORT=5432
export PGDATABASE=agentgate
export PGUSER=agentgate
export PGPASSFILE=/secure/path/.pgpass

pg_restore \
  --clean \
  --if-exists \
  --no-owner \
  --no-privileges \
  --dbname "$PGDATABASE" \
  /secure/backups/agentgate-2026-05-07-010000.dump
```

Production-style migration and startup example:

```bash
docker compose -f compose.prod.example.yml --profile ops run --rm migrate
docker compose -f compose.prod.example.yml up -d api web worker scheduler
```

Recovery notes:

- use the same or a compatible PostgreSQL major version expected by your deployment plan
- if Redis is reused after restoring an older PostgreSQL snapshot, clear or replace stale broker state according to your environment's Redis recovery policy
- do not seed demo data into a restored production environment

## Post-Restore Verification

Run the existing deployment validator first:

```bash
make verify-restore
```

Or directly:

```bash
AGENTGATE_VALIDATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_VALIDATE_WEB_URL=https://agentgate.example.com \
AGENTGATE_VALIDATE_EMAIL=owner@example.com \
AGENTGATE_VALIDATE_PASSWORD='<password>' \
AGENTGATE_VALIDATE_TENANT_SLUG=customer-tenant \
python scripts/validate-deployment.py
```

Then verify the recovery-specific items that the smoke validator does not prove by itself:

- `GET /v1/audit-integrity/status` returns healthy chain status for the tenant you care about
- `GET /v1/audit-integrity/checkpoints` returns the expected checkpoint history if checkpointing is enabled
- if external anchoring is enabled, verify the latest checkpoint through `POST /v1/audit-integrity/checkpoints/{id}/verify`
- confirm the external audit-anchor destination still contains the expected checkpoint documents
- confirm an operator can open `/settings`, `/tools`, `/jobs`, and `/audit-integrity`
- confirm `GET /v1/workers/status` shows an active worker after the restore
- confirm no production environment still accepts the demo credentials from local development

## Restore Drill Procedure

A useful drill is:

1. restore PostgreSQL into an isolated environment
2. inject the same secret-manager and KMS configuration shape used in production
3. start `api`, `web`, `worker`, and `scheduler`
4. run `make verify-restore`
5. verify audit-integrity status and the latest checkpoint
6. record actual RTO and any manual recovery gaps
7. update the runbook before the next drill

The pilot rehearsal runner is useful before or after this drill for repo and environment sanity checks, but it does not replace the restore procedure itself.

## What This Guide Does Not Cover

This foundation does not provide:

- automated managed backups
- cross-region database replication
- Redis point-in-time recovery guidance for every deployment shape
- backup orchestration for external connector systems
- automatic recovery of third-party systems like GitHub, Jira, Slack, MCP servers, or your IdP
- immutable evidence claims for audit checkpoints unless the destination itself enforces WORM or Object Lock semantics

## Limitations

- a successful restore drill proves your current process, not every future incident path
- PostgreSQL restore alone is not enough if the environment-specific secrets or KMS permissions are missing
- AgentGate does not independently verify your backup retention or object-lock settings
- the deployment validator is a smoke test and must be paired with operator review of logs, worker state, and audit-integrity evidence
