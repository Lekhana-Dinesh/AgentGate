"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { ScheduledTask, ScheduledTaskRunResponse } from "@/types/api";

function describeSchedule(task: ScheduledTask): string {
  if (task.schedule_kind === "interval") {
    return `${task.interval_seconds ?? 0}s interval`;
  }
  return task.cron_expression || "Cron";
}

export default function ScheduledTasksPage() {
  const { token, user } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [lastRunByTask, setLastRunByTask] = useState<Record<string, ScheduledTaskRunResponse>>({});
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listScheduledTasks(token || ""),
    [token, refreshKey],
    Boolean(token),
  );
  const canManageTasks = user?.role === "owner" || user?.role === "admin";
  const isReadOnlyReviewer = user?.role === "security_reviewer";

  async function handleRunNow(taskId: string) {
    if (!token || !canManageTasks) {
      return;
    }
    setActionError(null);
    setActionMessage(null);
    setActiveKey(`run:${taskId}`);
    try {
      const response = await apiClient.runScheduledTaskNow(token, taskId);
      setLastRunByTask((current) => ({ ...current, [taskId]: response }));
      setRefreshKey((current) => current + 1);
      setActionMessage("Scheduled task queued through the normal durable job path.");
    } catch (err) {
      setActionError(
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Scheduled task run failed.",
      );
    } finally {
      setActiveKey(null);
    }
  }

  async function handleToggle(task: ScheduledTask) {
    if (!token || !canManageTasks) {
      return;
    }
    setActionError(null);
    setActionMessage(null);
    setActiveKey(`toggle:${task.id}`);
    try {
      const updated = await apiClient.updateScheduledTask(token, task.id, { enabled: !task.enabled });
      setData((current) => current?.map((item) => (item.id === updated.id ? updated : item)) || []);
      setActionMessage(`Scheduled task "${task.name}" ${updated.enabled ? "enabled" : "disabled"}.`);
    } catch (err) {
      setActionError(
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Scheduled task update failed.",
      );
    } finally {
      setActiveKey(null);
    }
  }

  return (
    <PageShell
      title="Scheduled Tasks"
      description="Watch tenant-scoped recurring controls enqueue durable jobs without relying on external cron for local and smaller self-hosted deployments."
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
      {actionMessage ? (
        <Card className="mb-6">
          <p className="text-sm text-emerald-700">{actionMessage}</p>
        </Card>
      ) : null}

      <Card className="mb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Operator Notes</p>
            <h3 className="mt-3 text-xl font-semibold text-slate-950">Recurring enqueue only</h3>
            <p className="mt-2 text-sm text-slate-500">
              These schedules enqueue existing durable jobs. They do not store connector secrets, and they do not replace an external orchestrator when you need stronger fleet-level coordination.
            </p>
            <p className="mt-2 text-sm text-slate-500">
              Owner and admin roles can enable, disable, or run a task immediately. Security reviewers stay read-only on this page.
            </p>
          </div>
          {user ? <Badge tone={canManageTasks ? "active" : "degraded"}>{canManageTasks ? "Manage" : "Read only"}</Badge> : null}
        </div>
      </Card>

      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading scheduled tasks...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : !data?.length ? (
          <div className="space-y-2 text-sm text-slate-500">
            <p>No scheduled tasks are configured for this tenant yet.</p>
            <p>Use the `POST /v1/scheduled-tasks` API to create recurring retention, export, integrity, or connector health tasks.</p>
          </div>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>Name</Th>
                <Th>Task Type</Th>
                <Th>Enabled</Th>
                <Th>Schedule</Th>
                <Th>Next Run</Th>
                <Th>Last Status</Th>
                <Th>Actions</Th>
              </tr>
            </TableHead>
            <TableBody>
              {data.map((task) => {
                const lastRun = lastRunByTask[task.id];
                const runKey = `run:${task.id}`;
                const toggleKey = `toggle:${task.id}`;
                return (
                  <tr key={task.id}>
                    <Td>
                      <div className="font-medium text-slate-950">{task.name}</div>
                      <div className="mt-1 text-xs text-slate-500">{task.idempotency_key}</div>
                    </Td>
                    <Td>
                      <Badge tone="low">{task.task_type.replaceAll("_", " ")}</Badge>
                    </Td>
                    <Td>
                      <Badge tone={task.enabled ? "enabled" : "disabled"}>
                        {task.enabled ? "enabled" : "disabled"}
                      </Badge>
                    </Td>
                    <Td>{describeSchedule(task)}</Td>
                    <Td>
                      <div className="text-sm text-slate-900">{formatDate(task.next_run_at)}</div>
                      <div className="mt-1 text-xs text-slate-500">
                        Last run {task.last_run_at ? formatDate(task.last_run_at) : "not recorded yet"}
                      </div>
                    </Td>
                    <Td>
                      <div className="text-sm text-slate-900">
                        {task.last_status ? <Badge tone={task.last_status}>{task.last_status}</Badge> : "Never run"}
                      </div>
                      <div className="mt-1 max-w-xs text-xs text-slate-500">
                        {task.last_error || lastRun?.job.last_error || "No scheduler error recorded."}
                      </div>
                    </Td>
                    <Td>
                      {canManageTasks ? (
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="secondary"
                            onClick={() => void handleToggle(task)}
                            disabled={activeKey !== null}
                          >
                            {activeKey === toggleKey
                              ? "Saving..."
                              : task.enabled
                                ? "Disable"
                                : "Enable"}
                          </Button>
                          <Button
                            onClick={() => void handleRunNow(task.id)}
                            disabled={activeKey !== null}
                          >
                            {activeKey === runKey ? "Running..." : "Run now"}
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-slate-500">
                          {isReadOnlyReviewer ? "Review only" : "No access"}
                        </span>
                      )}
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
