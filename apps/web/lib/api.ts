import { apiBaseUrl } from "@/lib/config";
import { clearSession } from "@/lib/session";
import type {
  Agent,
  AuditExportConfig,
  AuditExportRunResponse,
  AuditExportStatus,
  ApprovalRequest,
  AuditEvent,
  CurrentUser,
  DemoScenarioResponse,
  DashboardOverview,
  JobRecord,
  LoginPayload,
  OIDCConfigStatus,
  Policy,
  RetentionPurgeResponse,
  RetentionStatus,
  TokenResponse,
  ToolCall,
  Trace,
} from "@/types/api";

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
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...options,
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
    if (!options.skipAuthRedirect && response.status === 401 && typeof window !== "undefined") {
      clearSession();
      window.location.assign("/login?reason=session-expired");
    }
    throw error;
  }

  return (await response.json()) as T;
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

  async getCurrentUser(token: string): Promise<CurrentUser> {
    return request<CurrentUser>("/v1/auth/me", { token });
  }

  async getDashboardOverview(token: string): Promise<DashboardOverview> {
    return request<DashboardOverview>("/v1/dashboard/overview", { token });
  }

  async listAgents(token: string): Promise<Agent[]> {
    return request<Agent[]>("/v1/agents", { token });
  }

  async getAgent(token: string, agentId: string): Promise<Agent> {
    return request<Agent>(`/v1/agents/${agentId}`, { token });
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
      severity: string;
      decision: string;
      conditions: { match: "all" | "any"; rules: Array<{ field: string; operator: string; value: string | number | boolean }> };
    },
  ) {
    return request<Policy>("/v1/policies", {
      method: "POST",
      token,
      body: JSON.stringify(payload),
    });
  }

  async updatePolicy(token: string, policyId: string, updates: Partial<Policy>) {
    return request<Policy>(`/v1/policies/${policyId}`, {
      method: "PUT",
      token,
      body: JSON.stringify(updates),
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

  async runSalesScenario(token: string): Promise<DemoScenarioResponse> {
    return request<DemoScenarioResponse>(
      "/v1/demo/run-sales-agent-risk-scenario",
      {
        method: "POST",
        token,
      },
    );
  }
}

export const apiClient = new AgentGateApiClient();
