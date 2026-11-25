# Self-Hosted Deployment

AgentGate now includes self-hosted deployment foundations through `compose.prod.example.yml` and an AWS ECS/Fargate Terraform starter in `deploy/aws/ecs/`.

This is a practical baseline for teams running AgentGate themselves with:

- external PostgreSQL
- external Redis
- AWS KMS-backed payload protection
- a dedicated worker process
- a dedicated scheduler process when recurring tasks are enabled
- TLS termination and reverse proxy handled outside AgentGate

Use this as the production-style baseline for controlled pilots and high-touch self-hosted evaluations.
This is not a claim of enterprise GA, managed hosting, certified compliance, or complete platform operations.

If you want the fastest practical first-company rehearsal path, start with [Self-Hosted Evaluation](self-hosted-evaluation.md). That guide narrows this broader deployment baseline to a single-VM Docker Compose controlled-pilot proof with external PostgreSQL, external Redis, and one real approval-gated GitHub action.

## Recommended Topology

Recommended shape:

1. Run the `api`, `web`, `worker`, and optional `scheduler` services from this repo.
2. Point AgentGate at externally managed PostgreSQL and Redis.
3. Terminate TLS at a reverse proxy or ingress in front of the `web` and optionally `api` services.
4. Keep `/metrics` internal and restrict admin/API access by network policy where possible.
5. Inject secrets through deployment environment variables or your secret manager, not through git-tracked files.

The provided `compose.prod.example.yml` intentionally does not start PostgreSQL or Redis containers.

## Files

- `compose.prod.example.yml`
- `.env.self-hosted-evaluation.example`
- `deploy/aws/ecs/`
- `scripts/validate-deployment.py`
- `docs/operations/self-hosted-evaluation.md`
- `docs/operations/backup-and-restore.md`
- `docs/operations/aws-ecs-deployment.md`
- `observability/prometheus/prometheus.yml`
- `observability/prometheus/alert-rules.yml`
- `observability/grafana/agentgate-overview-dashboard.json`
- `docs/operations/deployment-validation.md`
- `docs/operations/observability-package.md`
- `docs/operations/production-runbook.md`
- `docs/operations/production-readiness-checklist.md`

## Required Environment Variables

Minimum production-like settings:

- `AGENTGATE_ENV=production`
- `AGENTGATE_SECRET_KEY`
- `AGENTGATE_DATABASE_URL`
- `AGENTGATE_REDIS_URL`
- `AGENTGATE_PUBLIC_APP_URL`
- `AGENTGATE_PUBLIC_API_URL`
- `AGENTGATE_CORS_ORIGINS`
- `AGENTGATE_JOB_DISPATCH_MODE=worker`
- `AGENTGATE_JOB_BROKER=redis`
- optional `AGENTGATE_SCHEDULER_POLL_INTERVAL_SECONDS`
- optional `AGENTGATE_SCHEDULER_BATCH_SIZE`
- `AGENTGATE_RATE_LIMIT_ENABLED=true`
- `AGENTGATE_RATE_LIMIT_PROVIDER=redis`

Recommended payload-protection settings:

- `AGENTGATE_KEY_PROVIDER=aws_kms`
- `AGENTGATE_AWS_REGION`
- `AGENTGATE_AWS_KMS_KEY_ID`
- optional `AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF`
- optional decrypt-only compatibility mappings in `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS`

Optional local or migration compatibility path:

- `AGENTGATE_KEY_PROVIDER=env`
- `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` or `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF`

Common optional integration examples:

- `AGENTGATE_GITHUB_TOKEN` or `AGENTGATE_GITHUB_APP_PRIVATE_KEY`
- `AGENTGATE_SLACK_BOT_TOKEN`
- connector-specific Jira or MCP env vars referenced by tool config, if those connectors are intentionally enabled

For first live pilot workflows, prefer GitHub. Treat Jira as an explicit opt-in second phase, and keep MCP disabled unless the remote server is internal and tightly allowlisted.

The `compose.prod.example.yml` file uses placeholder defaults so `docker compose ... config` can be validated safely, but real deployments must override them.
For an AWS-specific starter that keeps the same runtime model, see `docs/operations/aws-ecs-deployment.md`.

## PostgreSQL Setup

Requirements:

- PostgreSQL is the intended production database
- create a dedicated database and least-privilege application user
- enforce TLS to the database if your environment supports it
- run backups and retention outside AgentGate

Example URL shape:

```text
postgresql+psycopg://agentgate:<password>@postgres.internal.example:5432/agentgate
```

Before cutting traffic to a new environment, verify:

- the database exists
- the app user can connect
- the app user can run migrations
- backups and restore tests exist

## Redis Setup

Requirements:

- use external Redis for worker publication/wakeups and distributed rate limiting
- do not expose Redis publicly
- require authentication and network restrictions where available

Example URL shape:

```text
redis://:<password>@redis.internal.example:6379/0
```

Redis is operationally important in worker mode and for production rate limiting, but the durable source of truth for jobs remains the database.

## AWS KMS Setup

Recommended production path:

- `AGENTGATE_KEY_PROVIDER=aws_kms`
- `AGENTGATE_AWS_REGION=<region>`
- `AGENTGATE_AWS_KMS_KEY_ID=<key-id-or-arn>`

Minimum IAM permissions on the configured KMS key:

- `kms:DescribeKey`
- `kms:GenerateDataKey`
- `kms:Decrypt`

AgentGate uses envelope encryption:

- KMS protects data-encryption keys
- payload ciphertext stays in AgentGate storage
- plaintext data keys are not persisted

If you are migrating from the env-backed provider, keep old decrypt-only refs configured until legacy payloads age out or are re-encrypted by a future rotation workflow.

