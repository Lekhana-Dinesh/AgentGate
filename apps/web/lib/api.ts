import { apiBaseUrl } from "@/lib/config";
import {
  clearSession,
  clearStoredCsrfToken,
  COOKIE_SESSION_TOKEN,
  getStoredCsrfToken,
  isCookieSessionToken,
  setStoredCsrfToken,
} from "@/lib/session";
import type {
  Agent,
  AgentAPIKeyResponse,
  AgentAPIKeySummary,
  AuditIntegrityCheckpointRecord,
  AuditIntegrityCheckpointRunResponse,
  AuditIntegrityCheckpointVerifyResponse,
  AuditIntegrityStatus,
  AuditIntegrityVerifyResponse,
  AuditExportConfig,
  AuditExportRunResponse,
  AuditExportStatus,
  ApprovalRequest,
  AuditEvent,
  CSRFTokenResponse,
  CurrentUser,
  DemoScenarioResponse,
  DashboardOverview,
  GitHubGovernedDemoResponse,
  JobRecord,
  LoginPayload,
  LogoutResponse,
  OIDCConfigStatus,
  OnboardingActionResponse,
  OnboardingStatus,
  Policy,
  PolicySimulationRequest,
  PolicySimulationResult,
  RetentionPurgeResponse,
  RetentionStatus,
  ScheduledTask,
  ScheduledTaskRunResponse,
  SettingsOverview,
  TokenResponse,
  ToolSafeSummary,
  ToolSafeDetail,
  ToolSafeMetadataCreateInput,
  ToolSafeMetadataUpdateInput,
  ToolCall,
  Trace,
  UserRecord,
} from "@/types/api";

const CSRF_HEADER_NAME = "X-CSRF-Token";
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

export class ApiError extends Error {
  status: number;
  code: string;
  requestId: string | null;
  extra: Record<string, unknown> | null;

  constructor(
    message: string,
    options: {
      status: number;
      code: string;
      requestId?: string | null;
      extra?: Record<string, unknown> | null;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId ?? null;
    this.extra = options.extra ?? null;
  }
}

async function request<T>(
  path: string,
  options: RequestInit & { token?: string | null; skipAuthRedirect?: boolean } = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const method = (options.method || "GET").toUpperCase();
  const useCookieSession = isCookieSessionToken(options.token);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token && !useCookieSession) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }
  if (useCookieSession && !SAFE_METHODS.has(method)) {
    const csrfToken = (await ensureCsrfToken()) || null;
    if (csrfToken) {
      headers.set(CSRF_HEADER_NAME, csrfToken);
    }
  }

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
    credentials: "include",
    headers,
  });

  if (!response.ok) {
    const errorPayload = await response.json().catch(() => null);
    const detail =
      errorPayload?.error?.detail || errorPayload?.detail || "The request could not be completed.";
    const error = new ApiError(detail, {
      status: response.status,
      code: errorPayload?.error?.code || "request_failed",
      requestId: errorPayload?.error?.request_id || response.headers.get("X-Request-ID"),
      extra: errorPayload?.error?.extra || null,
    });
    if (useCookieSession && (error.code === "csrf_invalid" || error.code === "csrf_required")) {
      clearStoredCsrfToken();
    }
    if (!options.skipAuthRedirect && response.status === 401 && typeof window !== "undefined") {
      clearSession();
      window.location.assign("/login?reason=session-expired");
    }
    throw error;
  }

  return (await response.json()) as T;
}

