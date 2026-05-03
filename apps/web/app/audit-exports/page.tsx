"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { useSession } from "@/hooks/use-session";
import type { AuditExportRunResponse } from "@/types/api";

export default function AuditExportsPage() {
  const { token } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeConfigId, setActiveConfigId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastRunByConfig, setLastRunByConfig] = useState<Record<string, AuditExportRunResponse>>({});
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.listAuditExports(token || ""),
    [token, refreshKey],
    Boolean(token),
  );

  async function handleRun(configId: string, dryRun: boolean) {
    if (!token) {
      return;
    }
    setActionError(null);
    setActiveConfigId(`${configId}:${dryRun ? "dry-run" : "run"}`);
    try {
      const response = await apiClient.runAuditExport(token, configId, { dry_run: dryRun });
      setLastRunByConfig((current) => ({ ...current, [configId]: response }));
      setRefreshKey((current) => current + 1);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Audit export run failed.";
      setActionError(message);
    } finally {
      setActiveConfigId(null);
    }
  }

  return (
    <PageShell
      title="Audit Exports"
      description="Track tenant-scoped SIEM export configurations, confirm their last delivery state, and manually trigger sanitized audit exports through the async jobs layer."
      actions={
        <Button variant="ghost" onClick={() => setRefreshKey((current) => current + 1)} disabled={!token}>
          Refresh
        </Button>
      }
    >
      {actionError ? (
        <Card className="mb-6">
          <p className="text-sm text-rose-700">{actionError}</p>
        </Card>
      ) : null}

      <Card className="mb-6">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Operator Notes</p>
        <h3 className="mt-3 text-xl font-semibold text-slate-950">Sanitized export visibility only</h3>
        <p className="mt-2 text-sm text-slate-500">
          Secrets never appear here. Use the privileged API to create or update destinations; the dashboard focuses on enablement, last result, and safe manual runs.
        </p>
      </Card>

      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading audit export configs...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : !data?.length ? (
          <div className="space-y-2 text-sm text-slate-500">
            <p>No audit export configs are set up for this tenant yet.</p>
            <p>Use the `POST /v1/audit-exports` API to create a destination without exposing tokens in the UI.</p>
          </div>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>Name</Th>
                <Th>Destination</Th>
                <Th>Enabled</Th>
                <Th>Credential</Th>
                <Th>Last Status</Th>
                <Th>Last Exported</Th>
                <Th>Actions</Th>
              </tr>
            </TableHead>
            <TableBody>
              {data.map((config) => {
                const lastRun = lastRunByConfig[config.id];
                const runKey = `${config.id}:run`;
                const dryRunKey = `${config.id}:dry-run`;
                return (
                  <tr key={config.id}>
                    <Td>
                      <div className="font-medium text-slate-950">{config.name}</div>
                      <div className="mt-1 text-xs text-slate-500">{config.endpoint_url}</div>
                    </Td>
                    <Td>
                      <Badge tone="low">{config.destination_type}</Badge>
                    </Td>
                    <Td>
                      <Badge tone={config.enabled ? "active" : "cancelled"}>
                        {config.enabled ? "enabled" : "disabled"}
                      </Badge>
                    </Td>
                    <Td>
                      <div className="text-sm text-slate-900">{config.credential_source.replace(/_/g, " ")}</div>
                      <div className="mt-1 text-xs text-slate-500">{config.credential_status}</div>
                    </Td>
                    <Td>
                      <div className="text-sm text-slate-900">
                        {config.last_export_status ? (
                          <Badge tone={config.last_export_status}>{config.last_export_status}</Badge>
                        ) : (
                          "Never run"
                        )}
                      </div>
                      <div className="mt-1 max-w-xs text-xs text-slate-500">
                        {config.last_error || lastRun?.job.last_error || "No failure recorded."}
                      </div>
                    </Td>
                    <Td>
                      <div className="text-sm text-slate-900">{formatDate(config.last_exported_at)}</div>
                      {lastRun?.result ? (
                        <div className="mt-1 text-xs text-slate-500">
                          {lastRun.result.exported_events} events in {lastRun.result.batches_processed} batch
                          {lastRun.result.batches_processed === 1 ? "" : "es"}
                        </div>
                      ) : null}
                    </Td>
                    <Td>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          onClick={() => void handleRun(config.id, true)}
                          disabled={!config.enabled || activeConfigId !== null}
                        >
                          {activeConfigId === dryRunKey ? "Running..." : "Dry-run"}
                        </Button>
                        <Button
                          onClick={() => void handleRun(config.id, false)}
                          disabled={!config.enabled || activeConfigId !== null}
                        >
                          {activeConfigId === runKey ? "Running..." : "Run export"}
                        </Button>
                      </div>
                    </Td>
                  </tr>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>
    </PageShell>
  );
}
