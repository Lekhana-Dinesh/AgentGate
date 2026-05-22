# Production Runbook

This runbook is the operator-facing procedure for deploying, validating, upgrading, and recovering a self-hosted AgentGate environment.

Use it together with:

- `docs/operations/self-hosted-deployment.md`
- `docs/operations/aws-ecs-deployment.md`
- `docs/operations/backup-and-restore.md`
- `docs/operations/deployment-hardening.md`
- `docs/operations/production-readiness-checklist.md`

## Scope

This runbook assumes:

- either `compose.prod.example.yml` or `deploy/aws/ecs/`
- external PostgreSQL
- external Redis
- a dedicated `worker` process
- a dedicated `scheduler` process when recurring tasks are enabled
- TLS termination handled by an external reverse proxy or ingress

## Pre-Deployment Checks

Before the first deployment or any upgrade:

1. Confirm the repo revision or image tag you intend to deploy.
2. Confirm PostgreSQL connectivity and backup coverage.
3. Confirm Redis connectivity and access controls.
4. Confirm required secrets and public URLs are injected.
5. Confirm the KMS key exists and IAM permissions are in place if `AGENTGATE_KEY_PROVIDER=aws_kms`.
6. If using Compose, run `docker compose -f compose.prod.example.yml config`.
7. If using the ECS/Fargate starter, run `terraform -chdir=deploy/aws/ecs validate` and review the plan inputs.
8. Review `GET /ready` expectations and alerting destinations.
9. Run `python scripts/check-recovery-readiness.py --env-file /etc/agentgate/pilot.env ...` with the backup, rollback, Redis, and checkpoint-review confirmations you intend to rely on during the window.

## Initial Deployment

1. Build or pull the `api` and `web` images.
2. Run database migrations:

```bash
docker compose -f compose.prod.example.yml --profile ops run --rm migrate
```

If you are using the ECS/Fargate starter instead of Compose, run the one-off `migrate` task described in `docs/operations/aws-ecs-deployment.md`, then update the long-running ECS services.

3. Start the stack:

```bash
docker compose -f compose.prod.example.yml up -d api web worker scheduler
```

4. Wait for service health checks to pass.
5. Verify:
   - `GET /health`
   - `GET /ready`
   - `GET /metrics` from an internal path
   - `python scripts/validate-deployment.py` with an expected operator account
   - Prometheus can scrape `/metrics` from its internal path
   - starter alert rules are loaded if you are using Prometheus alerting
6. Create the first owner only if the environment has no users yet:
   - call `POST /v1/auth/bootstrap`
7. Disable any temporary bootstrap access workflows after the first owner is created.

## Routine Validation

After deployment, confirm:

- `GET /ready` returns `200`
- the web login page loads through the reverse proxy
- local login works for an expected operator account
- `scripts/validate-deployment.py` succeeds against the live deployment
- `GET /v1/workers/status` shows at least one active worker
- the scheduler container is running if recurring tasks are enabled
- the worker is consuming jobs normally
- logs show no startup validation failure
- the dashboard import and alerting path still match the current deployment if you use the starter observability assets

## Upgrade Procedure

1. Review release notes, schema changes, and operator-facing changes.
2. Take or confirm a fresh PostgreSQL backup.
3. Stage the new images or build the new revision.
4. Run migrations on the new revision:

```bash
docker compose -f compose.prod.example.yml --profile ops run --rm migrate
```

If you are using the ECS/Fargate starter, run the migration task against the new task definition before rolling the long-running services.

5. Roll the `api`, `worker`, and `scheduler` services to the new version.
6. Roll the `web` service to the new version, especially if `NEXT_PUBLIC_API_BASE_URL` or browser behavior changed.
7. Recheck:
   - `/ready`
   - `/metrics`
   - `scripts/validate-deployment.py`
   - `/v1/workers/status`
   - operator login
   - one representative dashboard page

If the rollout introduces configuration changes, validate those in staging first.

## Rollback Procedure

Rollback depends on migration compatibility.

Application-only rollback:

