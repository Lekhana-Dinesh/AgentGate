variable "aws_region" {
  description = "AWS region for ECS, ALB, CloudWatch Logs, and IAM resources."
  type        = string
}

variable "name_prefix" {
  description = "Prefix for ECS, ALB, IAM, and log resources."
  type        = string
  default     = "agentgate"
}

variable "tags" {
  description = "Additional tags to apply to created AWS resources."
  type        = map(string)
  default     = {}
}

variable "vpc_id" {
  description = "Existing VPC ID used by the ECS services and ALB."
  type        = string
}

variable "alb_subnet_ids" {
  description = "Existing public or ingress-capable subnet IDs for the ALB."
  type        = list(string)
}

variable "service_subnet_ids" {
  description = "Existing private subnet IDs for ECS tasks."
  type        = list(string)
}

variable "alb_ingress_cidrs" {
  description = "CIDR blocks allowed to reach the ALB."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "assign_public_ip" {
  description = "Whether ECS tasks should receive public IPs. Keep false for private-subnet deployments."
  type        = bool
  default     = false
}

variable "public_app_url" {
  description = "External browser URL for AgentGate."
  type        = string
}

variable "public_api_url" {
  description = "External API URL for AgentGate."
  type        = string
}

variable "public_app_host" {
  description = "Host header for the web application listener rule."
  type        = string
}

variable "public_api_host" {
  description = "Host header for the API listener rule."
  type        = string
}

variable "alb_certificate_arn" {
  description = "Optional ACM certificate ARN for HTTPS termination on the ALB."
  type        = string
  default     = null
  nullable    = true
}

variable "api_image_uri" {
  description = "Container image URI for the API, worker, scheduler, and migration task."
  type        = string
}

variable "web_image_uri" {
  description = "Container image URI for the web frontend."
  type        = string
}

variable "api_desired_count" {
  description = "Desired ECS task count for the API service."
  type        = number
  default     = 1
}

variable "web_desired_count" {
  description = "Desired ECS task count for the web service."
  type        = number
  default     = 1
}

variable "worker_desired_count" {
  description = "Desired ECS task count for the worker service."
  type        = number
  default     = 1
}

variable "scheduler_desired_count" {
  description = "Desired ECS task count for the scheduler service when enabled."
  type        = number
  default     = 1
}

variable "enable_scheduler" {
  description = "Whether to run the scheduler service."
  type        = bool
  default     = true
}

variable "api_cpu" {
  description = "CPU units for the API task definition."
  type        = number
  default     = 512
}

variable "api_memory" {
  description = "Memory (MiB) for the API task definition."
  type        = number
  default     = 1024
}

variable "web_cpu" {
  description = "CPU units for the web task definition."
  type        = number
  default     = 256
}

variable "web_memory" {
  description = "Memory (MiB) for the web task definition."
  type        = number
  default     = 512
}

variable "worker_cpu" {
  description = "CPU units for the worker task definition."
  type        = number
  default     = 512
}

variable "worker_memory" {
  description = "Memory (MiB) for the worker task definition."
  type        = number
  default     = 1024
}

variable "scheduler_cpu" {
  description = "CPU units for the scheduler task definition."
  type        = number
  default     = 256
}

variable "scheduler_memory" {
  description = "Memory (MiB) for the scheduler task definition."
  type        = number
  default     = 512
}

variable "migrate_cpu" {
  description = "CPU units for the one-off migration task definition."
  type        = number
  default     = 256
}

variable "migrate_memory" {
  description = "Memory (MiB) for the one-off migration task definition."
  type        = number
  default     = 512
}

variable "secret_key_secret_arn" {
  description = "Secrets Manager or SSM ARN for AGENTGATE_SECRET_KEY."
  type        = string
}

variable "database_url_secret_arn" {
  description = "Secrets Manager or SSM ARN for AGENTGATE_DATABASE_URL."
  type        = string
}

variable "redis_url_secret_arn" {
  description = "Secrets Manager or SSM ARN for AGENTGATE_REDIS_URL."
  type        = string
}

variable "github_token_secret_arn" {
  description = "Optional Secrets Manager or SSM ARN for AGENTGATE_GITHUB_TOKEN."
  type        = string
  default     = null
  nullable    = true
}

variable "github_app_private_key_secret_arn" {
  description = "Optional Secrets Manager or SSM ARN for AGENTGATE_GITHUB_APP_PRIVATE_KEY."
  type        = string
  default     = null
  nullable    = true
}

variable "slack_bot_token_secret_arn" {
  description = "Optional Secrets Manager or SSM ARN for AGENTGATE_SLACK_BOT_TOKEN."
  type        = string
  default     = null
  nullable    = true
}

variable "shared_secret_arns" {
  description = "Additional shared secret env var name -> secret ARN mappings for API-like tasks."
  type        = map(string)
  default     = {}
}

variable "api_secret_arns" {
  description = "Additional API-only secret env var name -> secret ARN mappings."
  type        = map(string)
  default     = {}
}

variable "worker_secret_arns" {
  description = "Additional worker-only secret env var name -> secret ARN mappings."
  type        = map(string)
  default     = {}
}

variable "scheduler_secret_arns" {
  description = "Additional scheduler-only secret env var name -> secret ARN mappings."
  type        = map(string)
  default     = {}
}

variable "web_secret_arns" {
  description = "Optional web-only secret env var name -> secret ARN mappings."
  type        = map(string)
  default     = {}
}

variable "agentgate_env" {
  description = "Value for AGENTGATE_ENV."
  type        = string
  default     = "production"
}

variable "agentgate_debug" {
  description = "Value for AGENTGATE_DEBUG."
  type        = bool
  default     = false
}

variable "default_tenant_plan" {
  description = "Value for AGENTGATE_DEFAULT_TENANT_PLAN."
  type        = string
  default     = "enterprise"
}

variable "cors_origins" {
  description = "Browser origins allowed by AGENTGATE_CORS_ORIGINS."
  type        = list(string)
}

variable "allow_insecure_public_urls" {
  description = "Value for AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS."
  type        = bool
  default     = false
}

variable "allow_private_audit_export_destinations" {
  description = "Value for AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS."
  type        = bool
  default     = false
}

variable "allow_demo_credentials" {
  description = "Value for AGENTGATE_ALLOW_DEMO_CREDENTIALS."
  type        = bool
  default     = false
}

variable "key_provider" {
  description = "Value for AGENTGATE_KEY_PROVIDER."
  type        = string
  default     = "aws_kms"
}

variable "payload_kms_key_arn" {
  description = "KMS key ARN used for payload protection and exposed to AGENTGATE_AWS_KMS_KEY_ID."
  type        = string
}

variable "payload_encryption_active_key_ref" {
  description = "Value for AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF."
  type        = string
  default     = "aws-kms-primary"
}

variable "payload_encryption_key_version" {
  description = "Value for AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION."
  type        = number
  default     = 1
}

variable "payload_encryption_additional_keys" {
  description = "Additional decrypt-only key mappings serialized to AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS."
  type        = map(string)
  default     = {}
}

variable "payload_encryption_additional_key_versions" {
  description = "Additional decrypt-only key version mappings serialized to AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEY_VERSIONS."
  type        = map(string)
  default     = {}
}

variable "audit_integrity_anchor_type" {
  description = "Value for AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE."
  type        = string
  default     = "object_storage"
}

variable "audit_integrity_local_path" {
  description = "Value for AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH."
  type        = string
  default     = ".tmp/audit-integrity-checkpoints"
}

variable "audit_integrity_s3_bucket" {
  description = "Checkpoint bucket name when using object_storage audit anchoring."
  type        = string
  default     = ""
}

variable "audit_integrity_s3_prefix" {
  description = "Checkpoint prefix when using object_storage audit anchoring."
  type        = string
  default     = "agentgate/audit-integrity"
}

variable "audit_integrity_s3_region" {
  description = "Checkpoint bucket region when using object_storage audit anchoring."
  type        = string
  default     = ""
}

variable "audit_integrity_s3_endpoint_url" {
  description = "Optional endpoint URL for S3-compatible audit anchoring."
  type        = string
  default     = ""
}

variable "slack_notifications_enabled" {
  description = "Value for AGENTGATE_SLACK_NOTIFICATIONS_ENABLED."
  type        = bool
  default     = false
}

variable "slack_bot_token_env_var" {
  description = "Value for AGENTGATE_SLACK_BOT_TOKEN_ENV_VAR."
  type        = string
  default     = "AGENTGATE_SLACK_BOT_TOKEN"
}

variable "slack_default_channel" {
  description = "Value for AGENTGATE_SLACK_DEFAULT_CHANNEL."
  type        = string
  default     = ""
}

variable "job_dispatch_mode" {
  description = "Value for AGENTGATE_JOB_DISPATCH_MODE."
  type        = string
  default     = "worker"
}

variable "job_broker" {
  description = "Value for AGENTGATE_JOB_BROKER."
  type        = string
  default     = "redis"
}

variable "rate_limit_enabled" {
  description = "Value for AGENTGATE_RATE_LIMIT_ENABLED."
  type        = bool
  default     = true
}

variable "rate_limit_provider" {
  description = "Value for AGENTGATE_RATE_LIMIT_PROVIDER."
  type        = string
  default     = "redis"
}

variable "cloudwatch_log_retention_days" {
  description = "Retention period for CloudWatch log groups."
  type        = number
  default     = 30
}

variable "rds_security_group_id" {
  description = "Optional existing RDS security group ID for a starter ingress rule from ECS tasks."
  type        = string
  default     = null
  nullable    = true
}

variable "redis_security_group_id" {
  description = "Optional existing Redis security group ID for a starter ingress rule from ECS tasks."
  type        = string
  default     = null
  nullable    = true
}

variable "ecs_task_additional_security_group_ids" {
  description = "Additional existing security group IDs to attach to ECS tasks."
  type        = list(string)
  default     = []
}

variable "shared_additional_environment" {
  description = "Additional shared non-secret environment variables for API-like tasks."
  type        = map(string)
  default     = {}
}

variable "api_additional_environment" {
  description = "Additional non-secret environment variables for the API task."
  type        = map(string)
  default     = {}
}

variable "worker_additional_environment" {
  description = "Additional non-secret environment variables for the worker task."
  type        = map(string)
  default     = {}
}

variable "scheduler_additional_environment" {
  description = "Additional non-secret environment variables for the scheduler task."
  type        = map(string)
  default     = {}
}

variable "web_additional_environment" {
  description = "Additional non-secret environment variables for the web task."
  type        = map(string)
  default     = {}
}