## Secret Injection Model

Do not commit real secrets into Compose files or `.env.example`.

Recommended injection patterns:

- host-level environment variables managed by your process supervisor
- Docker Compose `--env-file` stored outside the repo
- secret-manager driven env injection at deploy time

Current runtime behavior:

- GitHub, Slack, OIDC, and payload-key secret references are still env-backed today
- placeholder `secret_ref:` and `vault:` reference types still fail closed unless backed by env-compatible resolution

## Build And Configuration Validation

Validate the production compose example:

```bash
docker compose -f compose.prod.example.yml config
make prod-config-check
```

Build images locally from the repo:

```bash
docker compose -f compose.prod.example.yml build
```

The web image now accepts a build-time `NEXT_PUBLIC_API_BASE_URL` so the browser bundle can target the correct external API origin.

## Migrations

Run schema migrations before starting or updating the worker and API fleet:

```bash
make api-migrate
```

Or with the production compose example:

```bash
docker compose -f compose.prod.example.yml --profile ops run --rm migrate
```

Do not rely on opportunistic runtime migration in a multi-instance production rollout.

## Starting The Stack

Example sequence:

1. export or inject the required environment variables
2. validate config
3. run migrations
4. build or pull images
5. start `api`, `web`, `worker`, and `scheduler` when recurring tasks are enabled

Example:

```bash
docker compose -f compose.prod.example.yml config
docker compose -f compose.prod.example.yml --profile ops run --rm migrate
docker compose -f compose.prod.example.yml up -d api web worker scheduler
AGENTGATE_VALIDATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_VALIDATE_WEB_URL=https://agentgate.example.com \
AGENTGATE_VALIDATE_EMAIL=owner@example.com \
AGENTGATE_VALIDATE_PASSWORD='<password>' \
AGENTGATE_VALIDATE_TENANT_SLUG=customer-tenant \
python scripts/validate-deployment.py
```

## First Operator Account

Do not use seeded demo credentials in production.

The supported first-user workflow is:

- deploy a clean environment with no users
- temporarily configure a distinct strong `AGENTGATE_BOOTSTRAP_TOKEN` and pass it via `X-AgentGate-Bootstrap-Token` on `POST /v1/auth/bootstrap` to create the first owner, then remove the token and restart
- inject the token into the API service only. With Compose, use a local override for the API environment

After the first user exists, bootstrap is locked by design.

The demo seed command `python -m app.db.seed` is for local development and demos only.

## TLS And Reverse Proxy Expectations

Recommended assumptions:

- terminate TLS at your ingress or reverse proxy
- publish only HTTPS origins externally
- keep `AGENTGATE_PUBLIC_APP_URL` and `AGENTGATE_PUBLIC_API_URL` aligned with those public origins
- expose the container ports on loopback or private networks only unless you have a deliberate edge design

AgentGate itself is not a full reverse proxy, certificate manager, or web-application firewall.

## Health, Readiness, Metrics, And Logs

Primary endpoints:

- `GET /health`
- `GET /ready`
- `GET /metrics`
- `GET /v1/workers/status`

Recommended usage:

- use `/ready` for traffic-gating and deployment readiness
- use `/health` only as lightweight liveness
- scrape `/metrics` from an internal network path
- collect structured container logs centrally
- run `scripts/validate-deployment.py` after startup or upgrade to exercise login plus a small set of safe operator APIs
- load the starter Prometheus and alert rules only on internal monitoring paths, and import the Grafana dashboard as an operator baseline

Readiness already checks:

- database connectivity
- jobs/config summary
- scheduler config summary
- key-provider status
- safe integration/config status
- rate-limiter provider status

Worker liveness is still best observed through logs and `GET /v1/workers/status`; `/ready` does not prove a worker is actively processing jobs.
Scheduler liveness is best observed through logs and scheduler metrics; `/ready` reports safe config status, not a fleet heartbeat.

For the shipped monitoring assets, see `docs/operations/observability-package.md`.

## Backup And Restore

You still need to provide:

- PostgreSQL backup schedules
- Redis recovery expectations appropriate for your deployment
- restore drills for the PostgreSQL database
- retention and recovery of external audit-anchor object storage if checkpoint anchoring is enabled
- recovery of secret-manager and KMS access required to decrypt payloads
- retention for exported logs and operational logs

Redis can usually be treated as reconstructable operational state, but PostgreSQL holds the durable system of record for tenants, users, policies, tool calls, approvals, audit events, and jobs.

Use `docs/operations/backup-and-restore.md` as the operator guide for backup scope, secure dump examples, restore sequence, and post-restore validation.

## Upgrades And Rollback

See `docs/operations/production-runbook.md` for the step-by-step procedure.

At a minimum:

- take a database backup before migrations
- run migrations in a controlled step
- roll out web and API together when browser configuration changes
- keep the previous image available for rollback
- understand whether a migration is backward compatible before reverting the app image
- keep the post-restore validation account and recovery drill steps documented ahead of the upgrade window

## Known Limitations

- this repo now offers a Compose baseline plus a separate AWS ECS/Fargate Terraform starter, not a single universal platform module
- the ECS/Fargate starter still assumes existing VPC, registry, RDS, Redis, KMS, DNS, and secret-management primitives rather than provisioning a complete platform
- no built-in HA topology, autoscaling, or managed failover
- the built-in recurring scheduler is intentionally simple and not a full distributed orchestration platform
- no lease renewal for genuinely long-running worker jobs yet
- no broader cloud deployment modules for GCP or Azure
- external audit checkpoint anchoring now exists, but immutable evidence claims still depend on destination-side WORM or Object Lock controls
- no managed certificate automation or ingress stack in-repo
