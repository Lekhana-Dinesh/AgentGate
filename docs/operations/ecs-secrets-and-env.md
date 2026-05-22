# ECS Secrets And Environment Mapping

This guide maps the AWS ECS/Fargate starter under `deploy/aws/ecs/` into four operator-facing buckets:

1. non-secret environment variables rendered into ECS task definitions
2. secret values injected through ECS `secrets` from AWS Secrets Manager or SSM
3. deployment-time Terraform inputs used to shape AWS resources
4. values that must never be committed to git

Use this guide together with:

- `deploy/aws/ecs/variables.tf`
- `deploy/aws/ecs/locals.tf`
- `docs/operations/aws-ecs-deployment.md`
- `compose.prod.example.yml`
- `.env.example`

## Rules

- Use `shared_additional_environment`, `api_additional_environment`, `worker_additional_environment`, `scheduler_additional_environment`, and `web_additional_environment` for non-secret values only.
- Use `shared_secret_arns`, `api_secret_arns`, `worker_secret_arns`, `scheduler_secret_arns`, and `web_secret_arns` for secret values only.
- Keep image URIs, subnet IDs, security-group IDs, hostnames, and KMS key ARNs in Terraform variables.
- Keep secret values out of `.tf` files, `terraform.tfvars.example`, `.env.example`, docs, and git-tracked operator notes.

## Service Mapping

| Service | Non-secret env source in ECS | Secret source in ECS | Notes |
| --- | --- | --- | --- |
| `api` | `base_agentgate_env` + `api_additional_environment` | `shared_secret_map` + `api_secret_arns` | Public API behind the ALB. |
| `web` | `NEXT_PUBLIC_API_BASE_URL` + `web_additional_environment` | `web_secret_arns` | Browser frontend. No shared `AGENTGATE_*` base env is injected by default. |
| `worker` | `base_agentgate_env` + `AGENTGATE_WORKER_ID` + `worker_additional_environment` | `shared_secret_map` + `worker_secret_arns` | No public ingress. |
| `scheduler` | `base_agentgate_env` + `scheduler_additional_environment` | `shared_secret_map` + `scheduler_secret_arns` | Optional service. No public ingress. |
| `migrate` | same env map as `api` | same secret map as `api` | One-off task only. Not a long-running ECS service. |

## Runtime Config Table

