"use client";

import Link from "next/link";
import { Dispatch, FormEvent, SetStateAction, useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input, Textarea } from "@/components/ui/input";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { apiBaseUrl } from "@/lib/config";
import { formatDate } from "@/lib/utils";
import type {
  RiskBand,
  ToolCredentialReference,
  ToolSafeDetail,
  ToolSafeMetadataCreateInput,
  ToolSafeMetadataUpdateInput,
  ToolSafeSummary,
  ToolType,
} from "@/types/api";

const selectClassName =
  "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm outline-none transition focus:border-slate-400";

const connectorGuides: Partial<Record<ToolType, { label: string; path: string }>> = {
  github: { label: "GitHub guide", path: "docs/connectors/github.md" },
  jira: { label: "Jira guide", path: "docs/connectors/jira.md" },
  mcp: { label: "MCP guide", path: "docs/connectors/mcp.md" },
  mock: { label: "Tool management guide", path: "docs/operations/tool-management.md" },
};

const authModesByType: Record<ManagedToolType, string[]> = {
  github: ["env_token", "github_app", "env_pat"],
  jira: ["env_token", "basic_env"],
  mcp: ["none", "bearer_env", "api_key_env"],
  mock: [],
};

type ManagedToolType = Extract<ToolType, "github" | "jira" | "mcp" | "mock">;
type TrustDomain = "internal" | "external" | "unknown";
type ToolTemplateId =
  | "github_env_token"
  | "github_app"
  | "jira_env_token"
  | "jira_basic_env"
  | "mcp_http"
  | "mock_demo";

type ToolMetadataDraft = {
  name: string;
  type: ManagedToolType;
  description: string;
  enabled: boolean;
  risk_level: RiskBand;
  base_url: string;
  auth_mode: string;
  trust_domain: TrustDomain;
  repository_allowlist: string;
  internal_repositories: string;
  internal_owners: string;
  public_repositories: string;
  app_id: string;
  installation_id: string;
  project_allowlist: string;
  issue_type_allowlist: string;
  external_project_keys: string;
  transition_allowlist: string;
  assignee_allowlist: string;
  transport: "http";
  allowed_tool_names: string;
  blocked_tool_names: string;
};

const templateDefinitions: Array<{
  id: ToolTemplateId;
  title: string;
  description: string;
  type: ManagedToolType;
}> = [
  {
    id: "github_env_token",
    title: "GitHub env-token",
    description: "The strongest current first live connector for a controlled pilot.",
    type: "github",
  },
  {
    id: "github_app",
    title: "GitHub App",
    description: "Production-minded GitHub metadata with App and installation IDs only.",
    type: "github",
  },
  {
    id: "jira_env_token",
    title: "Jira env-token",
    description: "A constrained second-phase Jira connector using external token injection.",
    type: "jira",
  },
  {
    id: "jira_basic_env",
    title: "Jira basic-env",
    description: "Jira Cloud-style email plus API-token metadata without exposing either value.",
    type: "jira",
  },
  {
    id: "mcp_http",
    title: "MCP HTTP allowlist",
    description: "HTTP-only MCP metadata for tightly allowlisted internal tool names.",
    type: "mcp",
  },
  {
    id: "mock_demo",
    title: "Mock or demo tool",
    description: "A safe local or demo placeholder with no external credential dependency.",
    type: "mock",
  },
];

function isManagedToolType(value: ToolType): value is ManagedToolType {
  return value === "github" || value === "jira" || value === "mcp" || value === "mock";
}

function renderLabel(value: string | null | undefined): string {
  return (value || "unknown").replaceAll("_", " ");
}

