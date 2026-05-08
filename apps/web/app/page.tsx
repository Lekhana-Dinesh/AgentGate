"use client";

import Link from "next/link";

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
  const { token, user } = useSession();
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.getDashboardOverview(token || ""),
    [token],
    Boolean(token),
  );
  const canViewOnboarding = Boolean(
    token && user && ["owner", "admin", "security_reviewer"].includes(user.role),
  );
  const {
    data: onboarding,
    loading: onboardingLoading,
    error: onboardingError,
  } = useAuthedQuery(
    () => apiClient.getOnboardingStatus(token || ""),
    [token, user?.role],
    canViewOnboarding,
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

      {canViewOnboarding ? (
        <div className="mt-6">
          <Card>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">First-run status</p>
                <h3 className="mt-3 text-xl font-semibold text-slate-950">Onboarding</h3>
                <p className="mt-2 max-w-3xl text-sm text-slate-500">
                  Safe setup guidance for the next operator step. This does not create connectors, inject secrets, or replace the existing admin APIs.
                </p>
              </div>
              <Link
                href="/onboarding"
                className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
              >
                Open onboarding
              </Link>
            </div>

            {onboardingLoading ? (
              <p className="mt-5 text-sm text-slate-500">Loading onboarding readiness...</p>
            ) : onboarding ? (
              <div className="mt-5 grid gap-4 md:grid-cols-[1.15fr_0.85fr]">
                <div>
                  <p className="text-sm font-medium text-slate-950">Recommended next step</p>
                  <p className="mt-2 text-sm text-slate-600">{onboarding.recommended_next_step}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Badge tone={onboarding.dismissed ? "disabled" : "ready"}>
                      {onboarding.dismissed ? "dismissed" : "active"}
                    </Badge>
                    <Badge tone={onboarding.audit_integrity_status === "legacy_only" ? "warning" : "ready"}>
                      {onboarding.audit_integrity_status.replaceAll("_", " ")}
                    </Badge>
                  </div>
                </div>
                <div className="grid gap-3 sm:grid-cols-3 md:grid-cols-1">
                  <div>
                    <p className="text-sm text-slate-500">Agents</p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">{onboarding.agent_count}</p>
                  </div>
                  <div>
                    <p className="text-sm text-slate-500">Tools</p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">{onboarding.tool_count}</p>
                  </div>
                  <div>
                    <p className="text-sm text-slate-500">Policies</p>
                    <p className="mt-1 text-lg font-semibold text-slate-950">{onboarding.policy_count}</p>
                  </div>
                </div>
              </div>
            ) : onboardingError ? (
              <p className="mt-5 text-sm text-rose-700">{onboardingError}</p>
            ) : null}
          </Card>
        </div>
      ) : null}

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
