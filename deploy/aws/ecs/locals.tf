locals {
  tags = merge(
    {
      Application = "agentgate"
      ManagedBy   = "terraform"
      Stack       = "ecs-fargate"
    },
    var.tags,
  )

  base_agentgate_env = merge(
    {
      AGENTGATE_ENV                                                  = var.agentgate_env
      AGENTGATE_DEBUG                                                = tostring(var.agentgate_debug)
      AGENTGATE_ACCESS_TOKEN_EXPIRE_MINUTES                          = "60"
      AGENTGATE_DEFAULT_TENANT_PLAN                                  = var.default_tenant_plan
      AGENTGATE_AUTO_CREATE_SCHEMA                                   = "false"
      AGENTGATE_CORS_ORIGINS                                         = jsonencode(var.cors_origins)
      AGENTGATE_PUBLIC_APP_URL                                       = var.public_app_url
      AGENTGATE_PUBLIC_API_URL                                       = var.public_api_url
      AGENTGATE_ALLOW_INSECURE_PUBLIC_URLS                           = tostring(var.allow_insecure_public_urls)
      AGENTGATE_ALLOW_PRIVATE_AUDIT_EXPORT_DESTINATIONS              = tostring(var.allow_private_audit_export_destinations)
      AGENTGATE_ALLOW_DEMO_CREDENTIALS                               = tostring(var.allow_demo_credentials)
      AGENTGATE_KEY_PROVIDER                                         = var.key_provider
      AGENTGATE_AWS_REGION                                           = var.aws_region
      AGENTGATE_AWS_KMS_KEY_ID                                       = var.payload_kms_key_arn
      AGENTGATE_AWS_KMS_ENDPOINT_URL                                 = ""
      AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF                    = var.payload_encryption_active_key_ref
      AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION                       = tostring(var.payload_encryption_key_version)
      AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS                   = jsonencode(var.payload_encryption_additional_keys)
      AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEY_VERSIONS           = jsonencode(var.payload_encryption_additional_key_versions)
      AGENTGATE_SLACK_NOTIFICATIONS_ENABLED                          = tostring(var.slack_notifications_enabled)
      AGENTGATE_SLACK_BOT_TOKEN_ENV_VAR                              = var.slack_bot_token_env_var
      AGENTGATE_SLACK_DEFAULT_CHANNEL                                = var.slack_default_channel
      AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE                          = var.audit_integrity_anchor_type
      AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH                           = var.audit_integrity_local_path
      AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET                            = var.audit_integrity_s3_bucket
      AGENTGATE_AUDIT_INTEGRITY_S3_PREFIX                            = var.audit_integrity_s3_prefix
      AGENTGATE_AUDIT_INTEGRITY_S3_REGION                            = var.audit_integrity_s3_region
      AGENTGATE_AUDIT_INTEGRITY_S3_ENDPOINT_URL                      = var.audit_integrity_s3_endpoint_url
      AGENTGATE_AUDIT_INTEGRITY_S3_ACCESS_KEY_ID_REF                 = ""
      AGENTGATE_AUDIT_INTEGRITY_S3_SECRET_ACCESS_KEY_REF             = ""
      AGENTGATE_AUDIT_INTEGRITY_S3_SESSION_TOKEN_REF                 = ""
      AGENTGATE_OIDC_HTTP_TIMEOUT_SECONDS                            = "5"
      AGENTGATE_OIDC_STATE_TTL_SECONDS                               = "600"
      AGENTGATE_OIDC_EXCHANGE_TTL_SECONDS                            = "180"
      AGENTGATE_JOB_DISPATCH_MODE                                    = var.job_dispatch_mode
      AGENTGATE_JOB_BROKER                                           = var.job_broker
      AGENTGATE_JOB_REDIS_QUEUE_NAME                                 = "agentgate:jobs"
      AGENTGATE_JOB_POLL_INTERVAL_SECONDS                            = "2"
      AGENTGATE_JOB_WORKER_BATCH_SIZE                                = "10"
      AGENTGATE_JOB_STALE_RECOVERY_BATCH_SIZE                        = "25"
      AGENTGATE_JOB_LEASE_SECONDS                                    = "300"
      AGENTGATE_SCHEDULER_POLL_INTERVAL_SECONDS                      = "5"
      AGENTGATE_SCHEDULER_BATCH_SIZE                                 = "25"
      AGENTGATE_WORKER_HEARTBEAT_INTERVAL_SECONDS                    = "5"
      AGENTGATE_WORKER_STALE_AFTER_SECONDS                           = "30"
      AGENTGATE_JOB_SLACK_MAX_ATTEMPTS                               = "3"
      AGENTGATE_JOB_SLACK_RETRY_BACKOFF_SECONDS                      = "30"
      AGENTGATE_AUDIT_EXPORT_TIMEOUT_SECONDS                         = "5"
      AGENTGATE_JOB_AUDIT_EXPORT_MAX_ATTEMPTS                        = "3"
      AGENTGATE_JOB_AUDIT_EXPORT_RETRY_BACKOFF_SECONDS               = "30"
      AGENTGATE_JOB_AUDIT_INTEGRITY_CHECKPOINT_MAX_ATTEMPTS          = "3"
      AGENTGATE_JOB_AUDIT_INTEGRITY_CHECKPOINT_RETRY_BACKOFF_SECONDS = "30"
      AGENTGATE_JOB_RETENTION_MAX_ATTEMPTS                           = "2"
      AGENTGATE_JOB_RETENTION_RETRY_BACKOFF_SECONDS                  = "60"
      AGENTGATE_PAYLOAD_RETENTION_STANDARD_DAYS                      = "30"
      AGENTGATE_PAYLOAD_RETENTION_SHORT_LIVED_DAYS                   = "7"
      AGENTGATE_PAYLOAD_RETENTION_EXTENDED_DAYS                      = "90"
      AGENTGATE_RATE_LIMIT_ENABLED                                   = tostring(var.rate_limit_enabled)
      AGENTGATE_RATE_LIMIT_PROVIDER                                  = var.rate_limit_provider
      AGENTGATE_ALLOW_IN_MEMORY_RATE_LIMIT_IN_PRODUCTION             = "false"
      AGENTGATE_RATE_LIMIT_FAIL_OPEN_ON_BACKEND_ERROR                = "false"
      AGENTGATE_RATE_LIMIT_LOGIN_LIMIT                               = "5"
      AGENTGATE_RATE_LIMIT_LOGIN_WINDOW_SECONDS                      = "60"
      AGENTGATE_RATE_LIMIT_OIDC_LIMIT                                = "10"
      AGENTGATE_RATE_LIMIT_OIDC_WINDOW_SECONDS                       = "60"
      AGENTGATE_RATE_LIMIT_GATEWAY_LIMIT                             = "30"
      AGENTGATE_RATE_LIMIT_GATEWAY_WINDOW_SECONDS                    = "60"
      AGENTGATE_RATE_LIMIT_APPROVAL_LIMIT                            = "20"
      AGENTGATE_RATE_LIMIT_APPROVAL_WINDOW_SECONDS                   = "60"
      AGENTGATE_RATE_LIMIT_AUDIT_EXPORT_LIMIT                        = "6"
      AGENTGATE_RATE_LIMIT_AUDIT_EXPORT_WINDOW_SECONDS               = "300"
      AGENTGATE_RATE_LIMIT_RETENTION_LIMIT                           = "4"
      AGENTGATE_RATE_LIMIT_RETENTION_WINDOW_SECONDS                  = "300"
      AGENTGATE_RATE_LIMIT_JOBS_RETRY_LIMIT                          = "6"
      AGENTGATE_RATE_LIMIT_JOBS_RETRY_WINDOW_SECONDS                 = "300"
      AGENTGATE_RATE_LIMIT_AUDIT_INTEGRITY_LIMIT                     = "4"
      AGENTGATE_RATE_LIMIT_AUDIT_INTEGRITY_WINDOW_SECONDS            = "300"
    },
    var.shared_additional_environment,
  )

  api_env_map = merge(local.base_agentgate_env, var.api_additional_environment)

  worker_env_map = merge(
    local.base_agentgate_env,
    {
      AGENTGATE_WORKER_ID = "worker-1"
    },
    var.worker_additional_environment,
  )

  scheduler_env_map = merge(local.base_agentgate_env, var.scheduler_additional_environment)

  web_env_map = merge(
    {
      NEXT_PUBLIC_API_BASE_URL = var.public_api_url
    },
    var.web_additional_environment,
  )

  shared_secret_map = merge(
    {
      AGENTGATE_SECRET_KEY   = var.secret_key_secret_arn
      AGENTGATE_DATABASE_URL = var.database_url_secret_arn
      AGENTGATE_REDIS_URL    = var.redis_url_secret_arn
    },
    var.github_token_secret_arn == null ? {} : {
      AGENTGATE_GITHUB_TOKEN = var.github_token_secret_arn
    },
    var.github_app_private_key_secret_arn == null ? {} : {
      AGENTGATE_GITHUB_APP_PRIVATE_KEY = var.github_app_private_key_secret_arn
    },
    var.slack_bot_token_secret_arn == null ? {} : {
      AGENTGATE_SLACK_BOT_TOKEN = var.slack_bot_token_secret_arn
    },
    var.shared_secret_arns,
  )

  api_secret_map       = merge(local.shared_secret_map, var.api_secret_arns)
  worker_secret_map    = merge(local.shared_secret_map, var.worker_secret_arns)
  scheduler_secret_map = merge(local.shared_secret_map, var.scheduler_secret_arns)
  web_secret_map       = var.web_secret_arns

  all_secret_arns = toset(
    [
      for arn in concat(
        values(local.shared_secret_map),
        values(var.api_secret_arns),
        values(var.worker_secret_arns),
        values(var.scheduler_secret_arns),
        values(var.web_secret_arns),
      ) : arn
      if arn != null && trimspace(arn) != ""
    ]
  )

  checkpoint_bucket_resources = var.audit_integrity_s3_bucket == "" ? [] : [
    "arn:aws:s3:::${var.audit_integrity_s3_bucket}",
    "arn:aws:s3:::${var.audit_integrity_s3_bucket}/*",
  ]
}
