# AWS ECS/Fargate Deployment

AgentGate now includes an AWS ECS/Fargate deployment starter under `deploy/aws/ecs/`.

This is a practical cloud deployment foundation for controlled pilots and high-touch self-hosted evaluations.
It preserves the same runtime assumptions as the production Compose profile:

- external PostgreSQL
- external Redis
- AWS KMS-backed payload protection
- dedicated API, web, worker, and optional scheduler processes
- explicit one-off migrations
- operator-managed observability, backups, and rollback

This is not a claim of enterprise GA, managed SaaS, HA maturity, or compliance certification.

## Architecture

The ECS/Fargate starter assumes a split similar to `compose.prod.example.yml`:

- `api` ECS service behind an ALB target group
- `web` ECS service behind an ALB target group
- `worker` ECS service without public ingress
- optional `scheduler` ECS service without public ingress
- one-off `migrate` task definition for `alembic upgrade head`

The starter expects these resources to exist already:

- VPC
- ALB-capable subnets
- private service subnets
- external RDS PostgreSQL
- external ElastiCache Redis
- a KMS key for payload protection
- container images in an existing registry such as ECR
- Secrets Manager or SSM parameters for runtime secrets

The Terraform module creates only the deployment scaffolding around those resources:

- ECS cluster
- ALB, listeners, and target groups
- ECS task definitions and services
- CloudWatch log groups
- starter security groups
- IAM task execution and runtime roles

## Files

- `deploy/aws/ecs/versions.tf`
- `deploy/aws/ecs/variables.tf`
- `deploy/aws/ecs/locals.tf`
- `deploy/aws/ecs/main.tf`
- `deploy/aws/ecs/outputs.tf`
- `deploy/aws/ecs/terraform.tfvars.example`

## Required AWS Resources

Provide these before planning or applying the module:

- existing VPC ID
- ingress-capable ALB subnet IDs
- private ECS service subnet IDs
- DNS names for the browser and API hosts
- ACM certificate ARN if you want HTTPS on the ALB
- image URIs for the API image and web image
- secret ARN or parameter ARN for:
  - `AGENTGATE_SECRET_KEY`
  - `AGENTGATE_DATABASE_URL`
  - `AGENTGATE_REDIS_URL`
- payload KMS key ARN

Common optional resources:

- existing RDS security group ID so the starter can add ingress from ECS tasks
- existing Redis security group ID so the starter can add ingress from ECS tasks
- Secrets Manager or SSM entries for GitHub, Slack, OIDC, or connector credentials
- audit-checkpoint S3 bucket if external checkpoint anchoring is enabled

## Environment Variables And Secrets

The Terraform starter keeps the same configuration shape as the production Compose profile.

For a service-by-service mapping of non-secret environment variables, secret ARNs, deployment-only inputs, and never-commit values, see [`docs/operations/ecs-secrets-and-env.md`](ecs-secrets-and-env.md).
Use the `*_additional_environment` maps for non-secret values only, and use `*_secret_arns` or the dedicated secret ARN inputs for secret injection.
For a practical pre-production operator walkthrough, see the rehearsal runbook at [`docs/operations/aws-ecs-rehearsal.md`](aws-ecs-rehearsal.md).

Non-secret environment variables are rendered into task definitions for:

- public URLs
- CORS origins
- worker, scheduler, and rate-limiter settings
- audit-integrity anchoring mode
- KMS region and KMS key reference
- `NEXT_PUBLIC_API_BASE_URL` for the web service

Secret values are injected by ARN reference through ECS task definition `secrets`, not hardcoded into Terraform.

Expected secret inputs include:

- `secret_key_secret_arn`
- `database_url_secret_arn`
- `redis_url_secret_arn`
- optional connector secret ARNs such as GitHub or Slack
- optional per-service secret maps for additional runtime settings

The starter keeps KMS references explicit:

- `payload_kms_key_arn` is used for IAM permissions
- the same value is exposed to the runtime as `AGENTGATE_AWS_KMS_KEY_ID`

## IAM And Network Boundaries

The starter now separates IAM and network posture in a minimal way:

- one shared ECS task execution role resolves image pulls, CloudWatch logs, and secret references
- one runtime IAM role is shared by `api`, `worker`, `scheduler`, and `migrate` because those tasks may need KMS-backed payload access and optional audit-checkpoint object-storage access
- the `web` task uses a separate runtime IAM role without the KMS or checkpoint-bucket permissions granted to app-like tasks
- the ALB targets separate task security groups for `api` and `web`
- `worker`, optional `scheduler`, and one-off `migrate` use a background-task security group with no ALB ingress rule

This is still a starter. Outbound egress remains broad by default and should be narrowed to your actual database, cache, VPC endpoint, proxy, and observability paths before production use.

## Image Publishing Expectations

The Terraform starter does not build or publish images.

