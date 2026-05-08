"use client";

import { FormEvent, useState } from "react";
import { useParams } from "next/navigation";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate, formatRisk } from "@/lib/utils";
import type { AgentAPIKeyResponse, AgentAPIKeySummary } from "@/types/api";

const DEFAULT_EXPIRY_DAYS = "90";
const MANAGED_EXPIRY_OPTIONS = [
  { label: "30 days", value: "30" },
  { label: "90 days", value: "90" },
  { label: "180 days", value: "180" },
  { label: "365 days", value: "365" },
];

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) {
    return false;
  }
  return new Date(expiresAt).getTime() <= Date.now();
}

function getKeyStatus(key: AgentAPIKeySummary): "active" | "expired" | "revoked" {
  if (key.revoked_at) {
    return "revoked";
  }
  if (isExpired(key.expires_at)) {
    return "expired";
  }
  return "active";
}

function getKeyWarnings(key: AgentAPIKeySummary): string[] {
  const warnings: string[] = [];
  if (!key.last_used_at) {
    warnings.push("Never used");
  }
  if (!key.expires_at) {
    warnings.push("No automatic expiry");
    return warnings;
  }
  const remainingMs = new Date(key.expires_at).getTime() - Date.now();
  const remainingDays = Math.ceil(remainingMs / (1000 * 60 * 60 * 24));
  if (remainingDays > 0 && remainingDays <= 7) {
    warnings.push(`Expires in ${remainingDays} day${remainingDays === 1 ? "" : "s"}`);
  }
  return warnings;
}