async function ensureCsrfToken(): Promise<string | null> {
  const stored = getStoredCsrfToken();
  if (stored) {
    return stored;
  }

  const response = await fetch(`${apiBaseUrl}/v1/auth/csrf-token`, {
    credentials: "include",
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    return null;
  }
  const payload = (await response.json()) as CSRFTokenResponse;
  if (payload.csrf_token) {
    setStoredCsrfToken(payload.csrf_token);
  }
  return payload.csrf_token;
}

export class AgentGateApiClient {
  async login(payload: LoginPayload): Promise<TokenResponse> {
    return request<TokenResponse>("/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
      skipAuthRedirect: true,
    });
  }

  async getOIDCConfigStatus(tenantSlug: string): Promise<OIDCConfigStatus> {
    return request<OIDCConfigStatus>(`/v1/auth/oidc/${encodeURIComponent(tenantSlug)}/config-status`, {
      skipAuthRedirect: true,
    });
  }

  async exchangeOIDCTicket(ticket: string): Promise<TokenResponse> {
    return request<TokenResponse>("/v1/auth/oidc/exchange", {
      method: "POST",
      body: JSON.stringify({ ticket }),
      skipAuthRedirect: true,
    });
  }

  async getCurrentUser(
    token: string | null = COOKIE_SESSION_TOKEN,
    options: { skipAuthRedirect?: boolean } = {},
  ): Promise<CurrentUser> {
    return request<CurrentUser>("/v1/auth/me", {
      token,
      skipAuthRedirect: options.skipAuthRedirect,
    });
  }

  async getCsrfToken(): Promise<CSRFTokenResponse> {
    const response = await request<CSRFTokenResponse>("/v1/auth/csrf-token", {
      token: COOKIE_SESSION_TOKEN,
      skipAuthRedirect: true,
    });
    if (response.csrf_token) {
      setStoredCsrfToken(response.csrf_token);
    }
    return response;
  }

  async logout(token: string | null = COOKIE_SESSION_TOKEN): Promise<LogoutResponse> {
    return request<LogoutResponse>("/v1/auth/logout", {
      method: "POST",
      token,
      skipAuthRedirect: true,
      body: JSON.stringify({}),
    });
  }

  async getDashboardOverview(token: string): Promise<DashboardOverview> {
    return request<DashboardOverview>("/v1/dashboard/overview", { token });
  }

  async getOnboardingStatus(token: string): Promise<OnboardingStatus> {
    return request<OnboardingStatus>("/v1/onboarding/status", { token });
  }

  async dismissOnboarding(token: string): Promise<OnboardingActionResponse> {
    return request<OnboardingActionResponse>("/v1/onboarding/dismiss", {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async resetOnboarding(token: string): Promise<OnboardingActionResponse> {
    return request<OnboardingActionResponse>("/v1/onboarding/reset", {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async createOnboardingDemoPolicy(token: string): Promise<OnboardingActionResponse> {
    return request<OnboardingActionResponse>("/v1/onboarding/demo-policy", {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async listAgents(token: string): Promise<Agent[]> {
    return request<Agent[]>("/v1/agents", { token });
  }

  async listToolSummaries(token: string): Promise<ToolSafeSummary[]> {
    return request<ToolSafeSummary[]>("/v1/tools/summary", { token });
  }

  async getToolSafeDetail(token: string, toolId: string): Promise<ToolSafeDetail> {
    return request<ToolSafeDetail>(`/v1/tools/${toolId}/safe-detail`, { token });
  }

  async createToolSafeMetadata(token: string, payload: ToolSafeMetadataCreateInput): Promise<ToolSafeDetail> {
    return request<ToolSafeDetail>("/v1/tools/safe-metadata", {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async updateToolSafeMetadata(
    token: string,
    toolId: string,
    payload: ToolSafeMetadataUpdateInput,
  ): Promise<ToolSafeDetail> {
    return request<ToolSafeDetail>(`/v1/tools/${toolId}/safe-metadata`, {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    });
  }

  async probeToolHealth(token: string, toolId: string): Promise<ToolSafeSummary> {
    return request<ToolSafeSummary>(`/v1/tools/${toolId}/probe-health`, {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async getAgent(token: string, agentId: string): Promise<Agent> {
    return request<Agent>(`/v1/agents/${agentId}`, { token });
  }

  async listAgentApiKeys(token: string, agentId: string): Promise<AgentAPIKeySummary[]> {
    return request<AgentAPIKeySummary[]>(`/v1/agents/${agentId}/api-keys`, { token });
  }

  async createAgentApiKey(
    token: string,
    agentId: string,
    payload: {
      name: string;
      expires_in_days: number | null;
      scopes: Array<"gateway:invoke">;
    },
  ): Promise<AgentAPIKeyResponse> {
    return request<AgentAPIKeyResponse>(`/v1/agents/${agentId}/api-keys`, {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async revokeAgentApiKey(token: string, agentId: string, apiKeyId: string): Promise<{ message: string }> {
    return request<{ message: string }>(`/v1/agents/${agentId}/api-keys/${apiKeyId}/revoke`, {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async suspendAgent(token: string, agentId: string): Promise<Agent> {
    return request<Agent>(`/v1/agents/${agentId}/suspend`, {
      method: "POST",
      token,
    });
  }

  async revokeAgent(token: string, agentId: string): Promise<Agent> {
    return request<Agent>(`/v1/agents/${agentId}/revoke`, {
      method: "POST",
      token,
    });
  }

  async listToolCalls(token: string, params = ""): Promise<ToolCall[]> {
    return request<ToolCall[]>(`/v1/gateway/tool-calls${params}`, { token });
  }

  async listApprovals(token: string, params = ""): Promise<ApprovalRequest[]> {
    return request<ApprovalRequest[]>(`/v1/approvals${params}`, { token });
  }

  async approveRequest(token: string, approvalId: string, comment: string, executeNow = true) {
    return request<ApprovalRequest>(`/v1/approvals/${approvalId}/approve`, {
      method: "POST",
      token,
      body: JSON.stringify({ approver_comment: comment, execute_now: executeNow }),
    });
  }

  async rejectRequest(token: string, approvalId: string, comment: string) {
    return request<ApprovalRequest>(`/v1/approvals/${approvalId}/reject`, {
      method: "POST",
      token,
      body: JSON.stringify({ approver_comment: comment, execute_now: false }),
    });
  }

  async listPolicies(token: string): Promise<Policy[]> {
    return request<Policy[]>("/v1/policies", { token });
  }

  async createPolicy(
    token: string,
    payload: {
      name: string;
      description: string;
      enabled: boolean;
      severity: "low" | "medium" | "high" | "critical";
      decision: "allow" | "block" | "require_approval" | "redact";
      conditions: {
        match: "all" | "any";
        rules: Array<{
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
        }>;
      };
    },
  ) {
    return request<Policy>("/v1/policies", {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async updatePolicy(
    token: string,
    policyId: string,
    updates: {
      description?: string;
      enabled?: boolean;
      severity?: "low" | "medium" | "high" | "critical";
      decision?: "allow" | "block" | "require_approval" | "redact";
      conditions?: {
        match: "all" | "any";
        rules: Array<{
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
        }>;
      };
    },
  ) {
    return request<Policy>(`/v1/policies/${policyId}`, {
      method: "PUT",
      token,
      body: JSON.stringify(updates),
    });
  }

  async simulatePolicy(token: string, payload: PolicySimulationRequest): Promise<PolicySimulationResult> {
    return request<PolicySimulationResult>("/v1/policies/simulate", {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async listTraces(token: string): Promise<Trace[]> {
    return request<Trace[]>("/v1/traces", { token });
  }

  async getTrace(token: string, traceId: string): Promise<Trace> {
    return request<Trace>(`/v1/traces/${traceId}`, { token });
  }

  async listAuditEvents(token: string, params = ""): Promise<AuditEvent[]> {
    return request<AuditEvent[]>(`/v1/audit/events${params}`, { token });
  }

  async listJobs(token: string, params = ""): Promise<JobRecord[]> {
    return request<JobRecord[]>(`/v1/jobs${params}`, { token });
  }

  async listAuditExports(token: string): Promise<AuditExportConfig[]> {
    return request<AuditExportConfig[]>("/v1/audit-exports", { token });
  }

  async updateAuditExport(
    token: string,
    configId: string,
    payload: { enabled?: boolean },
  ): Promise<AuditExportConfig> {
    return request<AuditExportConfig>(`/v1/audit-exports/${configId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    });
  }

  async getAuditIntegrityStatus(token: string): Promise<AuditIntegrityStatus> {
    return request<AuditIntegrityStatus>("/v1/audit-integrity/status", { token });
  }

  async verifyAuditIntegrity(token: string): Promise<AuditIntegrityVerifyResponse> {
    return request<AuditIntegrityVerifyResponse>("/v1/audit-integrity/verify", {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async listAuditIntegrityCheckpoints(token: string): Promise<AuditIntegrityCheckpointRecord[]> {
    return request<AuditIntegrityCheckpointRecord[]>("/v1/audit-integrity/checkpoints", { token });
  }

  async createAuditIntegrityCheckpoint(token: string): Promise<AuditIntegrityCheckpointRunResponse> {
    return request<AuditIntegrityCheckpointRunResponse>("/v1/audit-integrity/checkpoints", {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async verifyAuditIntegrityCheckpoint(
    token: string,
    checkpointId: string,
  ): Promise<AuditIntegrityCheckpointVerifyResponse> {
    return request<AuditIntegrityCheckpointVerifyResponse>(
      `/v1/audit-integrity/checkpoints/${checkpointId}/verify`,
      {
        method: "POST",
        token,
        body: JSON.stringify({}),
      },
    );
  }

  async getAuditExportStatus(token: string, configId: string): Promise<AuditExportStatus> {
    return request<AuditExportStatus>(`/v1/audit-exports/${configId}/status`, { token });
  }

  async runAuditExport(
    token: string,
    configId: string,
    payload: { dry_run?: boolean } = {},
  ): Promise<AuditExportRunResponse> {
    return request<AuditExportRunResponse>(`/v1/audit-exports/${configId}/run`, {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async getRetentionStatus(token: string): Promise<RetentionStatus> {
    return request<RetentionStatus>("/v1/retention/status", { token });
  }

  async runRetentionPurge(
    token: string,
    payload: {
      dry_run?: boolean;
      limit?: number;
      retention_classes?: string[];
      tool_name?: string;
      tool_call_ids?: string[];
    },
  ): Promise<RetentionPurgeResponse> {
    return request<RetentionPurgeResponse>("/v1/retention/purge", {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async listScheduledTasks(token: string): Promise<ScheduledTask[]> {
    return request<ScheduledTask[]>("/v1/scheduled-tasks", { token });
  }

  async listUsers(token: string): Promise<UserRecord[]> {
    return request<UserRecord[]>("/v1/users", { token });
  }

  async getUser(token: string, userId: string): Promise<UserRecord> {
    return request<UserRecord>(`/v1/users/${userId}`, { token });
  }

  async updateUser(
    token: string,
    userId: string,
    payload: { full_name?: string; role?: string },
  ): Promise<UserRecord> {
    return request<UserRecord>(`/v1/users/${userId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    });
  }

  async deactivateUser(token: string, userId: string, reason?: string): Promise<UserRecord> {
    return request<UserRecord>(`/v1/users/${userId}/deactivate`, {
      method: "POST",
      token,
      body: JSON.stringify(reason ? { reason } : {}),
    });
  }

  async reactivateUser(token: string, userId: string): Promise<UserRecord> {
    return request<UserRecord>(`/v1/users/${userId}/reactivate`, {
      method: "POST",
      token,
    });
  }

  async getSettingsOverview(token: string): Promise<SettingsOverview> {
    return request<SettingsOverview>("/v1/settings/overview", { token });
  }

  async updateScheduledTask(
    token: string,
    taskId: string,
    payload: { enabled?: boolean },
  ): Promise<ScheduledTask> {
    return request<ScheduledTask>(`/v1/scheduled-tasks/${taskId}`, {
      method: "PATCH",
      token,
      body: JSON.stringify(payload),
    });
  }

  async runScheduledTaskNow(token: string, taskId: string): Promise<ScheduledTaskRunResponse> {
    return request<ScheduledTaskRunResponse>(`/v1/scheduled-tasks/${taskId}/run-now`, {
      method: "POST",
      token,
      body: JSON.stringify({}),
    });
  }

  async runSalesScenario(token: string): Promise<DemoScenarioResponse> {
    return request<DemoScenarioResponse>(
      "/v1/demo/run-sales-agent-risk-scenario",
      {
        method: "POST",
        token,
      },
    );
  }

  async runGovernedGitHubScenario(token: string): Promise<GitHubGovernedDemoResponse> {
    return request<GitHubGovernedDemoResponse>(
      "/v1/demo/run-governed-github-workflow",
      {
        method: "POST",
        token,
      },
    );
  }
}

export const apiClient = new AgentGateApiClient();
