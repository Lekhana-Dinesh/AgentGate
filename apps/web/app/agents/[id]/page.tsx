"use client";

import { useParams } from "next/navigation";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate, formatRisk } from "@/lib/utils";

export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useSession();
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
  const auditEvents = auditQuery.data || [];

  return (
    <PageShell
      title={agent?.name || "Agent Detail"}
      description="Inspect agent scope, recent tool activity, and audit history for this runtime identity."
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
