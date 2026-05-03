"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate, formatRisk } from "@/lib/utils";
import type { ToolCall } from "@/types/api";

function getArguments(call: ToolCall): Record<string, unknown> {
  const payload = call.request_payload;
  const candidate = payload?.arguments;
  if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
    return candidate as Record<string, unknown>;
  }
  return {};
}

function getConnectorContext(call: ToolCall): Record<string, unknown> {
  const payload = call.request_payload;
  const candidate = payload?.connector_context;
  if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
    return candidate as Record<string, unknown>;
  }
  return {};
}

function getGitHubTarget(call: ToolCall): string {
  const args = getArguments(call);
  const repository =
    typeof args.repository === "string"
      ? args.repository
      : typeof args.owner === "string" && typeof args.repo === "string"
        ? `${args.owner}/${args.repo}`
        : "";
  const numberValue = args.pull_number ?? args.number;
  const number =
    typeof numberValue === "number"
      ? numberValue
      : typeof numberValue === "string"
        ? Number(numberValue)
        : null;

  return [repository, Number.isFinite(number) ? `#${number}` : ""].filter(Boolean).join(" ");
}

function isGitHubCall(call: ToolCall): boolean {
  return (
    (typeof call.request_payload?.tool_type === "string" && call.request_payload.tool_type === "github") ||
    call.tool_name === "GitHub"
  );
}

function getToolSubtitle(call: ToolCall): string {
  if (!isGitHubCall(call)) {
    return call.action_name;
  }
  const target = getGitHubTarget(call);
  return [call.action_name, target].filter(Boolean).join(" - ");
}

function getRepoTrust(call: ToolCall): string {
  const connectorContext = getConnectorContext(call);
  return typeof connectorContext.repo_trust === "string" ? connectorContext.repo_trust : "";
}

function getSearchBlob(call: ToolCall): string {
  const args = getArguments(call);
  const repository = typeof args.repository === "string" ? args.repository : "";
  const repoTrust = getRepoTrust(call);
  return `${call.tool_name} ${call.action_name} ${call.decision_reason} ${repository} ${repoTrust}`.toLowerCase();
}

export default function ToolCallsPage() {
  const { token } = useSession();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");

  const queryString = statusFilter ? `?status=${statusFilter}` : "";
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.listToolCalls(token || "", queryString),
    [token, queryString],
    Boolean(token),
  );

  const filtered = (data || []).filter((call) => getSearchBlob(call).includes(search.toLowerCase()));

  return (
    <PageShell
      title="Tool Calls"
      description="Search runtime decisions across agents, tools, statuses, and risk scores."
    >
      <Card className="mb-6">
        <div className="grid gap-4 md:grid-cols-[1fr_220px]">
          <Input
            placeholder="Search by tool, action, repository, or reason"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="executed">Executed</option>
            <option value="blocked">Blocked</option>
            <option value="pending_approval">Pending approval</option>
            <option value="failed">Failed</option>
          </select>
        </div>
      </Card>

      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading tool calls...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>Tool</Th>
                <Th>Status</Th>
                <Th>Risk</Th>
                <Th>Decision</Th>
                <Th>Created</Th>
              </tr>
            </TableHead>
            <TableBody>
              {filtered.map((call) => (
                <tr key={call.id}>
                  <Td>
                    <div className="font-medium">{call.tool_name}</div>
                    <div className="text-xs text-slate-500">{getToolSubtitle(call)}</div>
                  </Td>
                  <Td><Badge tone={call.status}>{call.status}</Badge></Td>
                  <Td>{formatRisk(call.risk_score)}</Td>
                  <Td>
                    <div>{call.decision_reason}</div>
                    {getRepoTrust(call) ? (
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
                        Repo trust: {getRepoTrust(call)}
                      </div>
                    ) : null}
                    {call.payload_redaction_status ? (
                      <div className="text-xs uppercase tracking-[0.18em] text-slate-500">
                        Payload: {call.payload_redaction_status}
                      </div>
                    ) : null}
                  </Td>
                  <Td>{formatDate(call.created_at)}</Td>
                </tr>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </PageShell>
  );
}