1. If the migration was backward compatible, redeploy the previous `api`, `web`, `worker`, and `scheduler` images.
2. Recheck readiness, worker status, and scheduler logs.

Database-involved rollback:

1. Stop write traffic if the migration is not backward compatible.
2. Restore PostgreSQL from a known-good backup if necessary.
3. Redeploy the previous application version.
4. Revalidate login, readiness, worker processing, and audit-integrity status.

Do not assume every migration is reversible. Review each migration deliberately before deployment.

Recommended evidence before the window opens:

- previous release or image reference retained
- migration compatibility reviewed and recorded
- fresh PostgreSQL backup confirmed
- isolated restore target identified
- Redis recovery expectations reviewed
- audit-integrity checkpoint recovery reviewed if external anchoring is enabled

## Worker Operations

Expected worker checks:

- the `worker` container is running
- `GET /v1/workers/status` shows at least one active worker
- job backlog is not growing unexpectedly
- dead-letter or retry-exhausted jobs are reviewed

Expected scheduler checks:

- the `scheduler` container is running when recurring tasks are enabled
- due scheduled-task counts are not growing unexpectedly
- scheduler logs show normal enqueue activity rather than repeated config failures

If the worker is unhealthy:

1. inspect worker logs
2. inspect Redis connectivity if `AGENTGATE_JOB_BROKER=redis`
3. inspect database connectivity
4. inspect `/v1/workers/status`
5. restart the worker only after identifying whether jobs are safe to resume

Approved execution is intentionally not blindly retried.

## Backup And Restore

Minimum expectations:

- scheduled PostgreSQL backups
- tested PostgreSQL restore path
- documented recovery of external audit-anchor storage when checkpoint anchoring is enabled
- documented recovery of secret-manager and KMS access required for payload decryption
- retention policy for logs and exported audit evidence
- documented recovery-time expectations for Redis

Restore drill guidance:

1. restore PostgreSQL into an isolated environment
2. restore or confirm access to external audit-anchor storage if checkpoint anchoring is enabled
3. inject the environment, secret-manager, and KMS configuration required by the restored environment
4. start `api`, `web`, `worker`, and `scheduler` against that restored database
5. run `make verify-restore`
6. confirm `/v1/workers/status`, operator login, and representative data visibility
7. confirm `/v1/audit-integrity/status` and verify the latest checkpoint if external anchoring exists
8. record the actual recovery duration and any missing manual steps

See `docs/operations/backup-and-restore.md` for command examples and the full post-restore checklist.

The recovery readiness checker is intentionally non-destructive and helps collect this evidence ahead of the drill:

```bash
python scripts/check-recovery-readiness.py \
  --env-file /etc/agentgate/pilot.env \
  --backup-confirmed \
  --restore-target-confirmed \
  --previous-release-ref agentgate-2026-05-22 \
  --migration-compatibility unknown \
  --redis-recovery-reviewed \
  --audit-anchor-reviewed \
  --kms-recovery-reviewed
```

## Metrics And Logs

Scrape:

- `GET /metrics`

Monitor:

- repeated readiness failures
- rate-limited spikes
- job failures
- retry exhaustion
- stale recovery spikes
- dead-letter growth
- worker heartbeat degradation
- audit export failures

Starter assets:

- `observability/prometheus/prometheus.yml`
- `observability/prometheus/alert-rules.yml`
- `observability/grafana/agentgate-overview-dashboard.json`

Treat these as baseline examples, not a full monitoring program.

Collect structured logs for:

- API
- worker
- scheduler
- reverse proxy / ingress

## Incident Handoff

If a deployment incident might involve security impact, also follow:

- `SECURITY.md`
- `docs/security/INCIDENT_RESPONSE.md`

## Known Gaps

- the built-in recurring scheduler is intentionally simple and not a full distributed orchestration platform
- no in-repo HA/failover automation
- external audit checkpoint anchoring now exists, but it is not a valid immutability claim unless the destination itself enforces WORM or Object Lock semantics
- no Kubernetes, Helm, or broader HA cloud orchestration profile yet; the ECS/Fargate Terraform starter is still a deployment foundation rather than a full platform module