| Setting name | Purpose | Secret or non-secret | Source in ECS | Used by api/web/worker/scheduler/migrate | Required for minimal pilot | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| `api_image_uri` | API container image for API-like tasks | Non-secret deployment input | Terraform task definition image | `api`, `worker`, `scheduler`, `migrate` | Yes | Keep API, worker, scheduler, and migrate on the same tested image tag. |
| `web_image_uri` | Web container image | Non-secret deployment input | Terraform task definition image | `web` | Yes | Keep aligned with the matching API release. |
| `secret_key_secret_arn` -> `AGENTGATE_SECRET_KEY` | JWT/session signing secret | Secret | ECS `secrets` | `api`, `worker`, `scheduler`, `migrate` | Yes | Must be injected from Secrets Manager or SSM. Never place the raw value in `*_additional_environment`. |
| `database_url_secret_arn` -> `AGENTGATE_DATABASE_URL` | External PostgreSQL connection URL | Secret | ECS `secrets` | `api`, `worker`, `scheduler`, `migrate` | Yes | Treat as secret because it normally embeds credentials. |
| `redis_url_secret_arn` -> `AGENTGATE_REDIS_URL` | External Redis connection URL | Secret | ECS `secrets` | `api`, `worker`, `scheduler`, `migrate` | Yes for worker-mode pilot | Treat as secret because it may embed auth tokens. |
| `public_app_url`, `public_api_url`, `public_app_host`, `public_api_host` | Public browser/API origins and ALB host routing | Non-secret | ECS `environment` plus Terraform listener rules | `api`, `web`, `worker`, `scheduler`, `migrate` for URLs; ALB routing for app/api hosts | Yes | Public URLs and CORS are intentionally non-secret. |
| `cors_origins` | Allowed browser origins | Non-secret | ECS `environment` | `api`, `worker`, `scheduler`, `migrate` | Yes | Serialized into `AGENTGATE_CORS_ORIGINS`. |
| `key_provider`, `aws_region`, `payload_kms_key_arn` | KMS-backed payload protection mode and key reference | Non-secret | ECS `environment`; IAM policy uses `payload_kms_key_arn` | `api`, `worker`, `scheduler`, `migrate` | Yes for recommended production-style pilot | `payload_kms_key_arn` is not a secret, but it is security-sensitive deployment metadata. |
| `payload_encryption_active_key_ref`, `payload_encryption_key_version`, `payload_encryption_additional_keys`, `payload_encryption_additional_key_versions` | Payload envelope metadata and decrypt-only compatibility refs | Non-secret | ECS `environment` | `api`, `worker`, `scheduler`, `migrate` | Usually yes | These are key refs and versions, not raw key material. |
| `shared_secret_arns` | Generic shared secret injection for app-like tasks | Secret | ECS `secrets` | `api`, `worker`, `scheduler`, `migrate` | Optional | Use for additional secrets such as `AGENTGATE_JIRA_TOKEN`, `AGENTGATE_JIRA_API_TOKEN`, `AGENTGATE_MCP_TOKEN`, `AGENTGATE_MCP_API_KEY`, OIDC client secrets, SCIM token env vars, or env-provider payload keys. |
| `api_secret_arns`, `worker_secret_arns`, `scheduler_secret_arns`, `web_secret_arns` | Service-specific secret injection | Secret | ECS `secrets` | Matching service only | Optional | Use when a secret should not be shared across all app-like tasks. |
| `github_token_secret_arn`, `github_app_private_key_secret_arn`, `slack_bot_token_secret_arn` | First-class connector secret refs | Secret | ECS `secrets` | `api`, `worker`, `scheduler`, `migrate` | Optional | These are convenience variables; similar secrets for Jira, MCP, OIDC, or SCIM still go through the generic secret maps. |
| `shared_additional_environment` | Generic shared non-secret environment values | Non-secret | ECS `environment` | `api`, `worker`, `scheduler`, `migrate` | Optional | Do not use this map for secret values. |
| `api_additional_environment`, `worker_additional_environment`, `scheduler_additional_environment`, `web_additional_environment` | Service-specific non-secret environment values | Non-secret | ECS `environment` | Matching service only | Optional | Use for safe flags, hostnames, ref metadata, and other non-secret runtime config. |
| `job_dispatch_mode`, `job_broker`, `AGENTGATE_JOB_*`, `AGENTGATE_SCHEDULER_*`, `AGENTGATE_WORKER_*`, `AGENTGATE_RATE_LIMIT_*` | Worker, scheduler, retry, retention, and rate-limit tuning | Non-secret | ECS `environment` | `api`, `worker`, `scheduler`, `migrate` | Yes for worker mode; defaults cover a minimal pilot | These settings differ operationally, but they are not secrets. |
| `AGENTGATE_WORKER_ID` | Worker identity label | Non-secret | ECS `environment` | `worker` only | Yes for worker | Set automatically to `worker-1` unless overridden. |
| `NEXT_PUBLIC_API_BASE_URL` | Browser-facing API base URL | Non-secret | ECS `environment` | `web` only | Yes | This is also a build-time concern for the Compose production profile, but in ECS it is injected as a runtime env var for the web task definition. |
| `audit_integrity_anchor_type`, `audit_integrity_s3_bucket`, `audit_integrity_s3_prefix`, `audit_integrity_s3_region`, `audit_integrity_s3_endpoint_url` | Audit checkpoint anchoring mode and bucket metadata | Non-secret | ECS `environment` | `api`, `worker`, `scheduler`, `migrate` | Optional | Bucket name and region are not secret; access credentials should come from IAM or secret-backed env vars if ever needed. |
| `AGENTGATE_AUDIT_INTEGRITY_S3_ACCESS_KEY_ID_REF`, `AGENTGATE_AUDIT_INTEGRITY_S3_SECRET_ACCESS_KEY_REF`, `AGENTGATE_AUDIT_INTEGRITY_S3_SESSION_TOKEN_REF` | Names of env refs used for non-IAM audit object-store credentials | Non-secret ref metadata | Add through `shared_additional_environment` or service-specific additional env maps | `api`, `worker`, `scheduler`, `migrate` if not using IAM | Usually no | If you use these ref variables, inject the actual referenced secret env vars through the secret maps. |
| `AGENTGATE_SCIM_TENANT_TOKEN_REFS` | Tenant-to-env-ref map for SCIM bearer tokens | Non-secret ref metadata | Add through `shared_additional_environment` or `api_additional_environment` | Usually `api`; optionally other app-like tasks if needed | Optional | The JSON map is non-secret, but the referenced `AGENTGATE_SCIM_TOKEN_*` values are secrets and belong in `shared_secret_arns` or `api_secret_arns`. |
| OIDC client metadata and issuer settings | OIDC URLs, issuer, audience, client ID, and similar safe config | Usually non-secret | Add through additional environment maps | Usually `api`; optionally `worker`, `scheduler`, `migrate` if needed by shared code paths | Optional | Keep OIDC client secrets or private keys in secret maps, not additional env maps. |
| `vpc_id`, `alb_subnet_ids`, `service_subnet_ids`, `alb_certificate_arn`, `assign_public_ip`, `alb_ingress_cidrs`, `rds_security_group_id`, `redis_security_group_id`, `ecs_task_additional_security_group_ids` | AWS deployment wiring and network posture | Non-secret deployment input | Terraform resource arguments | AWS resources rather than app runtime | Yes | Important deployment metadata, but not runtime secrets. |
| `api_desired_count`, `web_desired_count`, `worker_desired_count`, `scheduler_desired_count`, `enable_scheduler`, `*_cpu`, `*_memory`, `cloudwatch_log_retention_days`, `name_prefix`, `tags` | Capacity, optional scheduler enablement, naming, and retention | Non-secret deployment input | Terraform resource arguments | ECS services, task definitions, log groups | Yes except scheduler-specific inputs | These shape deployment behavior, not application logic. |