function renderTypeLabel(value: ToolType): string {
  if (value === "mcp") {
    return "MCP";
  }
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function renderAuthModeLabel(value: string | null | undefined): string {
  return renderLabel(value || "not_applicable");
}

function renderConnectorModeLabel(value: ToolSafeSummary["connector_mode"] | null | undefined): string {
  switch (value) {
    case "demo_safe_mock":
      return "demo-safe mock";
    case "live_connector":
      return "live connector";
    default:
      return "not applicable";
  }
}

function renderConnectorModeTone(value: ToolSafeSummary["connector_mode"] | null | undefined): string {
  if (value === "demo_safe_mock") {
    return "warning";
  }
  if (value === "live_connector") {
    return "low";
  }
  return "low";
}

function formatAllowlistCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts).filter(([, value]) => value > 0);
  if (!entries.length) {
    return "No scoped allowlists";
  }
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${value} ${renderLabel(key)}`)
    .join(" / ");
}

function formatActions(actions: string[]): string {
  if (!actions.length) {
    return "No documented action set";
  }
  return actions.join(", ");
}

function renderCredentialReferenceSummary(reference: ToolCredentialReference): string {
  if (reference.reference_name) {
    return reference.reference_name;
  }
  if (reference.reference_type === "secret_ref") {
    return "Configured through an external secret reference";
  }
  if (reference.reference_type === "vault") {
    return "Configured through an external vault reference";
  }
  return "Configured outside AgentGate";
}

function renderCredentialReferenceState(reference: ToolCredentialReference): {
  tone: string;
  label: string;
} {
  if (reference.configured === true) {
    return { tone: "ready", label: "available" };
  }
  if (reference.configured === false) {
    return { tone: "warning", label: "missing" };
  }
  return { tone: "low", label: "external" };
}

function renderProbeSourceLabel(value: "manual_probe" | "health_check_job" | null | undefined): string {
  if (value === "health_check_job") {
    return "scheduled or job-driven";
  }
  if (value === "manual_probe") {
    return "manual";
  }
  return "unknown";
}

function parseDelimitedList(value: string): string[] {
  const seen = new Set<string>();
  const items = value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
  const normalized: string[] = [];
  for (const item of items) {
    const fingerprint = item.toLowerCase();
    if (seen.has(fingerprint)) {
      continue;
    }
    seen.add(fingerprint);
    normalized.push(item);
  }
  return normalized;
}

function serializeList(values: string[]): string {
  return values.join("\n");
}

function buildDraftFromTemplate(templateId: ToolTemplateId): ToolMetadataDraft {
  switch (templateId) {
    case "github_app":
      return {
        name: "GitHub App",
        type: "github",
        description: "GitHub App-backed repository metadata and issue workflow connector",
        enabled: true,
        risk_level: "high",
        base_url: "https://api.github.com",
        auth_mode: "github_app",
        trust_domain: "internal",
        repository_allowlist: "agentgate-labs/internal-agentgate\noctocat/hello-world",
        internal_repositories: "agentgate-labs/internal-agentgate",
        internal_owners: "agentgate-labs",
        public_repositories: "octocat/hello-world",
        app_id: "",
        installation_id: "",
        project_allowlist: "",
        issue_type_allowlist: "",
        external_project_keys: "",
        transition_allowlist: "",
        assignee_allowlist: "",
        transport: "http",
        allowed_tool_names: "",
        blocked_tool_names: "",
      };
    case "jira_env_token":
      return {
        name: "Jira",
        type: "jira",
        description: "Governed Jira issue workflow connector",
        enabled: true,
        risk_level: "high",
        base_url: "https://jira.example.test",
        auth_mode: "env_token",
        trust_domain: "internal",
        repository_allowlist: "",
        internal_repositories: "",
        internal_owners: "",
        public_repositories: "",
        app_id: "",
        installation_id: "",
        project_allowlist: "OPS\nSUPPORT",
        issue_type_allowlist: "task\nbug\nincident",
        external_project_keys: "SUPPORT",
        transition_allowlist: "31\ndone",
        assignee_allowlist: "acct-support-1\nacct-oncall-1",
        transport: "http",
        allowed_tool_names: "",
        blocked_tool_names: "",
      };
    case "jira_basic_env":
      return {
        ...buildDraftFromTemplate("jira_env_token"),
        auth_mode: "basic_env",
        name: "Jira Cloud",
      };
    case "mcp_http":
      return {
        name: "Internal MCP",
        type: "mcp",
        description: "Governed MCP connector for an internal HTTP tool server",
        enabled: false,
        risk_level: "high",
        base_url: "https://mcp.internal.example",
        auth_mode: "bearer_env",
        trust_domain: "internal",
        repository_allowlist: "",
        internal_repositories: "",
        internal_owners: "",
        public_repositories: "",
        app_id: "",
        installation_id: "",
        project_allowlist: "",
        issue_type_allowlist: "",
        external_project_keys: "",
        transition_allowlist: "",
        assignee_allowlist: "",
        transport: "http",
        allowed_tool_names: "knowledge_search\nticket_comment",
        blocked_tool_names: "delete_records\nshell_execute",
      };
    case "mock_demo":
      return {
        name: "Demo Tool",
        type: "mock",
        description: "Mock or rehearsal-only tool for demo and policy validation",
        enabled: true,
        risk_level: "medium",
        base_url: "",
        auth_mode: "",
        trust_domain: "internal",
        repository_allowlist: "",
        internal_repositories: "",
        internal_owners: "",
        public_repositories: "",
        app_id: "",
        installation_id: "",
        project_allowlist: "",
        issue_type_allowlist: "",
        external_project_keys: "",
        transition_allowlist: "",
        assignee_allowlist: "",
        transport: "http",
        allowed_tool_names: "",
        blocked_tool_names: "",
      };
    case "github_env_token":
    default:
      return {
        name: "GitHub",
        type: "github",
        description: "GitHub repository metadata and issue workflow connector",
        enabled: true,
        risk_level: "high",
        base_url: "https://api.github.com",
        auth_mode: "env_token",
        trust_domain: "internal",
        repository_allowlist: "agentgate-labs/internal-agentgate\noctocat/hello-world",
        internal_repositories: "agentgate-labs/internal-agentgate",
        internal_owners: "agentgate-labs",
        public_repositories: "octocat/hello-world",
        app_id: "",
        installation_id: "",
        project_allowlist: "",
        issue_type_allowlist: "",
        external_project_keys: "",
        transition_allowlist: "",
        assignee_allowlist: "",
        transport: "http",
        allowed_tool_names: "",
        blocked_tool_names: "",
      };
  }
}

function buildDraftFromDetail(detail: ToolSafeDetail): ToolMetadataDraft {
  return {
    name: detail.name,
    type: detail.type as ManagedToolType,
    description: detail.description || "",
    enabled: detail.enabled,
    risk_level: detail.risk_level,
    base_url: detail.base_url || "",
    auth_mode: detail.auth_mode || "",
    trust_domain: (detail.trust_domain as TrustDomain | null) || "unknown",
    repository_allowlist: serializeList(detail.repository_allowlist),
    internal_repositories: serializeList(detail.internal_repositories),
    internal_owners: serializeList(detail.internal_owners),
    public_repositories: serializeList(detail.public_repositories),
    app_id: detail.app_id || "",
    installation_id: detail.installation_id || "",
    project_allowlist: serializeList(detail.project_allowlist),
    issue_type_allowlist: serializeList(detail.issue_type_allowlist),
    external_project_keys: serializeList(detail.external_project_keys),
    transition_allowlist: serializeList(detail.transition_allowlist),
    assignee_allowlist: serializeList(detail.assignee_allowlist),
    transport: detail.transport === "http" ? "http" : "http",
    allowed_tool_names: serializeList(detail.allowed_tool_names),
    blocked_tool_names: serializeList(detail.blocked_tool_names),
  };
}

function toToolSafeSummary(detail: ToolSafeDetail): ToolSafeSummary {
  return {
    id: detail.id,
    name: detail.name,
    type: detail.type,
    description: detail.description,
    enabled: detail.enabled,
    risk_level: detail.risk_level,
    base_url_host: detail.base_url_host,
    auth_mode: detail.auth_mode,
    trust_domain: detail.trust_domain,
    allowlist_counts: detail.allowlist_counts,
    supported_actions: detail.supported_actions,
    health_status: detail.health_status,
    health_can_connect: detail.health_can_connect,
    health_probe_performed: detail.health_probe_performed,
    health_checked_at: detail.health_checked_at,
    connector_mode: detail.connector_mode,
    live_execution_ready: detail.live_execution_ready,
    status_summary: detail.status_summary,
    warning_flags: detail.warning_flags,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  };
}

function buildCreatePayload(draft: ToolMetadataDraft): ToolSafeMetadataCreateInput {
  const payload: ToolSafeMetadataCreateInput = {
    name: draft.name.trim(),
    type: draft.type,
    description: draft.description.trim(),
    risk_level: draft.risk_level,
    enabled: draft.enabled,
  };

  if (draft.type !== "mock") {
    payload.base_url = draft.base_url.trim() || null;
  }
  if (draft.type === "github") {
    payload.auth_mode = draft.auth_mode || "env_token";
    payload.repository_allowlist = parseDelimitedList(draft.repository_allowlist);
    payload.internal_repositories = parseDelimitedList(draft.internal_repositories);
    payload.internal_owners = parseDelimitedList(draft.internal_owners);
    payload.public_repositories = parseDelimitedList(draft.public_repositories);
    if (payload.auth_mode === "github_app") {
      payload.app_id = draft.app_id.trim() || null;
      payload.installation_id = draft.installation_id.trim() || null;
    }
  }
  if (draft.type === "jira") {
    payload.auth_mode = draft.auth_mode || "env_token";
    payload.project_allowlist = parseDelimitedList(draft.project_allowlist);
    payload.issue_type_allowlist = parseDelimitedList(draft.issue_type_allowlist);
    payload.external_project_keys = parseDelimitedList(draft.external_project_keys);
    payload.transition_allowlist = parseDelimitedList(draft.transition_allowlist);
    payload.assignee_allowlist = parseDelimitedList(draft.assignee_allowlist);
  }
  if (draft.type === "mcp") {
    payload.base_url = draft.base_url.trim() || null;
    payload.transport = "http";
    payload.auth_mode = draft.auth_mode || "none";
    payload.trust_domain = draft.trust_domain;
    payload.allowed_tool_names = parseDelimitedList(draft.allowed_tool_names);
    payload.blocked_tool_names = parseDelimitedList(draft.blocked_tool_names);
  }

  return payload;
}

function buildUpdatePayload(draft: ToolMetadataDraft): ToolSafeMetadataUpdateInput {
  const createPayload = buildCreatePayload(draft);
  const { type: _type, ...updates } = createPayload;
  return updates;
}

function MetadataEditor({
  draft,
  setDraft,
  authModes,
  disabled,
}: {
  draft: ToolMetadataDraft;
  setDraft: Dispatch<SetStateAction<ToolMetadataDraft>>;
  authModes: string[];
  disabled: boolean;
}) {
  function update<K extends keyof ToolMetadataDraft>(field: K, value: ToolMetadataDraft[K]) {
    setDraft((current) => ({ ...current, [field]: value }));
  }

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 md:grid-cols-2">
        <label className="grid gap-2 text-sm text-slate-700">
          <span className="font-medium text-slate-900">Name</span>
          <Input value={draft.name} onChange={(event) => update("name", event.target.value)} disabled={disabled} />
        </label>
        <label className="grid gap-2 text-sm text-slate-700">
          <span className="font-medium text-slate-900">Risk level</span>
          <select
            value={draft.risk_level}
            onChange={(event) => update("risk_level", event.target.value as RiskBand)}
            className={selectClassName}
            disabled={disabled}
          >
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
            <option value="low">Low</option>
          </select>
        </label>
      </div>

      <label className="grid gap-2 text-sm text-slate-700">
        <span className="font-medium text-slate-900">Description</span>
        <Textarea value={draft.description} onChange={(event) => update("description", event.target.value)} disabled={disabled} />
      </label>

      <label className="flex items-center gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
        <input
          type="checkbox"
          checked={draft.enabled}
          onChange={(event) => update("enabled", event.target.checked)}
          disabled={disabled}
        />
        Enable this connector metadata record
      </label>

      {draft.type !== "mock" ? (
        <label className="grid gap-2 text-sm text-slate-700">
          <span className="font-medium text-slate-900">Base URL</span>
          <Input value={draft.base_url} onChange={(event) => update("base_url", event.target.value)} disabled={disabled} />
        </label>
      ) : null}

      {authModes.length ? (
        <label className="grid gap-2 text-sm text-slate-700">
          <span className="font-medium text-slate-900">Auth mode</span>
          <select
            value={draft.auth_mode}
            onChange={(event) => update("auth_mode", event.target.value)}
            className={selectClassName}
            disabled={disabled}
          >
            {authModes.map((mode) => (
              <option key={mode} value={mode}>
                {renderAuthModeLabel(mode)}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {draft.type === "github" ? (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Repository allowlist</span>
              <Textarea
                value={draft.repository_allowlist}
                onChange={(event) => update("repository_allowlist", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Internal repositories</span>
              <Textarea
                value={draft.internal_repositories}
                onChange={(event) => update("internal_repositories", event.target.value)}
                disabled={disabled}
              />
            </label>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Internal owners</span>
              <Textarea
                value={draft.internal_owners}
                onChange={(event) => update("internal_owners", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Public repositories</span>
              <Textarea
                value={draft.public_repositories}
                onChange={(event) => update("public_repositories", event.target.value)}
                disabled={disabled}
              />
            </label>
          </div>
          {draft.auth_mode === "github_app" ? (
            <div className="grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm text-slate-700">
                <span className="font-medium text-slate-900">GitHub App ID</span>
                <Input value={draft.app_id} onChange={(event) => update("app_id", event.target.value)} disabled={disabled} />
              </label>
              <label className="grid gap-2 text-sm text-slate-700">
                <span className="font-medium text-slate-900">Installation ID</span>
                <Input
                  value={draft.installation_id}
                  onChange={(event) => update("installation_id", event.target.value)}
                  disabled={disabled}
                />
              </label>
            </div>
          ) : null}
        </>
      ) : null}

      {draft.type === "jira" ? (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Project allowlist</span>
              <Textarea value={draft.project_allowlist} onChange={(event) => update("project_allowlist", event.target.value)} disabled={disabled} />
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Issue type allowlist</span>
              <Textarea value={draft.issue_type_allowlist} onChange={(event) => update("issue_type_allowlist", event.target.value)} disabled={disabled} />
            </label>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">External project keys</span>
              <Textarea
                value={draft.external_project_keys}
                onChange={(event) => update("external_project_keys", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Transition allowlist</span>
              <Textarea
                value={draft.transition_allowlist}
                onChange={(event) => update("transition_allowlist", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Assignee allowlist</span>
              <Textarea
                value={draft.assignee_allowlist}
                onChange={(event) => update("assignee_allowlist", event.target.value)}
                disabled={disabled}
              />
            </label>
          </div>
        </>
      ) : null}

      {draft.type === "mcp" ? (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Trust domain</span>
              <select
                value={draft.trust_domain}
                onChange={(event) => update("trust_domain", event.target.value as TrustDomain)}
                className={selectClassName}
                disabled={disabled}
              >
                <option value="internal">Internal</option>
                <option value="external">External</option>
                <option value="unknown">Unknown</option>
              </select>
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Transport</span>
              <Input value="http" disabled />
            </label>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Allowed tool names</span>
              <Textarea
                value={draft.allowed_tool_names}
                onChange={(event) => update("allowed_tool_names", event.target.value)}
                disabled={disabled}
              />
            </label>
            <label className="grid gap-2 text-sm text-slate-700">
              <span className="font-medium text-slate-900">Blocked tool names</span>
              <Textarea
                value={draft.blocked_tool_names}
                onChange={(event) => update("blocked_tool_names", event.target.value)}
                disabled={disabled}
              />
            </label>
          </div>
        </>
      ) : null}
    </div>
  );
}

export default function ToolsPage() {
  const { token, user } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [busyActionKey, setBusyActionKey] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState<ToolTemplateId>("github_env_token");
  const [createDraft, setCreateDraft] = useState<ToolMetadataDraft>(buildDraftFromTemplate("github_env_token"));
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [selectedTool, setSelectedTool] = useState<ToolSafeDetail | null>(null);
  const [editDraft, setEditDraft] = useState<ToolMetadataDraft | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const canView = user ? ["owner", "admin", "security_reviewer"].includes(user.role) : false;
  const canManage = user ? ["owner", "admin"].includes(user.role) : false;
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listToolSummaries(token || ""),
    [token, refreshKey],
    Boolean(token) && canView,
  );

  function setManagedEditDraft(update: SetStateAction<ToolMetadataDraft>) {
    setEditDraft((current) => {
      const base = current || editDraft;
      if (!base) {
        return current;
      }
      if (typeof update === "function") {
        return (update as (previous: ToolMetadataDraft) => ToolMetadataDraft)(base);
      }
      return update;
    });
  }

  function pushActionError(err: unknown, fallback: string) {
    const message =
      err instanceof ApiError && err.requestId
        ? `${err.message} Request ID: ${err.requestId}`
        : err instanceof Error
          ? err.message
          : fallback;
    setActionError(message);
  }

  async function loadToolDetail(toolId: string) {
    if (!token) {
      return;
    }
    setSelectedToolId(toolId);
    setDetailLoading(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const detail = await apiClient.getToolSafeDetail(token, toolId);
      setSelectedTool(detail);
      setEditDraft(isManagedToolType(detail.type) ? buildDraftFromDetail(detail) : null);
    } catch (err) {
      pushActionError(err, "The connector detail could not be loaded.");
    } finally {
      setDetailLoading(false);
    }
  }

  async function probeTool(toolId: string) {
    if (!token || !canManage) {
      return;
    }
    setBusyActionKey(`probe:${toolId}`);
    setActionMessage(null);
    setActionError(null);
    try {
      const updatedTool = await apiClient.probeToolHealth(token, toolId);
      setData((current) =>
        current ? current.map((item) => (item.id === toolId ? updatedTool : item)) : current,
      );
      if (selectedToolId === toolId) {
        await loadToolDetail(toolId);
      }
      setActionMessage(`Refreshed connector health for ${updatedTool.name}.`);
    } catch (err) {
      pushActionError(err, "The connector probe could not be completed.");
    } finally {
      setBusyActionKey(null);
    }
  }

  async function toggleTool(tool: ToolSafeSummary) {
    if (!token || !canManage) {
      return;
    }
    setBusyActionKey(`toggle:${tool.id}`);
    setActionMessage(null);
    setActionError(null);
    try {
      const updated = await apiClient.updateToolSafeMetadata(token, tool.id, { enabled: !tool.enabled });
      setData((current) =>
        current ? current.map((item) => (item.id === tool.id ? toToolSafeSummary(updated) : item)) : current,
      );
      if (selectedToolId === tool.id) {
        setSelectedTool(updated);
        setEditDraft(buildDraftFromDetail(updated));
      }
      setActionMessage(`${updated.name} is now ${updated.enabled ? "enabled" : "disabled"}.`);
    } catch (err) {
      pushActionError(err, "The connector state could not be updated.");
    } finally {
      setBusyActionKey(null);
    }
  }

  async function createTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !canManage) {
      return;
    }
    setBusyActionKey("create");
    setActionMessage(null);
    setActionError(null);
    try {
      const created = await apiClient.createToolSafeMetadata(token, buildCreatePayload(createDraft));
      setData((current) => [toToolSafeSummary(created), ...(current || []).filter((item) => item.id !== created.id)]);
      setSelectedToolId(created.id);
      setSelectedTool(created);
      setEditDraft(buildDraftFromDetail(created));
      setActionMessage(`Created safe metadata for ${created.name}. Configure secrets outside AgentGate before live use.`);
    } catch (err) {
      pushActionError(err, "The connector metadata could not be created.");
    } finally {
      setBusyActionKey(null);
    }
  }

  async function updateTool(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !canManage || !selectedToolId || !editDraft) {
      return;
    }
    setBusyActionKey(`save:${selectedToolId}`);
    setActionMessage(null);
    setActionError(null);
    try {
      const updated = await apiClient.updateToolSafeMetadata(token, selectedToolId, buildUpdatePayload(editDraft));
      setSelectedTool(updated);
      setEditDraft(buildDraftFromDetail(updated));
      setData((current) =>
        current ? current.map((item) => (item.id === updated.id ? toToolSafeSummary(updated) : item)) : current,
      );
      setActionMessage(`Saved safe metadata for ${updated.name}.`);
    } catch (err) {
      pushActionError(err, "The connector metadata could not be saved.");
    } finally {
      setBusyActionKey(null);
    }
  }

  if (!canView) {
    return (
      <PageShell
        title="Tools & Connectors"
        description="Safe connector posture and metadata management is limited to owner, admin, and security reviewer roles."
      >
        <Card>
          <p className="text-sm text-slate-600">
            This page summarizes tenant connector posture and now supports narrow metadata management for authorized
            operators. It remains restricted because even safe connector inventory can reveal operational integration
            shape.
          </p>
        </Card>
      </PageShell>
    );
  }

  const readyCount = (data || []).filter((item) => item.health_status === "ready").length;
  const degradedCount = (data || []).filter((item) => item.health_status !== "ready").length;
  const externalCount = (data || []).filter((item) => item.trust_domain && item.trust_domain !== "internal").length;
  const selectedTemplate = templateDefinitions.find((item) => item.id === selectedTemplateId) || templateDefinitions[0];
  const selectedToolCredentialReferences = selectedTool?.credential_references || [];
  const selectedToolValidationMessages = selectedTool?.validation_messages || [];
  const selectedToolSupportedAuthModes = selectedTool?.supported_auth_modes || [];

  return (
    <PageShell
      title="Tools & Connectors"
      description="Review connector posture, create or edit non-secret metadata, and validate GitHub-first pilot readiness without exposing token values, private keys, or raw Authorization headers."
      actions={
        <Button variant="ghost" onClick={() => setRefreshKey((current) => current + 1)} disabled={!token}>
          Refresh
        </Button>
      }
    >
      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">What this page does</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Safe connector posture and metadata control</h3>
          <p className="mt-2 text-sm text-slate-500">
            Use this page to understand which governed connectors exist, how narrowly they are scoped, whether their
            health posture is ready or degraded, and which non-secret metadata an owner or admin can safely manage from
            the browser.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Badge tone="ready">{readyCount} ready</Badge>
            <Badge tone={degradedCount ? "warning" : "ready"}>{degradedCount} need review</Badge>
            <Badge tone={externalCount ? "warning" : "ready"}>{externalCount} external or unknown trust</Badge>
          </div>
          {actionMessage ? <p className="mt-4 text-sm text-emerald-700">{actionMessage}</p> : null}
          {actionError ? <p className="mt-4 text-sm text-rose-700">{actionError}</p> : null}
        </Card>

        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Secret boundary</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Configure secrets outside AgentGate</h3>
          <div className="mt-3 space-y-3 text-sm text-slate-500">
            <p>This browser path accepts only connector metadata such as names, auth-mode labels, base URLs, and allowlists.</p>
            <p>It does not accept token values, private keys, auth emails, raw secret material, or Authorization headers.</p>
            <p>Review panels can show safe credential reference names such as env-var identifiers, but credential injection still stays in deployment config, environment wiring, or future secret-manager integrations.</p>
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              href="/settings"
              className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
            >
              Open settings
            </Link>
            <a
              href={`${apiBaseUrl}/docs#/tools`}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center justify-center rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-900"
            >
              Open tool API docs
            </a>
          </div>
        </Card>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.02fr_0.98fr]">
        <Card>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Templates</p>
              <h3 className="mt-3 text-xl font-semibold text-slate-950">Safe connector metadata templates</h3>
            </div>
            <Badge tone="low">{templateDefinitions.length} starter paths</Badge>
          </div>
          <p className="mt-3 text-sm text-slate-500">
            Start with a conservative template, then keep secrets external. GitHub is the strongest default first live
            connector. Jira is a narrower follow-on. MCP should stay disabled or internal-only unless tightly reviewed.
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {templateDefinitions.map((template) => (
              <button
                key={template.id}
                type="button"
                onClick={() => {
                  setSelectedTemplateId(template.id);
                  setCreateDraft(buildDraftFromTemplate(template.id));
                }}
                className={`rounded-2xl border px-4 py-4 text-left transition ${
                  selectedTemplateId === template.id
                    ? "border-slate-900 bg-slate-950 text-white"
                    : "border-slate-200 bg-white text-slate-900 hover:border-slate-400"
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-sm font-semibold">{template.title}</span>
                  <Badge tone={template.type === "mcp" ? "warning" : template.type === "jira" ? "medium" : "low"}>
                    {renderTypeLabel(template.type)}
                  </Badge>
                </div>
                <p className={`mt-2 text-xs ${selectedTemplateId === template.id ? "text-slate-200" : "text-slate-500"}`}>
                  {template.description}
                </p>
              </button>
            ))}
          </div>

          <form className="mt-6 grid gap-5" onSubmit={createTool}>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-slate-900">{selectedTemplate.title}</p>
                  <p className="mt-1 text-xs text-slate-500">{selectedTemplate.description}</p>
                </div>
                <Badge tone="low">{renderTypeLabel(selectedTemplate.type)}</Badge>
              </div>
              <p className="mt-3 text-xs text-slate-500">
                Docs: <code>{connectorGuides[selectedTemplate.type]?.path || "docs/operations/tool-management.md"}</code>
              </p>
            </div>

            <MetadataEditor
              draft={createDraft}
              setDraft={setCreateDraft}
              authModes={authModesByType[createDraft.type]}
              disabled={!canManage || busyActionKey !== null}
            />

            <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-4 text-xs text-slate-500">
              Secrets are not accepted here. After creating metadata, finish credential setup in deployment config or
              secret-manager wiring before expecting a live health check or real connector execution to succeed.
            </div>

            {canManage ? (
              <div className="flex flex-wrap gap-3">
                <Button type="submit" disabled={!token || busyActionKey !== null}>
                  {busyActionKey === "create" ? "Creating..." : "Create safe metadata"}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setCreateDraft(buildDraftFromTemplate(selectedTemplateId))}
                  disabled={busyActionKey !== null}
                >
                  Reset template
                </Button>
              </div>
            ) : (
              <p className="text-sm text-slate-500">Security reviewers can inspect connector posture here, but only owner and admin roles can create or update metadata.</p>
            )}
          </form>
        </Card>

        <Card>
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">
                {selectedTool ? "Selected connector" : "Review panel"}
              </p>
              <h3 className="mt-3 text-xl font-semibold text-slate-950">
                {selectedTool ? selectedTool.name : "Open a configured connector to review"}
              </h3>
            </div>
            {selectedTool ? <Badge tone={selectedTool.enabled ? "enabled" : "disabled"}>{selectedTool.enabled ? "enabled" : "disabled"}</Badge> : null}
          </div>

          {!selectedToolId ? (
            <div className="mt-6">
              <EmptyState
                title="Pick a connector from the inventory table"
                description="The review panel shows safe detail such as allowlists, auth-mode labels, trust hints, and GitHub readiness guidance without exposing token values or raw secret material."
              />
            </div>
          ) : detailLoading ? (
            <p className="mt-6 text-sm text-slate-500">Loading safe connector detail...</p>
          ) : selectedTool && editDraft ? (
            <form className="mt-6 grid gap-5" onSubmit={updateTool}>
              <div className="grid gap-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4 md:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Health</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone={selectedTool.health_status === "ready" ? "ready" : selectedTool.health_status}>
                      {renderLabel(selectedTool.health_status)}
                    </Badge>
                    <Badge tone={renderConnectorModeTone(selectedTool.connector_mode)}>
                      {renderConnectorModeLabel(selectedTool.connector_mode)}
                    </Badge>
                    <Badge tone="low">{renderAuthModeLabel(selectedTool.auth_mode)}</Badge>
                    {selectedTool.trust_domain ? <Badge tone={selectedTool.trust_domain === "internal" ? "ready" : "warning"}>{renderLabel(selectedTool.trust_domain)}</Badge> : null}
                    {selectedTool.type === "github" ? (
                      <Badge tone={selectedTool.live_execution_ready ? "ready" : "warning"}>
                        {selectedTool.live_execution_ready ? "live ready" : "live setup needed"}
                      </Badge>
                    ) : null}
                  </div>
                  {selectedTool.status_summary ? (
                    <p className="mt-3 text-sm text-slate-600">{selectedTool.status_summary}</p>
                  ) : null}
                </div>
                <div className="text-sm text-slate-500">
                  <p>Docs: <code>{selectedTool.documentation_path || connectorGuides[selectedTool.type]?.path || "docs/operations/tool-management.md"}</code></p>
                  <p className="mt-2">Supported actions: {formatActions(selectedTool.supported_actions)}</p>
                  <p className="mt-2">Updated {formatDate(selectedTool.updated_at)}</p>
                </div>
              </div>

              {selectedTool.type === "github" ? (
                <div className="grid gap-4 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">GitHub pilot readiness</p>
                    <h4 className="mt-2 text-lg font-semibold text-slate-950">Safe live-connector setup guidance</h4>
                    <p className="mt-2 text-sm text-slate-500">
                      Review whether this connector is still demo-safe only or whether live GitHub execution is ready after external credential wiring.
                    </p>
                  </div>

                  {selectedToolCredentialReferences.length ? (
                    <div className="grid gap-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Expected external credential wiring</p>
                      {selectedToolCredentialReferences.map((reference) => {
                        const state = renderCredentialReferenceState(reference);
                        return (
                          <div
                            key={`${selectedTool.id}-${reference.key}-${reference.reference_name || reference.reference_type || "external"}`}
                            className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
                          >
                            <div className="flex flex-wrap items-center justify-between gap-3">
                              <p className="text-sm font-semibold text-slate-900">{reference.label}</p>
                              <Badge tone={state.tone}>{state.label}</Badge>
                            </div>
                            <p className="mt-2 text-xs text-slate-500">
                              {reference.reference_name ? (
                                <>
                                  Reference name: <code>{renderCredentialReferenceSummary(reference)}</code>
                                </>
                              ) : (
                                renderCredentialReferenceSummary(reference)
                              )}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  ) : null}

                  {selectedToolValidationMessages.length ? (
                    <div className="grid gap-2">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Validation guidance</p>
                      {selectedToolValidationMessages.map((message) => (
                        <p key={`${selectedTool.id}-${message}`} className="text-sm text-slate-600">
                          {message}
                        </p>
                      ))}
                    </div>
                  ) : null}

                  <div className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Latest safe probe evidence</p>
                      <h5 className="mt-2 text-sm font-semibold text-slate-950">
                        {selectedTool.last_probe ? "Most recent connector probe" : "No connector probe history yet"}
                      </h5>
                    </div>
                    {selectedTool.last_probe ? (
                      <>
                        <div className="flex flex-wrap gap-2">
                          <Badge tone={selectedTool.last_probe.status === "ready" ? "ready" : selectedTool.last_probe.status}>
                            {renderLabel(selectedTool.last_probe.status)}
                          </Badge>
                          <Badge tone={selectedTool.last_probe.probe_performed ? "low" : "warning"}>
                            {selectedTool.last_probe.probe_performed ? "live call attempted" : "live call skipped"}
                          </Badge>
                          <Badge tone="low">{renderProbeSourceLabel(selectedTool.last_probe.source)}</Badge>
                        </div>
                        <div className="grid gap-1 text-sm text-slate-600">
                          <p>Checked {formatDate(selectedTool.last_probe.checked_at)}</p>
                          {selectedTool.last_probe.can_connect !== null ? (
                            <p>{selectedTool.last_probe.can_connect ? "Upstream connectivity succeeded during the latest probe." : "Upstream connectivity failed during the latest probe."}</p>
                          ) : (
                            <p>The latest probe did not attempt a live connector call.</p>
                          )}
                          {selectedTool.last_successful_probe_at ? (
                            <p>Last successful live probe: {formatDate(selectedTool.last_successful_probe_at)}</p>
                          ) : null}
                          {selectedTool.last_failed_probe_at ? (
                            <p>Last degraded or failed probe: {formatDate(selectedTool.last_failed_probe_at)}</p>
                          ) : null}
                          {selectedTool.last_failed_probe_error_summary ? (
                            <p className="text-amber-700">{selectedTool.last_failed_probe_error_summary}</p>
                          ) : selectedTool.last_probe.error_summary ? (
                            <p className="text-amber-700">{selectedTool.last_probe.error_summary}</p>
                          ) : null}
                        </div>
                      </>
                    ) : (
                      <p className="text-sm text-slate-500">
                        Run a health check or enable connector-health jobs to capture a safe timestamped readiness trail without exposing any credentials.
                      </p>
                    )}
                  </div>
                </div>
              ) : null}

              <MetadataEditor
                draft={editDraft}
                setDraft={setManagedEditDraft}
                authModes={selectedToolSupportedAuthModes.length ? selectedToolSupportedAuthModes : authModesByType[editDraft.type]}
                disabled={!canManage || busyActionKey !== null}
              />

              <div className="rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-4 text-xs text-slate-500">
                This editor updates metadata only. Existing secret bindings stay external. AgentGate can show safe
                credential reference names for operator guidance, but it still does not collect or reveal secret values.
              </div>

              <div className="flex flex-wrap gap-3">
                {canManage ? (
                  <>
                    <Button type="submit" disabled={!token || busyActionKey !== null}>
                      {busyActionKey === `save:${selectedTool.id}` ? "Saving..." : "Save safe metadata"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => toggleTool(selectedTool)}
                      disabled={!token || busyActionKey !== null}
                    >
                      {busyActionKey === `toggle:${selectedTool.id}`
                        ? "Updating..."
                        : selectedTool.enabled
                          ? "Disable connector"
                          : "Enable connector"}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => probeTool(selectedTool.id)}
                      disabled={!token || busyActionKey !== null}
                    >
                      {busyActionKey === `probe:${selectedTool.id}` ? "Checking..." : "Run health check"}
                    </Button>
                  </>
                ) : (
                  <p className="text-sm text-slate-500">View-only detail. Security reviewers can inspect metadata and health posture here, but mutation stays limited to owner and admin roles.</p>
                )}
              </div>
            </form>
          ) : (
            <p className="mt-6 text-sm text-slate-500">
              This tool type is visible for posture review, but browser metadata management is limited to GitHub, Jira,
              MCP, and mock connectors.
            </p>
          )}
        </Card>
      </div>

      <Card className="mt-6">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Inventory</p>
            <h3 className="mt-3 text-xl font-semibold text-slate-950">Configured tools and connectors</h3>
          </div>
          <Badge tone="low">{data?.length || 0} configured</Badge>
        </div>

        {loading ? (
          <p className="mt-6 text-sm text-slate-500">Loading tool posture...</p>
        ) : error ? (
          <p className="mt-6 text-sm text-rose-700">{error}</p>
        ) : !data?.length ? (
          <div className="mt-6">
            <EmptyState
              title="No tools configured yet"
              description="Use the safe template panel above to create narrow connector metadata, then finish external secret wiring before live use."
            />
          </div>
        ) : (
          <div className="mt-6">
            <Table>
              <TableHead>
                <tr>
                  <Th>Name</Th>
                  <Th>Type</Th>
                  <Th>Status</Th>
                  <Th>Auth & Trust</Th>
                  <Th>Scope</Th>
                  <Th>Supported Actions</Th>
                  <Th>Guidance</Th>
                </tr>
              </TableHead>
              <TableBody>
                {data.map((tool) => {
                  const guide = connectorGuides[tool.type];
                  const managedTool = isManagedToolType(tool.type);
                  return (
                    <tr key={tool.id}>
                      <Td>
                        <div className="font-medium text-slate-950">{tool.name}</div>
                        <div className="mt-1 text-xs text-slate-500">{tool.description || "No description provided."}</div>
                        <div className="mt-2 text-xs text-slate-500">
                          Host: {tool.base_url_host || "not applicable"} | Updated {formatDate(tool.updated_at)}
                        </div>
                      </Td>
                      <Td>
                        <Badge tone="low">{renderTypeLabel(tool.type)}</Badge>
                      </Td>
                      <Td>
                        <div className="flex flex-col gap-2">
                          <Badge tone={tool.health_status === "ready" ? "ready" : tool.health_status}>
                            {renderLabel(tool.health_status)}
                          </Badge>
                          <Badge tone={tool.enabled ? "enabled" : "disabled"}>
                            {tool.enabled ? "enabled" : "disabled"}
                          </Badge>
                          {tool.warning_flags.length ? (
                            <div className="text-xs text-slate-500">{tool.warning_flags.map(renderLabel).join(", ")}</div>
                          ) : null}
                        </div>
                      </Td>
                      <Td>
                        <div className="text-sm text-slate-900">{renderAuthModeLabel(tool.auth_mode)}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          Mode: {renderConnectorModeLabel(tool.connector_mode)}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Trust: {renderLabel(tool.trust_domain || "not_applicable")}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">
                          Probe: {tool.health_probe_performed ? (tool.health_can_connect ? "connected" : "failed") : "not run"}
                        </div>
                      </Td>
                      <Td>
                        <div className="text-sm text-slate-900">{formatAllowlistCounts(tool.allowlist_counts)}</div>
                      </Td>
                      <Td>
                        <div className="max-w-xs text-sm text-slate-900">{formatActions(tool.supported_actions)}</div>
                      </Td>
                      <Td>
                        <div className="space-y-2">
                          {tool.status_summary ? <p className="text-xs text-slate-500">{tool.status_summary}</p> : null}
                          <div className="text-xs text-slate-500">
                            {guide ? (
                              <>
                                <div className="font-semibold text-slate-700">{guide.label}</div>
                                <code>{guide.path}</code>
                              </>
                            ) : (
                              "No dedicated connector guide in this build."
                            )}
                          </div>
                          <Button
                            variant="ghost"
                            onClick={() => loadToolDetail(tool.id)}
                            disabled={!token || detailLoading || !managedTool}
                            className="w-full"
                          >
                            {!managedTool
                              ? "Summary only"
                              : selectedToolId === tool.id
                                ? "Reviewing"
                                : canManage
                                  ? "Edit safe metadata"
                                  : "Review metadata"}
                          </Button>
                          {canManage && managedTool ? (
                            <div className="grid gap-2">
                              <Button
                                variant="ghost"
                                onClick={() => toggleTool(tool)}
                                disabled={!token || busyActionKey !== null}
                                className="w-full"
                              >
                                {busyActionKey === `toggle:${tool.id}`
                                  ? "Updating..."
                                  : tool.enabled
                                    ? "Disable connector"
                                    : "Enable connector"}
                              </Button>
                              <Button
                                variant="ghost"
                                onClick={() => probeTool(tool.id)}
                                disabled={!token || busyActionKey !== null}
                                className="w-full"
                              >
                                {busyActionKey === `probe:${tool.id}` ? "Checking..." : "Run health check"}
                              </Button>
                            </div>
                          ) : (
                            <div className="text-xs text-slate-500">
                              {managedTool ? "View-only access" : "No browser metadata editor for this tool type"}
                            </div>
                          )}
                        </div>
                      </Td>
                    </tr>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </Card>
    </PageShell>
  );
}