function toKeySummary(key: AgentAPIKeyResponse): AgentAPIKeySummary {
  return {
    id: key.id,
    name: key.name,
    prefix: key.prefix,
    created_at: key.created_at,
    created_by_user_id: key.created_by_user_id,
    scopes: key.scopes,
    expires_at: key.expires_at,
    last_used_at: key.last_used_at,
    revoked_at: key.revoked_at,
    is_active: key.is_active,
  };
}

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token, user } = useSession();
  const [createName, setCreateName] = useState("");
  const [expiresInDays, setExpiresInDays] = useState(DEFAULT_EXPIRY_DAYS);
  const [creating, setCreating] = useState(false);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [createdKey, setCreatedKey] = useState<AgentAPIKeyResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const agentQuery = useAuthedQuery(() => apiClient.getAgent(token || "", id), [token, id], Boolean(token));
  const toolCallsQuery = useAuthedQuery(
    () => apiClient.listToolCalls(token || "", `?agent_id=${id}`),
    [token, id],
    Boolean(token),
  );
  const auditQuery = useAuthedQuery(
    () => apiClient.listAuditEvents(token || "", `?agent_id=${id}`),
    [token, id],
    Boolean(token),
  );
  const agent = agentQuery.data;
  const canReviewApiKeys = Boolean(
    user &&
      agent &&
      (user.role === "owner" ||
        user.role === "admin" ||
        user.role === "security_reviewer" ||
        (user.role === "developer" && agent.owner_user_id === user.id)),
  );
  const canManageApiKeys = Boolean(
    user &&
      agent &&
      (user.role === "owner" || user.role === "admin" || (user.role === "developer" && agent.owner_user_id === user.id)),
  );
  const apiKeysQuery = useAuthedQuery(
    () => apiClient.listAgentApiKeys(token || "", id),
    [token, id, canReviewApiKeys],
    Boolean(token && canReviewApiKeys),
  );

  const auditEvents = auditQuery.data || [];
  const expiryOptions =
    user?.role === "owner" || user?.role === "admin"
      ? [...MANAGED_EXPIRY_OPTIONS, { label: "No automatic expiry", value: "never" }]
      : MANAGED_EXPIRY_OPTIONS;

  async function refreshApiKeys() {
    if (!token) {
      return;
    }
    const result = await apiClient.listAgentApiKeys(token, id);
    apiKeysQuery.setData(result);
  }

  async function handleCreateKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !canManageApiKeys) {
      return;
    }
    setCreating(true);
    setActionError(null);
    setActionMessage(null);
    setCopied(false);
    try {
      const created = await apiClient.createAgentApiKey(token, id, {
        name: createName.trim(),
        expires_in_days: expiresInDays === "never" ? null : Number(expiresInDays),
        scopes: ["gateway:invoke"],
      });
      setCreatedKey(created);
      apiKeysQuery.setData((current) => [toKeySummary(created), ...(current || []).filter((item) => item.id !== created.id)]);
      setCreateName("");
      setExpiresInDays(DEFAULT_EXPIRY_DAYS);
      setActionMessage("API key created. Copy the secret now: AgentGate will not show it again.");
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not create API key.");
    } finally {
      setCreating(false);
    }
  }

  async function handleCopyCreatedKey() {
    if (!createdKey?.api_key) {
      return;
    }
    if (!navigator?.clipboard?.writeText) {
      setActionError("Clipboard access is not available in this browser.");
      return;
    }
    await navigator.clipboard.writeText(createdKey.api_key);
    setCopied(true);
  }

  async function handleRevokeKey(key: AgentAPIKeySummary) {
    if (!token || !canManageApiKeys) {
      return;
    }
    if (!window.confirm(`Revoke API key "${key.name}"? Existing clients using this key will stop working immediately.`)) {
      return;
    }
    setRevokingId(key.id);
    setActionError(null);
    setActionMessage(null);
    try {
      await apiClient.revokeAgentApiKey(token, id, key.id);
      await refreshApiKeys();
      if (createdKey?.id === key.id) {
        setCreatedKey(null);
      }
      setActionMessage(`API key "${key.name}" revoked.`);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Could not revoke API key.");
    } finally {
      setRevokingId(null);
    }
  }

  return (
    <PageShell
      title={agent?.name || "Agent Detail"}
      description="Inspect agent scope, API key lifecycle, recent tool activity, and audit history for this runtime identity."
    >
      <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          {agent ? (
            <div className="space-y-5">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Profile</p>
                <h3 className="mt-2 text-2xl font-semibold text-slate-950">{agent.name}</h3>
                <p className="mt-2 text-sm text-slate-500">{agent.description || agent.purpose}</p>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Environment</p>
                  <p className="mt-2"><Badge tone={agent.environment}>{agent.environment}</Badge></p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Status</p>
                  <p className="mt-2"><Badge tone={agent.status}>{agent.status}</Badge></p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Risk Level</p>
                  <p className="mt-2"><Badge tone={agent.risk_level}>{agent.risk_level}</Badge></p>
                </div>
                <div>
                  <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Updated</p>
                  <p className="mt-2 text-sm text-slate-700">{formatDate(agent.updated_at)}</p>
                </div>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Allowed Tools</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {agent.allowed_tools.map((tool) => (
                    <Badge key={tool} tone="medium">{tool}</Badge>
                  ))}
                </div>
              </div>
              <div>
                <p className="text-xs uppercase tracking-[0.16em] text-slate-500">Allowed Data Classes</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {agent.allowed_data_classes.map((item) => (
                    <Badge key={item} tone="low">{item}</Badge>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-slate-500">Loading agent profile...</p>
          )}
        </Card>

        <div className="space-y-6">
          <Card>
            <div className="space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <h3 className="text-xl font-semibold text-slate-950">API Keys</h3>
                  <p className="mt-1 text-sm text-slate-500">
                    Review lifecycle status, one-time creation output, and revoke access without exposing stored secrets.
                  </p>
                </div>
                {canReviewApiKeys ? (
                  <Badge tone={canManageApiKeys ? "active" : "degraded"}>
                    {canManageApiKeys ? "Manage" : "Read only"}
                  </Badge>
                ) : null}
              </div>

              {actionMessage ? (
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">
                  {actionMessage}
                </div>
              ) : null}
              {actionError ? (
                <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
                  {actionError}
                </div>
              ) : null}

              {agentQuery.loading && !agent ? (
                <p className="text-sm text-slate-500">Loading API key access...</p>
              ) : !canReviewApiKeys ? (
                <EmptyState
                  title="API key lifecycle restricted"
                  description="Only owners, admins, security reviewers, and the owning developer can review this surface. Create and revoke actions stay limited to owners, admins, and the owning developer."
                />
              ) : (
                <>
                  <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                    API key secrets are shown only once at creation time. Later views return metadata only, and stored hashes remain backend-only.
                  </div>

                  {canManageApiKeys ? (
                    <form className="grid gap-4 rounded-2xl border border-slate-200 bg-white px-4 py-4 md:grid-cols-[1.5fr_1fr_auto]" onSubmit={handleCreateKey}>
                      <label className="space-y-2">
                        <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Key label</span>
                        <input
                          className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-signal"
                          maxLength={255}
                          minLength={2}
                          onChange={(event) => setCreateName(event.target.value)}
                          placeholder="CI deploy key"
                          required
                          value={createName}
                        />
                      </label>
                      <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-1">
                        <label className="space-y-2">
                          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Scope</span>
                          <div className="flex min-h-[52px] items-center rounded-2xl border border-slate-200 bg-slate-50 px-4 text-sm text-slate-700">
                            <Badge tone="medium">gateway:invoke</Badge>
                          </div>
                        </label>
                        <label className="space-y-2">
                          <span className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Expiry</span>
                          <select
                            className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-signal"
                            onChange={(event) => setExpiresInDays(event.target.value)}
                            value={expiresInDays}
                          >
                            {expiryOptions.map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </label>
                      </div>
                      <div className="flex items-end">
                        <Button className="w-full" disabled={creating || createName.trim().length < 2} type="submit">
                          {creating ? "Creating..." : "Create key"}
                        </Button>
                      </div>
                    </form>
                  ) : (
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
                      This is a read-only review surface. Only owners, admins, and the owning developer can create or revoke agent API keys.
                    </div>
                  )}

                  {createdKey ? (
                    <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-semibold text-slate-900">New API key for {createdKey.name}</p>
                          <p className="mt-1 text-sm text-slate-600">
                            Copy this secret now. AgentGate will not return it again after this response.
                          </p>
                        </div>
                        <div className="flex gap-2">
                          <Button onClick={handleCopyCreatedKey} type="button" variant="secondary">
                            {copied ? "Copied" : "Copy"}
                          </Button>
                          <Button onClick={() => setCreatedKey(null)} type="button" variant="ghost">
                            Dismiss
                          </Button>
                        </div>
                      </div>
                      <div className="mt-3 overflow-x-auto rounded-2xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-sm text-emerald-300">
                        {createdKey.api_key}
                      </div>
                    </div>
                  ) : null}

                  {apiKeysQuery.loading && !apiKeysQuery.data ? (
                    <p className="text-sm text-slate-500">Loading API keys...</p>
                  ) : apiKeysQuery.error ? (
                    <p className="text-sm text-rose-700">{apiKeysQuery.error}</p>
                  ) : apiKeysQuery.data?.length ? (
                    <Table>
                      <TableHead>
                        <tr>
                          <Th>Key</Th>
                          <Th>Status</Th>
                          <Th>Scope</Th>
                          <Th>Expires</Th>
                          <Th>Last used</Th>
                          <Th>Actions</Th>
                        </tr>
                      </TableHead>
                      <TableBody>
                        {apiKeysQuery.data.map((key) => {
                          const status = getKeyStatus(key);
                          const warnings = getKeyWarnings(key);
                          return (
                            <tr key={key.id}>
                              <Td>
                                <div className="font-medium text-slate-900">{key.name}</div>
                                <div className="mt-1 text-xs text-slate-500">Prefix {key.prefix}</div>
                                {warnings.length ? (
                                  <div className="mt-2 flex flex-wrap gap-2">
                                    {warnings.map((warning) => (
                                      <Badge key={warning} tone="warning">
                                        {warning}
                                      </Badge>
                                    ))}
                                  </div>
                                ) : null}
                              </Td>
                              <Td>
                                <Badge tone={status}>{status}</Badge>
                              </Td>
                              <Td>
                                <div className="flex flex-wrap gap-2">
                                  {key.scopes.map((scope) => (
                                    <Badge key={scope} tone="medium">
                                      {scope}
                                    </Badge>
                                  ))}
                                </div>
                              </Td>
                              <Td>
                                <div className="text-sm text-slate-700">
                                  {key.expires_at ? formatDate(key.expires_at) : "No automatic expiry"}
                                </div>
                                {key.revoked_at ? (
                                  <div className="mt-1 text-xs text-slate-500">Revoked {formatDate(key.revoked_at)}</div>
                                ) : null}
                              </Td>
                              <Td>{key.last_used_at ? formatDate(key.last_used_at) : "Never"}</Td>
                              <Td>
                                {canManageApiKeys ? (
                                  key.revoked_at ? (
                                    <span className="text-xs text-slate-500">Already revoked</span>
                                  ) : (
                                    <Button
                                      disabled={revokingId === key.id}
                                      onClick={() => void handleRevokeKey(key)}
                                      variant="danger"
                                    >
                                      {revokingId === key.id ? "Revoking..." : "Revoke"}
                                    </Button>
                                  )
                                ) : (
                                  <span className="text-xs text-slate-500">Read only</span>
                                )}
                              </Td>
                            </tr>
                          );
                        })}
                      </TableBody>
                    </Table>
                  ) : (
                    <EmptyState
                      title="No API keys for this agent"
                      description="Create a short-lived gateway key when an integration needs machine access. The raw secret will be shown once and cannot be recovered later."
                    />
                  )}
                </>
              )}
            </div>
          </Card>

          <Card>
            <h3 className="text-xl font-semibold text-slate-950">Recent Tool Calls</h3>
            <div className="mt-4">
              <Table>
                <TableHead>
                  <tr>
                    <Th>Tool</Th>
                    <Th>Status</Th>
                    <Th>Risk</Th>
                    <Th>Reason</Th>
                  </tr>
                </TableHead>
                <TableBody>
                  {(toolCallsQuery.data || []).slice(0, 8).map((call) => (
                    <tr key={call.id}>
                      <Td>
                        <div className="font-medium">{call.tool_name}</div>
                        <div className="text-xs text-slate-500">{call.action_name}</div>
                      </Td>
                      <Td><Badge tone={call.status}>{call.status}</Badge></Td>
                      <Td>{formatRisk(call.risk_score)}</Td>
                      <Td>{call.decision_reason}</Td>
                    </tr>
                  ))}
                </TableBody>
              </Table>
            </div>
          </Card>

          <Card>
            <h3 className="text-xl font-semibold text-slate-950">Audit Events</h3>
            <div className="mt-4 space-y-3">
              {auditEvents.slice(0, 8).map((event) => (
                <div key={event.id} className="rounded-2xl border border-slate-200 bg-white px-4 py-4">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="font-medium text-slate-900">{event.event_type}</p>
                      <p className="mt-1 text-sm text-slate-500">{event.resource_type}</p>
                    </div>
                    <span className="text-xs text-slate-500">{formatDate(event.created_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </PageShell>
  );
}