## Values That Must Never Be Committed

Never commit raw values for:

- `AGENTGATE_SECRET_KEY`
- real PostgreSQL URLs with usernames/passwords
- real Redis URLs with auth credentials
- GitHub tokens or GitHub App private keys
- Jira tokens, Jira API tokens, or Jira passwords
- MCP bearer tokens or API keys
- OIDC client secrets, private keys, or signing secrets
- SCIM bearer tokens such as `AGENTGATE_SCIM_TOKEN_*`
- Slack bot tokens
- env-provider payload encryption keys such as `AGENTGATE_PAYLOAD_ENCRYPTION_KEY`
- non-IAM audit object-store access keys, secret keys, or session tokens
- bootstrap or operator passwords used outside demos

Also do not commit generated Terraform state or cache files such as `.terraform/`, `terraform.tfstate`, or crash logs.

## Example: Generic Secret Maps For SCIM, Jira, MCP, And OIDC

Use placeholders only:

```hcl
shared_additional_environment = {
  AGENTGATE_SCIM_TENANT_TOKEN_REFS = jsonencode({
    pilot = "env:AGENTGATE_SCIM_TOKEN_PILOT"
  })
  AGENTGATE_OIDC_ISSUER_URL = "https://idp.example.com"
  AGENTGATE_OIDC_CLIENT_ID  = "agentgate-pilot"
}

shared_secret_arns = {
  AGENTGATE_SCIM_TOKEN_PILOT = "arn:aws:secretsmanager:us-east-1:111122223333:secret:agentgate/scim-token-pilot-xxxxx"
  AGENTGATE_JIRA_API_TOKEN   = "arn:aws:secretsmanager:us-east-1:111122223333:secret:agentgate/jira-api-token-xxxxx"
  AGENTGATE_MCP_TOKEN        = "arn:aws:secretsmanager:us-east-1:111122223333:secret:agentgate/mcp-token-xxxxx"
  AGENTGATE_OIDC_CLIENT_SECRET = "arn:aws:secretsmanager:us-east-1:111122223333:secret:agentgate/oidc-client-secret-xxxxx"
}
```

This keeps the tenant-to-env-ref map and OIDC metadata non-secret while the actual bearer tokens and client secrets remain secret-backed.
