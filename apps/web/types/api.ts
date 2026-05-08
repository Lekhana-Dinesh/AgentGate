export type UserRole =
  | "owner"
  | "admin"
  | "security_reviewer"
  | "developer"
  | "approver"
  | "viewer";
export type UserStatus = "active" | "deactivated";
export type UserProvisionedSource = "local" | "oidc" | "scim" | "system";

export type AgentEnvironment = "development" | "staging" | "production";
export type AgentStatus = "active" | "suspended" | "revoked";
export type RiskBand = "low" | "medium" | "high" | "critical";
export type ToolType = "mcp" | "rest" | "mock" | "database" | "email" | "crm" | "custom" | "github" | "jira";
export type PolicyDecision = "allow" | "block" | "require_approval" | "redact";
export type PolicySeverity = "low" | "medium" | "high" | "critical";
export type ToolCallStatus = "allowed" | "blocked" | "pending_approval" | "executed" | "failed";
export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export type TraceStatus = "running" | "completed" | "failed" | "blocked" | "pending_approval";
export type TraceStepType = "thought" | "tool_call" | "policy_decision" | "approval" | "final" | "error";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "retry_exhausted" | "cancelled";
export type JobType =
  | "approval_notification.slack"
  | "approval_execution.tool_call"
  | "audit_export.placeholder"
  | "audit_integrity_checkpoint.placeholder"
  | "retention_purge.placeholder"
  | "audit_integrity_verify.placeholder"
  | "connector_health_check.placeholder";
export type PayloadRetentionClass = "standard" | "short_lived" | "extended" | "legal_hold";
export type AuditExportDestinationType =
  | "webhook"
  | "splunk_hec"
  | "datadog"
  | "http_json"
  | "custom_placeholder";
export type AuditEventSeverity = "info" | "warning" | "error" | "critical";
export type ScheduledTaskType =
  | "retention_purge"
  | "audit_export"
  | "audit_integrity_verify"
  | "audit_integrity_checkpoint"
  | "connector_health_check";
export type ScheduledTaskScheduleKind = "interval" | "cron";

