"use client";

import Link from "next/link";
import { useState } from "react";

import { StatCard } from "@/components/dashboard/stat-card";
import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { useSession } from "@/hooks/use-session";

function renderLabel(value: string | null | undefined): string {
  return (value || "unknown").replaceAll("_", " ");
}

function renderStatusTone(value: string | null | undefined): string {
  return value || "low";
}

export default function SettingsPage() {
  const { token, user } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.getSettingsOverview(token || ""),
    [token, refreshKey],
    Boolean(token),
  );

  return (
    <PageShell
      title="Settings"
      description="Review tenant-scoped configuration health, integration readiness, and operational links without exposing raw secrets, private keys, or unsafe config dumps."
      actions={
        <Button variant="ghost" onClick={() => setRefreshKey((current) => current + 1)} disabled={!token}>
          Refresh
        </Button>
      }
    >
      {loading ? <Card><p className="text-sm text-slate-500">Loading settings overview...</p></Card> : null}
      {error ? <Card><p className="text-sm text-rose-700">{error}</p></Card> : null}

      {data ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <StatCard
              label="OIDC / SSO"
              value={renderLabel(data.oidc.status)}
              detail={data.oidc.provider_name || "Local auth only"}
              accent={renderLabel(data.oidc.status)}
            />
            <StatCard
              label="GitHub Connectors"
              value={`${data.github_connectors.ready}/${data.github_connectors.total}`}
              detail="Connectors with credentials configured and no current health warnings."
              accent={renderLabel(data.github_connectors.status)}
            />
            <StatCard
              label="Audit Exports"
              value={`${data.audit_exports.enabled}/${data.audit_exports.total}`}
              detail="Enabled export destinations with safe credential and delivery status."
              accent={renderLabel(data.audit_exports.status)}
            />
            <StatCard
              label="Scheduled Tasks"
              value={`${data.scheduled_tasks.enabled}/${data.scheduled_tasks.total}`}
              detail={`${data.scheduled_tasks.due} task${data.scheduled_tasks.due === 1 ? "" : "s"} currently due.`}
              accent={renderLabel(data.scheduled_tasks.status)}
            />
            <StatCard
              label="Key Provider"
              value={data.keys.provider}
              detail={`Payload protection readiness: ${renderLabel(data.keys.readiness)}.`}
              accent={renderLabel(data.keys.readiness)}
            />
            <StatCard
              label="Rate Limiter"
              value={data.rate_limiter.provider}
              detail={`Backend status: ${renderLabel(data.rate_limiter.backend_status || data.rate_limiter.status)}.`}
              accent={renderLabel(data.rate_limiter.status)}
            />
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Tenant Profile</p>
              <h3 className="mt-3 text-xl font-semibold text-slate-950">{data.tenant.name}</h3>
              <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div>
                  <p className="text-sm text-slate-500">Slug</p>
                  <p className="mt-1 text-sm font-semibold text-slate-950">{data.tenant.slug}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Plan</p>
                  <p className="mt-1 text-sm font-semibold text-slate-950">{data.tenant.plan}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Users</p>
                  <p className="mt-1 text-sm font-semibold text-slate-950">
                    {data.tenant.active_user_count}/{data.tenant.user_count} active
                  </p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Inventory</p>
                  <p className="mt-1 text-sm font-semibold text-slate-950">
                    {data.tenant.agent_count} agents / {data.tenant.tool_count} tools
                  </p>
                </div>
              </div>
              <div className="mt-4 text-xs text-slate-500">
                Created {formatDate(data.tenant.created_at)}. Last updated {formatDate(data.tenant.updated_at)}.
              </div>
            </Card>

            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Operational Links</p>
              <h3 className="mt-3 text-xl font-semibold text-slate-950">Read-only status surface</h3>
              <p className="mt-2 text-sm text-slate-500">
                This page summarizes safe status only. Secret-backed changes still belong in environment injection, deployment config, or the narrower privileged APIs for each subsystem.
              </p>
              <p className="mt-2 text-sm text-slate-500">
                {user?.role === "owner" || user?.role === "admin"
                  ? "Owner and admin roles can jump from here into narrow non-secret controls for scheduled tasks, audit exports, and retention dry-runs."
                  : "Security reviewers can use these links for read-only operational review without exposing secrets."}
              </p>
              <div className="mt-5 flex flex-wrap gap-3">
                <Link
                  href="/tools"
                  className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
                >
                  Open tools
                </Link>
                <Link
                  href="/audit-exports"
                  className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
                >
                  Open audit exports
                </Link>
                <Link
                  href="/scheduled-tasks"
                  className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
                >
                  Open scheduled tasks
                </Link>
                <Link
                  href="/retention"
                  className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
                >
                  Open retention
                </Link>
                <a
                  href={data.links.readiness_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center justify-center rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-900"
                >
                  Open /ready
                </a>
                <a
                  href={data.links.metrics_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
                >
                  Open /metrics
                </a>
              </div>
            </Card>
          </div>

          <div className="mt-6 grid gap-6 xl:grid-cols-2">
            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Identity And Notifications</p>
              <div className="mt-4 space-y-4">
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-950">OIDC / SSO</p>
                    <p className="mt-1 text-sm text-slate-500">
                      {data.oidc.provider_name || "No provider configured"}.
                      {" "}Local auth {data.oidc.local_auth_enabled ? "remains enabled" : "is disabled"}.
                    </p>
                  </div>
                  <Badge tone={renderStatusTone(data.oidc.status)}>{renderLabel(data.oidc.status)}</Badge>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-950">Slack Notifications</p>
                    <p className="mt-1 text-sm text-slate-500">
                      {data.slack.enabled ? "Slack notifications are enabled." : "Slack notifications are disabled."}
                      {" "}Default channel: {data.slack.default_channel || "not configured"}.
                    </p>
                  </div>
                  <Badge tone={renderStatusTone(data.slack.status)}>{renderLabel(data.slack.status)}</Badge>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-950">Payload Protection Keys</p>
                    <p className="mt-1 text-sm text-slate-500">
                      Provider {data.keys.provider}. Active warnings: {data.keys.warnings.length}.
                    </p>
                  </div>
                  <Badge tone={renderStatusTone(data.keys.readiness)}>{renderLabel(data.keys.readiness)}</Badge>
                </div>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-medium text-slate-950">Rate Limiter</p>
                    <p className="mt-1 text-sm text-slate-500">
                      Provider {data.rate_limiter.provider}. Backend: {renderLabel(data.rate_limiter.backend_status || data.rate_limiter.status)}.
                    </p>
                  </div>
                  <Badge tone={renderStatusTone(data.rate_limiter.status)}>{renderLabel(data.rate_limiter.status)}</Badge>
                </div>
              </div>
            </Card>

            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Retention And Automation</p>
              <div className="mt-4 grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-sm font-medium text-slate-950">Retention Policy</p>
                  <p className="mt-2 text-sm text-slate-500">
                    Standard {data.retention.policy.standard_days}d, short-lived {data.retention.policy.short_lived_days}d, extended {data.retention.policy.extended_days}d.
                  </p>
                  <div className="mt-3 flex items-center gap-2">
                    <Badge tone={renderStatusTone(data.retention.status)}>{renderLabel(data.retention.status)}</Badge>
                    <span className="text-xs text-slate-500">
                      {data.retention.summary.failed} failed purge marker{data.retention.summary.failed === 1 ? "" : "s"}
                    </span>
                  </div>
                  <div className="mt-4">
                    <Link href="/retention" className="text-sm font-semibold text-signal hover:text-signal/80">
                      Open retention surface
                    </Link>
                  </div>
                </div>
                <div>
                  <p className="text-sm font-medium text-slate-950">Scheduled Tasks</p>
                  <p className="mt-2 text-sm text-slate-500">
                    {data.scheduled_tasks.enabled} enabled tasks across {Object.keys(data.scheduled_tasks.task_type_counts).length} task type{Object.keys(data.scheduled_tasks.task_type_counts).length === 1 ? "" : "s"}.
                  </p>
                  <div className="mt-3 flex items-center gap-2">
                    <Badge tone={renderStatusTone(data.scheduled_tasks.status)}>{renderLabel(data.scheduled_tasks.status)}</Badge>
                    <span className="text-xs text-slate-500">
                      {data.scheduled_tasks.due} due now
                    </span>
                  </div>
                  <div className="mt-4">
                    <Link href="/scheduled-tasks" className="text-sm font-semibold text-signal hover:text-signal/80">
                      Open scheduled tasks
                    </Link>
                  </div>
                </div>
              </div>
              <div className="mt-5 grid gap-4 md:grid-cols-3">
                <div>
                  <p className="text-sm text-slate-500">Eligible</p>
                  <p className="mt-1 text-lg font-semibold text-slate-950">{data.retention.summary.eligible}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Purged</p>
                  <p className="mt-1 text-lg font-semibold text-slate-950">{data.retention.summary.purged}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Legal Hold</p>
                  <p className="mt-1 text-lg font-semibold text-slate-950">{data.retention.summary.legal_hold}</p>
                </div>
              </div>
            </Card>
          </div>

          <Card className="mt-6">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">GitHub Connectors</p>
            {!data.github_connectors.connectors.length ? (
              <p className="mt-3 text-sm text-slate-500">No GitHub connectors are configured for this tenant.</p>
            ) : (
              <Table>
                <TableHead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Enabled</Th>
                    <Th>Status</Th>
                    <Th>Auth</Th>
                    <Th>Repository Scope</Th>
                    <Th>Updated</Th>
                  </tr>
                </TableHead>
                <TableBody>
                  {data.github_connectors.connectors.map((connector) => (
                    <tr key={connector.id}>
                      <Td>
                        <div className="font-medium text-slate-950">{connector.name}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          {connector.warnings[0] || "No warnings recorded."}
                        </div>
                      </Td>
                      <Td>
                        <Badge tone={connector.enabled ? "enabled" : "disabled"}>
                          {connector.enabled ? "enabled" : "disabled"}
                        </Badge>
                      </Td>
                      <Td>
                        <Badge tone={renderStatusTone(connector.status)}>{renderLabel(connector.status)}</Badge>
                      </Td>
                      <Td>{connector.auth_provider || "unknown"}</Td>
                      <Td>{connector.repository_allowlist_count} allowlisted repos</Td>
                      <Td>{formatDate(connector.updated_at)}</Td>
                    </tr>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>

          <Card className="mt-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Audit Exports</p>
              <Link href="/audit-exports" className="text-sm font-semibold text-signal hover:text-signal/80">
                Open audit exports
              </Link>
            </div>
            {!data.audit_exports.configs.length ? (
              <p className="mt-3 text-sm text-slate-500">No audit export destinations are configured for this tenant.</p>
            ) : (
              <Table>
                <TableHead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Destination</Th>
                    <Th>Enabled</Th>
                    <Th>Credential</Th>
                    <Th>Last Status</Th>
                    <Th>Updated</Th>
                  </tr>
                </TableHead>
                <TableBody>
                  {data.audit_exports.configs.map((config) => (
                    <tr key={config.id}>
                      <Td>
                        <div className="font-medium text-slate-950">{config.name}</div>
                        <div className="mt-1 text-xs text-slate-500">{config.endpoint_host || "No host"}</div>
                      </Td>
                      <Td>{config.destination_type}</Td>
                      <Td>
                        <Badge tone={config.enabled ? "enabled" : "disabled"}>
                          {config.enabled ? "enabled" : "disabled"}
                        </Badge>
                      </Td>
                      <Td>
                        <div className="text-sm text-slate-900">{renderLabel(config.credential_source)}</div>
                        <div className="mt-1 text-xs text-slate-500">{renderLabel(config.credential_status)}</div>
                      </Td>
                      <Td>
                        <div className="text-sm text-slate-900">
                          <Badge tone={renderStatusTone(config.last_export_status || "idle")}>
                            {renderLabel(config.last_export_status || "never_run")}
                          </Badge>
                        </div>
                        <div className="mt-1 text-xs text-slate-500">{config.last_error || "No error recorded."}</div>
                      </Td>
                      <Td>{formatDate(config.updated_at)}</Td>
                    </tr>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>

          <Card className="mt-6">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Scheduled Tasks</p>
              <Link href="/scheduled-tasks" className="text-sm font-semibold text-signal hover:text-signal/80">
                Open scheduled tasks
              </Link>
            </div>
            {!data.scheduled_tasks.tasks.length ? (
              <p className="mt-3 text-sm text-slate-500">No recurring scheduled tasks are configured for this tenant.</p>
            ) : (
              <Table>
                <TableHead>
                  <tr>
                    <Th>Name</Th>
                    <Th>Task Type</Th>
                    <Th>Enabled</Th>
                    <Th>Next Run</Th>
                    <Th>Last Status</Th>
                    <Th>Updated</Th>
                  </tr>
                </TableHead>
                <TableBody>
                  {data.scheduled_tasks.tasks.map((task) => (
                    <tr key={task.id}>
                      <Td>
                        <div className="font-medium text-slate-950">{task.name}</div>
                        <div className="mt-1 text-xs text-slate-500">{task.last_error || "No scheduler error recorded."}</div>
                      </Td>
                      <Td>{task.task_type.replaceAll("_", " ")}</Td>
                      <Td>
                        <Badge tone={task.enabled ? "enabled" : "disabled"}>
                          {task.enabled ? "enabled" : "disabled"}
                        </Badge>
                      </Td>
                      <Td>{formatDate(task.next_run_at)}</Td>
                      <Td>
                        <Badge tone={renderStatusTone(task.last_status || "idle")}>
                          {renderLabel(task.last_status || "never_run")}
                        </Badge>
                      </Td>
                      <Td>{formatDate(task.updated_at)}</Td>
                    </tr>
                  ))}
                </TableBody>
              </Table>
            )}
          </Card>

          <Card className="mt-6">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Rate Limit Scopes</p>
            <Table>
              <TableHead>
                <tr>
                  <Th>Scope</Th>
                  <Th>Enabled</Th>
                  <Th>Limit</Th>
                  <Th>Window</Th>
                  <Th>Backend Failure</Th>
                </tr>
              </TableHead>
              <TableBody>
                {data.rate_limiter.scopes.map((scope) => (
                  <tr key={scope.scope}>
                    <Td>{scope.scope.replaceAll("_", " ")}</Td>
                    <Td>
                      <Badge tone={scope.enabled ? "enabled" : "disabled"}>
                        {scope.enabled ? "enabled" : "disabled"}
                      </Badge>
                    </Td>
                    <Td>{scope.limit}</Td>
                    <Td>{scope.window_seconds}s</Td>
                    <Td>{scope.fail_closed_on_backend_error ? "fail closed" : "fail open"}</Td>
                  </tr>
                ))}
              </TableBody>
            </Table>
          </Card>
        </>
      ) : null}
    </PageShell>
  );
}
