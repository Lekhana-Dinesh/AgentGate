export type UserRole =
  | "owner"
  | "admin"
  | "security_reviewer"
  | "developer"
  | "approver"
  | "viewer";

export type AgentEnvironment = "development" | "staging" | "production";
export type AgentStatus = "active" | "suspended" | "revoked";
export type RiskBand = "low" | "medium" | "high" | "critical";
export type ToolType = "mcp" | "rest" | "mock" | "database" | "email" | "crm" | "custom" | "github";
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
  | "retention_purge.placeholder";
export type PayloadRetentionClass = "standard" | "short_lived" | "extended" | "legal_hold";
export type AuditExportDestinationType =
  | "webhook"
  | "splunk_hec"
  | "datadog"
  | "http_json"
  | "custom_placeholder";
export type AuditEventSeverity = "info" | "warning" | "error" | "critical";

export interface CurrentUser {
  id: string;
  tenant_id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
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
  access_token: string;
  token_type: "bearer";
}

export interface OIDCConfigStatus {
  configured: boolean;
  enabled: boolean;
  local_auth_enabled: boolean;
  provider_name?: string | null;
  login_url?: string | null;
  reason?: string | null;
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