export interface CurrentUser {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  status: UserStatus;
  provisioned_source: UserProvisionedSource;
  deactivated_at: string | null;
  deactivation_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface UserRecord {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  status: UserStatus;
  provisioned_source: UserProvisionedSource;
  deactivated_at: string | null;
  deactivation_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface DashboardOverview {
  total_agents: number;
  active_agents: number;
  pending_approvals: number;
  blocked_actions: number;
  high_risk_tool_calls: number;
  recent_audit_events: AuditEvent[];
}

export interface OnboardingChecklistItem {
  key:
    | "active_owner"
    | "agent"
    | "tool"
    | "policy"
    | "approval_workflow"
    | "audit_integrity"
    | "settings";
  label: string;
  description: string;
  complete: boolean;
  href: string;
}

export interface OnboardingLink {
  label: string;
  href: string;
  description: string;
}

export interface OnboardingStatus {
  tenant_id: string;
  tenant_exists: boolean;
  active_owner_exists: boolean;
  agent_count: number;
  tool_count: number;
  policy_count: number;
  has_agent: boolean;
  has_tool: boolean;
  has_policy: boolean;
  approval_workflow_available: boolean;
  audit_integrity_configured: boolean;
  audit_integrity_status: "empty" | "legacy_only" | "anchored" | "anchored_with_legacy";
  settings_overview_available: boolean;
  dismissed: boolean;
  recommended_next_step: string;
  recommended_next_step_href: string;
  checklist: OnboardingChecklistItem[];
  links: OnboardingLink[];
}

export interface OnboardingActionResponse {
  ok: boolean;
  action: "dismiss" | "reset" | "create_demo_policy";
  message: string;
  dismissed: boolean | null;
  created: boolean | null;
  policy_id: string | null;
}

export interface Agent {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  owner_user_id: string | null;
  environment: AgentEnvironment;
  status: AgentStatus;
  purpose: string;
  allowed_tools: string[];
  allowed_data_classes: string[];
  risk_level: RiskBand;
  created_at: string;
  updated_at: string;
}

export interface AgentAPIKeySummary {
  id: string;
  name: string;
  prefix: string;
  created_at: string;
  created_by_user_id: string | null;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  is_active: boolean;
}

export interface AgentAPIKeyResponse extends AgentAPIKeySummary {
  api_key: string;
}

export interface ToolSafeSummary {
  id: string;
  name: string;
  type: ToolType;
  description: string;
  enabled: boolean;
  risk_level: RiskBand;
  base_url_host: string | null;
  auth_mode: string | null;
  trust_domain: string | null;
  allowlist_counts: Record<string, number>;
  supported_actions: string[];
  health_status: "ready" | "degraded" | "unconfigured" | "unsupported";
  health_can_connect: boolean | null;
  health_probe_performed: boolean;
  health_checked_at: string | null;
  warning_flags: string[];
  created_at: string;
  updated_at: string;
}

export interface ToolSafeDetail extends ToolSafeSummary {
  base_url: string | null;
  documentation_path: string | null;
  supported_auth_modes: string[];
  repository_allowlist: string[];
  internal_repositories: string[];
  internal_owners: string[];
  public_repositories: string[];
  app_id: string | null;
  installation_id: string | null;
  project_allowlist: string[];
  issue_type_allowlist: string[];
  external_project_keys: string[];
  transition_allowlist: string[];
  assignee_allowlist: string[];
  transport: string | null;
  allowed_tool_names: string[];
  blocked_tool_names: string[];
}

export interface ToolSafeMetadataCreateInput {
  name: string;
  type: Extract<ToolType, "github" | "jira" | "mcp" | "mock">;
  description: string;
  base_url?: string | null;
  risk_level: RiskBand;
  enabled: boolean;
  auth_mode?: string | null;
  trust_domain?: "internal" | "external" | "unknown" | null;
  repository_allowlist?: string[];
  internal_repositories?: string[];
  internal_owners?: string[];
  public_repositories?: string[];
  app_id?: string | null;
  installation_id?: string | null;
  project_allowlist?: string[];
  issue_type_allowlist?: string[];
  external_project_keys?: string[];
  transition_allowlist?: string[];
  assignee_allowlist?: string[];
  transport?: "http" | null;
  allowed_tool_names?: string[];
  blocked_tool_names?: string[];
}

export interface ToolSafeMetadataUpdateInput {
  name?: string;
  description?: string;
  base_url?: string | null;
  risk_level?: RiskBand;
  enabled?: boolean;
  auth_mode?: string | null;
  trust_domain?: "internal" | "external" | "unknown" | null;
  repository_allowlist?: string[];
  internal_repositories?: string[];
  internal_owners?: string[];
  public_repositories?: string[];
  app_id?: string | null;
  installation_id?: string | null;
  project_allowlist?: string[];
  issue_type_allowlist?: string[];
  external_project_keys?: string[];
  transition_allowlist?: string[];
  assignee_allowlist?: string[];
  transport?: "http" | null;
  allowed_tool_names?: string[];
  blocked_tool_names?: string[];
}

export interface ToolCall {
  id: string;
  tenant_id: string;
  agent_id: string;
  user_id: string | null;
  trace_id: string | null;
  tool_name: string;
  action_name: string;
  request_payload: Record<string, unknown>;
  response_payload: Record<string, unknown> | null;
  payload_protection_version?: string | null;
  payload_retention_class?: string;
  payload_expires_at?: string | null;
  payload_redaction_status?: string;
  status: ToolCallStatus;
  risk_score: number;
  decision_reason: string;
  created_at: string;
}

export interface ApprovalRequest {
  id: string;
  tenant_id: string;
  tool_call_id: string;
  requested_by_agent_id: string;
  assigned_to_user_id: string | null;
  status: ApprovalStatus;
  reason: string;
  approver_comment: string | null;
  created_at: string;
  decided_at: string | null;
  tool_call?: ToolCall | null;
  notification_status?: ApprovalNotificationStatus | null;
  execution_status?: ApprovalExecutionStatus | null;
}

export interface JobSummary {
  id: string;
  job_type: JobType;
  status: JobStatus;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface JobRecord extends JobSummary {
  tenant_id: string;
  idempotency_key: string;
  next_run_at: string;
  payload: Record<string, unknown>;
}

export interface ApprovalExecutionStatus {
  status: "not_requested" | JobStatus;
  job?: JobSummary | null;
  message?: string | null;
}

export interface AuditExportRunResult {
  dry_run: boolean;
  batches_processed: number;
  exported_events: number;
  last_exported_at: string | null;
  last_exported_event_id: string | null;
  destination_type: AuditExportDestinationType;
}

export interface AuditExportConfig {
  id: string;
  tenant_id: string;
  name: string;
  destination_type: AuditExportDestinationType;
  enabled: boolean;
  endpoint_url: string;
  event_type_filters: string[];
  severity_filters: AuditEventSeverity[];
  max_batch_size: number;
  credential_source: "none" | "token_env_var" | "secret_ref";
  credential_status: "not_required" | "configured" | "missing" | "unsupported" | "invalid";
  last_exported_at: string | null;
  last_exported_event_id: string | null;
  last_export_status: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  last_job: JobSummary | null;
}

export interface AuditExportStatus extends AuditExportConfig {
  pending_events: number;
  last_result: AuditExportRunResult | null;
}

export interface AuditExportRunResponse {
  dry_run: boolean;
  dispatch_mode: "inline" | "worker";
  job: JobRecord;
  result: AuditExportRunResult | null;
}

export interface AuditIntegrityIssue {
  code: string;
  detail: string;
  event_id?: string | null;
  sequence_number?: number | null;
}

export interface AuditIntegrityStatus {
  tenant_id: string;
  chain_scope: string;
  hash_algorithm: string;
  status: "empty" | "legacy_only" | "anchored" | "anchored_with_legacy";
  total_events: number;
  anchored_events: number;
  legacy_unanchored_events: number;
  latest_sequence_number?: number | null;
  latest_event_id?: string | null;
  latest_event_hash?: string | null;
  latest_anchored_at?: string | null;
}

export interface AuditIntegrityVerifyResponse {
  tenant_id: string;
  chain_scope: string;
  hash_algorithm: string;
  status: "empty" | "legacy_only" | "verified" | "verified_with_legacy" | "broken";
  chain_valid: boolean;
  boundary_limited: boolean;
  total_events: number;
  anchored_events: number;
  legacy_unanchored_events: number;
  verified_events: number;
  first_verified_event_id?: string | null;
  last_verified_event_id?: string | null;
  latest_sequence_number?: number | null;
  latest_event_id?: string | null;
  latest_event_hash?: string | null;
  latest_anchored_at?: string | null;
  issues: AuditIntegrityIssue[];
}

export type AuditIntegrityCheckpointStatus = "pending" | "anchored" | "failed";
export type AuditIntegrityCheckpointType = "local" | "object_storage" | "custom_placeholder";

export interface AuditIntegrityCheckpointRecord {
  id: string;
  tenant_id: string;
  checkpoint_type: AuditIntegrityCheckpointType;
  chain_scope: string;
  from_sequence_number: number;
  to_sequence_number: number;
  from_event_id: string;
  to_event_id: string;
  checkpoint_hash: string | null;
  previous_checkpoint_hash: string | null;
  event_count: number;
  destination_ref: string | null;
  status: AuditIntegrityCheckpointStatus;
  created_at: string;
  anchored_at: string | null;
  metadata: Record<string, unknown>;
}

export interface AuditIntegrityCheckpointJobResult {
  created: boolean;
  status: "anchored" | "failed" | "no_new_events";
  checkpoint_id: string | null;
  checkpoint_status: AuditIntegrityCheckpointStatus | null;
  event_count: number;
  from_sequence_number: number | null;
  to_sequence_number: number | null;
  checkpoint_hash: string | null;
}

export interface AuditIntegrityCheckpointRunResponse {
  dispatch_mode: "inline" | "worker";
  job: JobRecord;
  result: AuditIntegrityCheckpointJobResult | null;
}

export interface AuditIntegrityCheckpointVerifyResponse {
  checkpoint_id: string;
  tenant_id: string;
  status: "verified" | "broken";
  chain_valid: boolean;
  checkpoint_hash_valid: boolean;
  external_anchor_valid: boolean | null;
  stored_checkpoint_hash: string | null;
  recomputed_checkpoint_hash: string | null;
  verified_at: string;
  issues: AuditIntegrityIssue[];
}

export interface RetentionStatus {
  eligible: number;
  purged: number;
  legal_hold: number;
  failed: number;
  protected_active: number;
}

export interface RetentionPurgeResult {
  dry_run: boolean;
  requested: number;
  eligible: number;
  purged: number;
  skipped_non_expired: number;
  skipped_legal_hold: number;
  already_purged: number;
  failed: number;
  tool_call_ids: string[];
  failed_tool_call_ids: string[];
}

export interface RetentionPurgeResponse {
  dry_run: boolean;
  dispatch_mode: "inline" | "worker";
  job: JobRecord;
  result: RetentionPurgeResult | null;
}

export interface ScheduledTask {
  id: string;
  tenant_id: string;
  name: string;
  task_type: ScheduledTaskType;
  enabled: boolean;
  schedule_kind: ScheduledTaskScheduleKind;
  interval_seconds: number | null;
  cron_expression: string | null;
  next_run_at: string;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  idempotency_key: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ScheduledTaskRunResponse {
  dispatch_mode: "inline" | "worker";
  job: JobRecord;
  scheduled_task: ScheduledTask;
}

export interface SlackIntegrationHealthResponse {
  provider: "slack";
  enabled: boolean;
  configured: boolean;
  status: "disabled" | "ready" | "degraded" | "unconfigured";
  token_env_var: string;
  default_channel: string | null;
  probe_performed: boolean;
  can_connect: boolean | null;
  details: Record<string, unknown>;
}

export interface TenantProfileStatus {
  id: string;
  name: string;
  slug: string;
  plan: string;
  user_count: number;
  active_user_count: number;
  agent_count: number;
  tool_count: number;
  github_connector_count: number;
  audit_export_config_count: number;
  scheduled_task_count: number;
  created_at: string;
  updated_at: string;
}

export interface TenantOIDCSettingsStatus {
  status: "not_configured" | "disabled" | "ready" | "misconfigured";
  total_configs: number;
  enabled_configs: number;
  local_auth_enabled: boolean;
  provider_name: string | null;
  login_url: string | null;
  reason: string | null;
}

export interface GitHubConnectorStatus {
  id: string;
  name: string;
  enabled: boolean;
  status: "ready" | "degraded" | "unconfigured" | "unsupported";
  auth_provider: string | null;
  token_present: boolean | null;
  can_connect: boolean | null;
  repository_allowlist_count: number;
  warnings: string[];
  updated_at: string;
}

export interface GitHubConnectorOverview {
  status: "not_configured" | "disabled" | "ready" | "degraded";
  total: number;
  enabled: number;
  ready: number;
  degraded: number;
  unconfigured: number;
  unsupported: number;
  connectors: GitHubConnectorStatus[];
}

export interface AuditExportSettingsSummary {
  id: string;
  name: string;
  destination_type: AuditExportDestinationType;
  enabled: boolean;
  endpoint_host: string | null;
  credential_source: "none" | "token_env_var" | "secret_ref";
  credential_status: "not_required" | "configured" | "missing" | "unsupported" | "invalid";
  last_export_status: string | null;
  last_error: string | null;
  updated_at: string;
}

export interface AuditExportOverview {
  status: "not_configured" | "disabled" | "ready" | "degraded";
  total: number;
  enabled: number;
  credential_issue_count: number;
  failing_count: number;
  configs: AuditExportSettingsSummary[];
}

export interface RetentionPolicyStatus {
  standard_days: number;
  short_lived_days: number;
  extended_days: number;
  legal_hold_auto_purge: boolean;
}

export interface RetentionSettingsOverview {
  status: "ready" | "degraded";
  policy: RetentionPolicyStatus;
  summary: RetentionStatus;
}

export interface ScheduledTaskSettingsSummary {
  id: string;
  name: string;
  task_type: ScheduledTaskType;
  enabled: boolean;
  next_run_at: string;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  updated_at: string;
}

export interface ScheduledTaskOverview {
  status: "not_configured" | "disabled" | "ready" | "degraded";
  total: number;
  enabled: number;
  due: number;
  last_status_counts: Record<string, number>;
  task_type_counts: Record<string, number>;
  tasks: ScheduledTaskSettingsSummary[];
}

export interface RateLimiterScopeStatus {
  scope: string;
  enabled: boolean;
  limit: number;
  window_seconds: number;
  fail_closed_on_backend_error: boolean;
}

export interface RateLimiterStatus {
  status: "disabled" | "ok" | "warning" | "unavailable";
  provider: string;
  enabled: boolean;
  backend_status: string | null;
  warning: string | null;
  scopes: RateLimiterScopeStatus[];
}

export interface SettingsLinks {
  readiness_url: string;
  metrics_url: string;
}

export interface SettingsOverview {
  tenant: TenantProfileStatus;
  oidc: TenantOIDCSettingsStatus;
  github_connectors: GitHubConnectorOverview;
  slack: SlackIntegrationHealthResponse;
  audit_exports: AuditExportOverview;
  retention: RetentionSettingsOverview;
  scheduled_tasks: ScheduledTaskOverview;
  keys: KeyStatus;
  rate_limiter: RateLimiterStatus;
  links: SettingsLinks;
}

export interface ApprovalNotificationStatus {
  provider: "slack";
  status:
    | "disabled"
    | "not_attempted"
    | "queued"
    | "running"
    | "sent"
    | "failed"
    | "retry_exhausted"
    | "cancelled"
    | "unconfigured";
  job_id?: string | null;
  job?: JobSummary | null;
  attempts?: number | null;
  max_attempts?: number | null;
  event_type?: string | null;
  message?: string | null;
  error_code?: string | null;
  request_id?: string | null;
  channel?: string | null;
  created_at?: string | null;
}

export interface PolicyCondition {
  field:
    | "tool_name"
    | "action_name"
    | "recipient_domain"
    | "repo_trust"
    | "data_classification"
    | "risk_score"
    | "environment"
    | "amount"
    | "discount_percent"
    | "row_count"
    | "intent_mismatch";
  operator: "equals" | "contains" | "greater_than";
  value: string | number | boolean;
}

export interface PolicyConditionSet {
  match: "all" | "any";
  rules: PolicyCondition[];
}

export interface Policy {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  enabled: boolean;
  severity: PolicySeverity;
  conditions: PolicyConditionSet;
  decision: PolicyDecision;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface AuditEvent {
  id: string;
  tenant_id: string;
  actor_type: "user" | "agent" | "system";
  actor_id: string | null;
  event_type: string;
  resource_type: string;
  resource_id: string | null;
  metadata_json: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface TraceStep {
  id: string;
  trace_id: string;
  step_number: number;
  type: TraceStepType;
  content: string;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface Trace {
  id: string;
  tenant_id: string;
  agent_id: string;
  user_id: string | null;
  original_intent: string;
  status: TraceStatus;
  started_at: string;
  completed_at: string | null;
  summary: string;
  metadata_json: Record<string, unknown>;
  steps: TraceStep[];
}

export interface GatewayDecision {
  tool_call_id: string;
  trace_id: string;
  decision: PolicyDecision;
  status: ToolCallStatus;
  intent: {
    intent_match: boolean;
    confidence: number;
    explanation: string;
    detected_mismatch_reasons: string[];
  };
  risk: {
    score: number;
    band: RiskBand;
    reasons: string[];
    summary: string;
    factors: Array<{
      key: string;
      label: string;
      category:
        | "baseline"
        | "action"
        | "environment"
        | "recipient"
        | "data"
        | "amount"
        | "policy"
        | "intent";
      weight: number;
      explanation: string;
    }>;
  };
  policies: {
    decision: PolicyDecision;
    matched_policies: Array<{
      policy_id: string;
      name: string;
      severity: string;
      decision: string;
    }>;
    reasons: string[];
  };
  executed: boolean;
  output?: Record<string, unknown> | null;
}

export interface LoginPayload {
  email: string;
  password: string;
  tenant_slug?: string;
}

export interface TokenResponse {
  access_token: string | null;
  token_type: "bearer";
  session_mode: "token" | "cookie";
  csrf_token: string | null;
}

export interface CSRFTokenResponse {
  csrf_token: string | null;
  header_name: "X-CSRF-Token";
  session_mode: "token" | "cookie";
}

export interface LogoutResponse {
  logged_out: boolean;
}

export interface OIDCConfigStatus {
  configured: boolean;
  enabled: boolean;
  local_auth_enabled: boolean;
  provider_name?: string | null;
  login_url?: string | null;
  reason?: string | null;
}

export interface KeyPurposeStatus {
  purpose: string;
  provider: string;
  active_key_ref: string | null;
  active_key_version: string | null;
  configured_key_refs: string[];
  status: "ready" | "degraded" | "unconfigured" | "unavailable";
  region: string | null;
  warnings: string[];
}

export interface KeyStatus {
  provider: string;
  readiness: "ready" | "degraded" | "unconfigured" | "unavailable";
  purposes: KeyPurposeStatus[];
  warnings: string[];
}

export interface DemoScenarioResponse {
  trace_id: string;
  trace_status: TraceStatus;
  results: GatewayDecision[];
  approval_actions: Array<{
    approval_id: string;
    tool_call_id: string;
    status: ApprovalStatus;
    action_name: string;
  }>;
}
