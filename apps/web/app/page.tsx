"use client";

import { StatCard } from "@/components/dashboard/stat-card";
import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function DashboardPage() {
  const { token } = useSession();
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.getDashboardOverview(token || ""),
    [token],
    Boolean(token),
  );

  const stats = data
    ? [
        { label: "Total Agents", value: data.total_agents, detail: "Registered agents under this tenant.", accent: "Registry" },
        { label: "Active Agents", value: data.active_agents, detail: "Agents currently authorized to operate.", accent: "Runtime" },
        { label: "Pending Approvals", value: data.pending_approvals, detail: "Human reviews waiting in the inbox.", accent: "Workflow" },
        { label: "Blocked Actions", value: data.blocked_actions, detail: "Runtime enforcement decisions already stopped.", accent: "Control" },
        { label: "High-Risk Calls", value: data.high_risk_tool_calls, detail: "Calls that crossed the high-risk threshold.", accent: "Risk" },
      ]
    : [];

  return (
    <PageShell
      title="Control Plane Overview"
      description="Track runtime decisions, high-risk actions, and reviewer workload across your agent fleet."
    >
      <div className="grid gap-5 xl:grid-cols-5">
        {stats.map((item) => (
          <StatCard
            key={item.label}
            label={item.label}
            value={item.value}
            detail={item.detail}
            accent={item.accent}
          />
        ))}
      </div>

      <div className="mt-6">
        <Card>
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-xl font-semibold text-slate-950">Recent Audit Events</h3>
              <p className="mt-1 text-sm text-slate-500">Most recent security-sensitive platform activity.</p>
            </div>
            {error ? <Badge tone="critical">Load issue</Badge> : null}
          </div>

          {loading ? (
            <p className="mt-8 text-sm text-slate-500">Loading runtime telemetry...</p>
          ) : data?.recent_audit_events.length ? (
            <div className="mt-6">
              <Table>
                <TableHead>
                  <tr>
                    <Th>Event</Th>
                    <Th>Actor</Th>
                    <Th>Resource</Th>
                    <Th>Timestamp</Th>
                  </tr>
                </TableHead>
                <TableBody>
                  {data.recent_audit_events.map((event) => (
                    <tr key={event.id}>
                      <Td>{event.event_type}</Td>
                      <Td>{event.actor_type}</Td>
                      <Td>
                        <div className="font-medium">{event.resource_type}</div>
                        <div className="mono text-xs text-slate-500">{event.resource_id}</div>
                      </Td>
                      <Td>{formatDate(event.created_at)}</Td>
                    </tr>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="mt-6">
              <EmptyState
                title="No audit events yet"
                description="Run the demo scenario or send tool calls through the gateway to populate the timeline."
              />
            </div>
          )}
        </Card>
      </div>
    </PageShell>
  );
}
