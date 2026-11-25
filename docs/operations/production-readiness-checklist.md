# Production Readiness Checklist

Use this checklist before treating a self-hosted AgentGate deployment as production-like for a controlled pilot.

## Configuration

- `AGENTGATE_ENV=production`
- `AGENTGATE_SECRET_KEY` is strong and rotated through your secret process
- `AGENTGATE_PUBLIC_APP_URL` is an external HTTPS origin
- `AGENTGATE_PUBLIC_API_URL` is an external HTTPS origin
- `AGENTGATE_CORS_ORIGINS` lists only explicit allowed browser origins
- `AGENTGATE_JOB_DISPATCH_MODE=worker`
- `AGENTGATE_JOB_BROKER=redis`
- `AGENTGATE_RATE_LIMIT_ENABLED=true`
- `AGENTGATE_RATE_LIMIT_PROVIDER=redis`
- `AGENTGATE_ALLOW_DEMO_CREDENTIALS=false`
- `AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage` is configured if you want external checkpoint anchoring outside development and test
- `AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET` and `AGENTGATE_AUDIT_INTEGRITY_S3_REGION` are set when using object-storage anchoring

## Database And Cache

- PostgreSQL is external to the compose stack
- PostgreSQL backups exist and restores have been tested
- PostgreSQL backup retention and encryption are defined outside the repo
- Redis is external to the compose stack
- Redis is not publicly exposed
- network access to PostgreSQL and Redis is restricted

## Key Management And Secrets

- `AGENTGATE_KEY_PROVIDER=aws_kms` is configured, or the env-provider tradeoff is explicitly accepted
- `AGENTGATE_AWS_REGION` is set if using AWS KMS
- `AGENTGATE_AWS_KMS_KEY_ID` is set if using AWS KMS
- IAM access to KMS is least-privilege
- runtime secrets are injected externally and not committed to git
- placeholder `secret_ref:` and `vault:` references are not being relied on without env-backed resolution
- audit-checkpoint object-storage credentials use IAM or secret references injected at runtime and are not stored in the database
- KMS access recovery and secret-manager recovery are documented for restore events

## Deployment

- `docker compose -f compose.prod.example.yml config` passes
- `terraform -chdir=deploy/aws/ecs validate` passes if you are using the ECS/Fargate starter
- `docs/operations/aws-ecs-rehearsal.md` has been followed for the target AWS environment if you are using the ECS/Fargate starter
- database migrations run successfully before traffic cutover
- `api`, `web`, and `worker` start successfully
- `scheduler` starts successfully when recurring tasks are enabled
- the web build is pointed at the correct external API origin
- TLS termination is in place at the reverse proxy or ingress

## Operations

- `GET /health` is monitored as liveness only
- `GET /ready` is monitored for readiness gating
- `GET /metrics` is scraped from an internal path
- starter Prometheus and Grafana assets are imported or deliberately replaced if you are operating AgentGate with Prometheus
- starter alert rules are loaded or deliberately replaced if you are using Prometheus alerting
- `scripts/validate-deployment.py` is part of the post-start and post-upgrade operator checklist
- `make verify-restore` or the equivalent validator command is part of the restore-drill checklist
- structured logs are collected centrally
- `GET /v1/workers/status` is part of operator health checks
- worker restart procedure is documented
- scheduler restart procedure is documented if recurring tasks are enabled
- audit-checkpoint failure handling and re-run procedure are documented if external checkpoint anchoring is enabled
- restore verification includes `GET /v1/audit-integrity/status` and latest-checkpoint review when checkpointing is enabled

## Security

- demo credentials are not seeded into production
- first-user creation uses `POST /v1/auth/bootstrap` on a clean environment with a temporary `AGENTGATE_BOOTSTRAP_TOKEN` supplied via `X-AgentGate-Bootstrap-Token`
- `/metrics` is not exposed publicly
- reverse proxy and network ACLs limit public exposure appropriately
- GitHub, Jira, MCP, Slack, OIDC, and payload-key secrets are not stored in database config
- audit-checkpoint cloud credentials are not stored in database config
- database dumps and backup archives are not stored in git or on shared operator workstations without access controls
- at least one active owner remains in every production tenant before enforcing user deactivation workflows
- operator runbooks document how user deactivation affects existing JWTs and user-created agent API keys
- if stronger immutability claims matter, the object-storage destination uses versioning plus Object Lock or another real WORM control
- if external checkpoint anchoring matters for evidence recovery, the checkpoint bucket or prefix has its own backup, retention, and access policy

## Change Management

- upgrade procedure is documented
- rollback procedure is documented
- previous image version is retained for rollback
- migration compatibility has been reviewed before deployment

## Honest Remaining Gaps

- no Kubernetes/Helm deployment profile in-repo, and the ECS/Fargate Terraform starter still assumes existing cloud primitives rather than provisioning a full AWS platform
- the built-in recurring scheduler is intentionally simple and not leader-elected
- the current identity lifecycle foundation is deactivation-first, with a minimal SCIM `/Users` surface rather than full SCIM identity governance
- the shipped observability assets are only starter files and do not replace a full monitoring stack, dashboard program, or alert-routing setup
- external checkpoint anchoring is available, but it is not a valid immutability claim unless the destination itself enforces WORM or Object Lock semantics
- no lease-renewal mechanism for long-running jobs yet