You are expected to publish:

- an API image containing the FastAPI app, worker entrypoint, scheduler entrypoint, and Alembic
- a web image containing the production Next.js app

The default shape is:

- `api_image_uri` for `api`, `worker`, `scheduler`, and `migrate`
- `web_image_uri` for `web`

Keep the API and web image tags aligned for a given rollout.

## Validation And Planning

Safe local validation:

```bash
python scripts/check-no-live-secrets.py
docker compose config
docker compose -f compose.prod.example.yml config
terraform -chdir=deploy/aws/ecs fmt -check
terraform -chdir=deploy/aws/ecs init -backend=false
terraform -chdir=deploy/aws/ecs validate
```

Safe GitHub-first validation path:

- use the `Terraform ECS Validation` GitHub Actions workflow in [`.github/workflows/terraform-ecs-validate.yml`](../../.github/workflows/terraform-ecs-validate.yml)
- it runs `fmt -check`, `init -backend=false`, and `validate` on `ubuntu-latest`
- it does not require AWS credentials because it does not run `plan` or `apply`
- prefer this path when a local workstation has machine-specific Terraform provider issues, such as Windows proxy or TLS/plugin-handshake failures

Optional helper targets:

```bash
make aws-ecs-fmt
make aws-ecs-validate
AWS_ECS_TFVARS=/path/to/terraform.tfvars make aws-ecs-plan
```

Planning requires a real `terraform.tfvars` file with your resource IDs, image URIs, and secret ARNs.
Applying the plan requires AWS credentials and real infrastructure inputs.
Before the first AWS pilot rollout, walk through [`docs/operations/aws-ecs-rehearsal.md`](aws-ecs-rehearsal.md) and capture the evidence it calls for.

## Migration Flow

Do not rely on application startup to run schema changes.

Recommended sequence:

1. Build or publish the new API and web images.
2. Update the Terraform inputs to reference the new image tags if needed.
3. Run the one-off ECS migration task using the `migrate` task definition.
4. Confirm the migration task exits successfully.
5. Update the long-running ECS services.
6. Run `scripts/validate-deployment.py` against the deployed URLs.

The Terraform outputs include a starter `aws ecs run-task` command shape for the migration task.

## Rollout And Rollback

Typical rollout shape:

1. Validate Terraform and review the plan.
2. Confirm PostgreSQL backup coverage before migrations.
3. Run the migration task.
4. Update `api`, `worker`, and optional `scheduler`.
5. Update `web`.
6. Recheck `/ready`, `/metrics`, operator login, and worker status.

Rollback guidance:

- if the migration is backward compatible, redeploy the previous image tags
- if the migration is not backward compatible, stop write traffic, restore PostgreSQL if needed, and redeploy the previous images
- keep the previous image tags and restore steps documented before the maintenance window

As with the Compose profile, rollback safety depends on migration compatibility.

## Logging And Monitoring Expectations

The starter creates CloudWatch log groups for:

- `api`
- `web`
- `worker`
- `scheduler`
- `migrate`

You are still expected to provide:

- log retention policy review
- alert routing
- `/metrics` scraping path
- dashboard import and ownership
- worker and scheduler health review
- deployment validation after each rollout

Use the existing observability assets as starter material:

- `observability/prometheus/prometheus.yml`
- `observability/prometheus/alert-rules.yml`
- `observability/grafana/agentgate-overview-dashboard.json`

## Known Limitations

- this is a deployment starter, not full AWS platform provisioning
- VPC, subnets, registry, RDS, Redis, KMS, and DNS are assumed to exist already
- outbound task security-group egress is intentionally broad by default and should be tightened by the operator for a real environment
- API, worker, scheduler, and migrate still share one application runtime IAM role; if you need stricter service-by-service IAM separation, extend the starter before treating it as a hardened platform baseline
- no autoscaling policies are included
- no Route 53, WAF, CloudFront, or ACM certificate automation is included beyond optional certificate attachment
- no multi-region or disaster-recovery orchestration is included
- no Kubernetes, Helm, or broader cloud portability layer is included
- no managed backup orchestration is included
- external checkpoint anchoring is stronger than DB-only evidence, but it is not an immutability claim unless the destination itself enforces WORM or Object Lock semantics
- unrestricted MCP remains out of scope; keep MCP internal and tightly allowlisted if used at all

## What Is Not Production-Complete Yet

This starter does not make AgentGate a fully managed enterprise platform.

It does not provide:

- managed SaaS operations
- compliance certification
- HA policy or SLO guarantees
- autoscaling tuning
- blue/green orchestration
- platform-wide secret rotation workflows
- full SCIM or SAML identity governance
- full cloud landing-zone provisioning

Treat this as a credible ECS/Fargate baseline for controlled-pilot deployment work, not the end state of enterprise platform engineering.
