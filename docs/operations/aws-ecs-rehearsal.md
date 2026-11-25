# AWS ECS/Fargate Rehearsal

Use this runbook to rehearse the AgentGate AWS ECS/Fargate starter in a controlled environment before you treat it as production-like for a pilot.

This guide is intentionally conservative:

- it assumes operator-owned AWS credentials and AWS CLI access
- it assumes Terraform state, AWS account policy, and rollout approval are managed outside this repo
- it does not claim that this exact flow has been exercised in a live AWS account from this repository
- it does not claim HA, multi-region, compliance, or managed-platform maturity

Use this guide with:

- [AWS ECS/Fargate Deployment](aws-ecs-deployment.md)
- [ECS Secrets And Environment Mapping](ecs-secrets-and-env.md)
- [Deployment Validation](deployment-validation.md)
- [Backup And Restore](backup-and-restore.md)
- [Production Runbook](production-runbook.md)

## Rehearsal Goal

The goal is to prove that operators can:

- prepare external AWS dependencies and runtime secrets safely
- produce a clean Terraform plan for the ECS starter
- run the one-off migration task separately from long-running services
- bring up `api`, `web`, `worker`, and optional `scheduler` through the Terraform-managed service definitions
- verify ALB health, CloudWatch logs, readiness, metrics posture, and worker status
- capture enough evidence to decide whether the starter is usable for a controlled pilot

This is not a substitute for restore drills, load testing, or full production readiness review.

## Prerequisites

Before the rehearsal window:

- Terraform is installed on the operator workstation
- AWS CLI is installed and authenticated to the target account
- the operator can read the chosen Secrets Manager secrets or SSM parameters
- the operator can read CloudWatch Logs, ECS, ELBv2, IAM, and target VPC metadata
- a PostgreSQL backup or snapshot plan exists for the rehearsal environment
- the API and web images for the target release already exist in the registry
- the operator has the values required by `deploy/aws/ecs/terraform.tfvars.example`

Recommended local preflight from the repo root:

```bash
python scripts/check-no-live-secrets.py
docker compose config
docker compose -f compose.prod.example.yml config
terraform -chdir=deploy/aws/ecs fmt -check
terraform -chdir=deploy/aws/ecs init -backend=false
terraform -chdir=deploy/aws/ecs validate
```

If the operator workstation has a machine-specific Terraform provider/runtime problem, such as a local Windows proxy or TLS handshake failure, use the `Terraform ECS Validation` GitHub Actions workflow in [`.github/workflows/terraform-ecs-validate.yml`](../../.github/workflows/terraform-ecs-validate.yml) as the clean Linux preflight for these three commands before the rehearsal window.

## Required AWS Resources

The starter does not create a full AWS platform. The rehearsal environment must already have:

- an existing VPC
- ALB-capable subnets for ingress
- private ECS service subnets
- external PostgreSQL, such as RDS
- external Redis, such as ElastiCache
- an AWS KMS key for payload protection when `AGENTGATE_KEY_PROVIDER=aws_kms`
- container image hosting, such as ECR
- Secrets Manager secrets or SSM parameters for runtime secrets
- DNS ownership and ACM certificate ownership if you intend to test real HTTPS hosts

Optional but commonly needed:

- existing RDS and Redis security groups that can accept ingress from ECS tasks
- object-storage destination for audit-integrity checkpoint anchoring
- central log retention and alerting ownership outside this repo

## Image Build And Publish Expectations

The rehearsal assumes images are already built and pushed.

Expected image shape:

- one API image used by `api`, `worker`, `scheduler`, and `migrate`
- one web image used by `web`

Check before planning:

- `api_image_uri` points at the intended release tag
- `web_image_uri` points at the matching release tag
- the API image includes `uvicorn`, `app.worker`, `app.scheduler`, and Alembic
- the web image serves the production Next.js app

Do not start a rehearsal with mutable tags such as `latest`.

## Prepare `terraform.tfvars`

Start from `deploy/aws/ecs/terraform.tfvars.example` and create an operator-local `terraform.tfvars` outside the repository when possible.

Populate at minimum:

- AWS region and naming prefix
- VPC ID, ALB subnet IDs, and ECS service subnet IDs
- public app and API URLs plus hostnames
- optional ACM certificate ARN for HTTPS
- `api_image_uri` and `web_image_uri`
- secret ARN inputs for `AGENTGATE_SECRET_KEY`, database URL, and Redis URL
- KMS key ARN
- CORS origins
- optional RDS and Redis security group IDs

Use [ECS Secrets And Environment Mapping](ecs-secrets-and-env.md) while filling:

- non-secret values belong in Terraform variables or `*_additional_environment`
- secret values belong in Secrets Manager or SSM and are referenced through secret ARN variables
- do not place live secrets into `terraform.tfvars`

## Validation And Safe Planning

From the repo root, run:

```bash
terraform -chdir=deploy/aws/ecs fmt -check
terraform -chdir=deploy/aws/ecs init -backend=false
terraform -chdir=deploy/aws/ecs validate
terraform -chdir=deploy/aws/ecs plan -var-file=/secure/path/terraform.tfvars
```

If you prefer the helper target for planning:

```bash
AWS_ECS_TFVARS=/secure/path/terraform.tfvars make aws-ecs-plan
```

### Plan Review Checklist

Review the plan before any apply step. Do not treat a successful plan as approval by itself.

Confirm that the plan:

- references the expected VPC and subnet IDs
- uses the intended `api_image_uri` and `web_image_uri`
- does not show literal secret values
- keeps the migration task separate from ECS services
- creates or updates only the expected ALB, ECS, log-group, IAM, and security-group scaffolding
- does not unexpectedly replace critical resources because of naming or subnet drift
- keeps `worker` and optional `scheduler` off public ingress
- keeps `/metrics` as an operator-owned internal path rather than an internet-facing promise

No-go immediately if the plan suggests:

- accidental deletion or replacement of the live ALB without an approved maintenance path
- unexpected changes to unrelated networking or IAM resources
- literal secrets in output or operator terminal capture
- image tags that do not match the intended release
- public exposure for worker or scheduler paths

## Apply Ownership

This repository does not automate `terraform apply`.

After the plan is reviewed and approved, an operator may run the apply step manually from a credentialed workstation using the same `terraform.tfvars` file.

Keep ownership explicit:

- AWS credentials are operator-managed
- Terraform backend choice is operator-managed
- maintenance-window approval is operator-managed
- rollback authorization is operator-managed

## Rehearsal Sequence

Use a quiet maintenance window or an isolated pilot environment.

Suggested order:

1. Confirm PostgreSQL backup or snapshot coverage for the rehearsal target.
2. Confirm the image tags and secret references in `terraform.tfvars`.
3. Run Terraform validation and review the plan.
4. Apply the reviewed plan manually using your normal Terraform workflow.
5. Run the one-off migration task before cutting traffic to the new app revision.
6. Confirm the migration task exits successfully and review its CloudWatch logs.
7. Confirm the long-running ECS services are created or updated:
   - `api`
   - `worker`
   - optional `scheduler`
   - `web`
8. Wait for ALB target health to go healthy for `api` and `web`.
9. Run deployment validation against the deployed URLs.
10. Review worker and scheduler posture before declaring the rehearsal successful.

## Run The One-Off Migration Task

Do not rely on service startup for schema changes.

Use the Terraform output `migration_run_task_example` as a starting point, or run the equivalent `aws ecs run-task` command with:

- the created ECS cluster
- the `migration_task_definition_arn`
- service subnet IDs
- the background task security group
- the same launch type and network shape used by the starter

Success criteria:

- the task reaches `STOPPED`
- the exit code is `0`
- the CloudWatch log stream for `/ecs/<name-prefix>/migrate` shows a clean Alembic upgrade

No-go if:

- the task cannot pull the image
- secret injection fails
- database connectivity fails
- Alembic fails or attempts an unexpected downgrade path

## Start Or Update ECS Services

For this starter, the long-running services are Terraform-managed. Do not manually drift them unless you are performing an emergency rollback.

After apply, confirm that ECS reflects the intended services:

- `api` service desired count matches the rehearsal plan
- `web` service desired count matches the rehearsal plan
- `worker` service desired count matches the rehearsal plan
- `scheduler` exists only when `enable_scheduler=true`

Check that:

- `api` and `web` have ALB target groups attached
- `worker` and `scheduler` do not have public ingress
- `worker` and `scheduler` use the background task security group

## CloudWatch Logs Review

Review these log groups:

- `/ecs/<name-prefix>/api`
- `/ecs/<name-prefix>/web`
- `/ecs/<name-prefix>/worker`
- `/ecs/<name-prefix>/scheduler`
- `/ecs/<name-prefix>/migrate`

Operator checks:

- no crash-loop pattern after rollout
- no secret values emitted in logs
- API startup reaches readiness cleanly
- web startup serves the login page
- worker logs show job-polling startup without broker or database failures
- scheduler logs show startup cleanly when enabled

## ALB Target Health Review

Confirm both target groups move to healthy:

- API target group health aligns with the `/ready` path
- web target group health aligns with the configured login-page probe

No-go if:

- targets flap between healthy and unhealthy
- the API never becomes ready
- the web target does not serve the login path

## Deployment Validator

Run the existing deployment validator after the services are healthy:

```bash
AGENTGATE_VALIDATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_VALIDATE_WEB_URL=https://agentgate.example.com \
AGENTGATE_VALIDATE_EMAIL=owner@example.com \
AGENTGATE_VALIDATE_PASSWORD='<password>' \
AGENTGATE_VALIDATE_TENANT_SLUG=customer-tenant \
python scripts/validate-deployment.py
```

This is a smoke test, not proof of full platform health. Pair it with CloudWatch log review and worker checks.

## Readiness And Metrics Posture

Check these surfaces intentionally:

- `GET /health` for liveness only
- `GET /ready` for readiness gating
- `GET /metrics` only from an internal or explicitly controlled path

For the ECS starter, do not treat `/metrics` as a public endpoint requirement. If the only reachable path is private, that is acceptable and preferable.

## Worker And Scheduler Verification

The deployment validator does not prove background progress by itself.

Review:

- `GET /v1/workers/status`
- worker CloudWatch logs
- scheduler CloudWatch logs when `enable_scheduler=true`

Confirm that:

- at least one worker reports healthy
- the worker is using the expected queue/broker settings
- the scheduler is present only when enabled
- there is no repeated reconnect or crash-loop behavior

## Rollback Approach

Rollback depends on migration compatibility and must be decided before the rehearsal window.

Recommended stance:

- keep the previous API and web image tags available
- document whether the migration is backward compatible
- if backward compatible, redeploy the previous image tags through Terraform-managed inputs
- if not backward compatible, stop write traffic, restore PostgreSQL if needed, and then redeploy the earlier images

Do not assume that an image rollback alone is safe after every schema change.

## Evidence To Capture

Capture enough evidence for a later go/no-go review:

- Terraform `fmt -check` and `validate` output
- approved Terraform plan artifact or terminal capture with secrets redacted
- the image tags used for `api_image_uri` and `web_image_uri`
- migration task ARN, stop status, and exit code
- CloudWatch log references for `migrate`, `api`, `web`, `worker`, and optional `scheduler`
- ALB target health screenshots or exported state
- deployment validator output
- `/ready` response confirmation
- `/metrics` access-path notes showing it is not unintentionally public
- `GET /v1/workers/status` result
- backup or snapshot confirmation captured before migration
- any manual deviations, exceptions, or rollback decisions

## No-Go Conditions

Stop the rehearsal and escalate if any of the following is true:

- Terraform plan contains unexpected destructive changes
- live secrets are visible in plan output, logs, or shell history
- migration task fails
- API or web target health never stabilizes
- worker cannot reach Redis or PostgreSQL
- scheduler crash-loops when enabled
- deployment validator fails on core API or login checks
- `/metrics` is publicly exposed without explicit approval
- backup coverage is missing or unverified before a schema-changing rollout

## What A Successful Rehearsal Proves

A successful rehearsal shows that the current starter is capable of supporting:

- operator-managed Terraform planning and rollout
- separate migration execution
- ECS service startup with external PostgreSQL, Redis, KMS, and secret-manager dependencies
- basic ALB, log, readiness, and worker verification

It does not prove:

- HA or regional failover
- autoscaling behavior
- restore time objectives
- compliance posture
- full least-privilege IAM hardening
- full network egress hardening
- external connector correctness
