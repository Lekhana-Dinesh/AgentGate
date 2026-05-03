"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { StatCard } from "@/components/dashboard/stat-card";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { RetentionPurgeResponse } from "@/types/api";

export default function RetentionPage() {
  const { token } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [limit, setLimit] = useState("100");
  const [active, setActive] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastRun, setLastRun] = useState<RetentionPurgeResponse | null>(null);
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.getRetentionStatus(token || ""),
    [token, refreshKey],
    Boolean(token),
  );

  async function handleDryRun() {
    if (!token) {
      return;
    }
    setActive(true);
    setActionError(null);
    try {
      const response = await apiClient.runRetentionPurge(token, {
        dry_run: true,
        limit: Math.max(1, Number(limit) || 100),
      });
      setLastRun(response);
      setRefreshKey((current) => current + 1);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Dry-run purge failed.";
      setActionError(message);
    } finally {
      setActive(false);
    }
  }

  return (
    <PageShell
      title="Retention"
      description="Preview protected payload purge eligibility and confirm that retention jobs are reducing sensitive execution state without exposing it."
      actions={
        <Button onClick={handleDryRun} disabled={active || !token}>
          {active ? "Running dry-run..." : "Run dry-run purge"}
        </Button>
      }
    >
      {loading ? <Card><p className="text-sm text-slate-500">Loading retention summary...</p></Card> : null}
      {error ? <Card><p className="text-sm text-rose-700">{error}</p></Card> : null}
      {actionError ? <Card><p className="text-sm text-rose-700">{actionError}</p></Card> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <StatCard
          label="Eligible"
          value={data?.eligible ?? 0}
          detail="Expired protected payloads ready for purge."
          accent="due"
        />
        <StatCard
          label="Protected Active"
          value={data?.protected_active ?? 0}
          detail="Protected payloads still inside their retention window."
          accent="active"
        />
        <StatCard
          label="Purged"
          value={data?.purged ?? 0}
          detail="Payloads already redacted from execution storage."
          accent="done"
        />
        <StatCard
          label="Legal Hold"
          value={data?.legal_hold ?? 0}
          detail="Payloads excluded from automatic purge."
          accent="hold"
        />
        <StatCard
          label="Failed"
          value={data?.failed ?? 0}
          detail="Payloads that need another purge attempt."
          accent="retry"
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Dry-Run Controls</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Preview retention impact</h3>
          <p className="mt-2 text-sm text-slate-500">
            The dashboard only exposes dry-run execution. Use the privileged API for real purge when you are ready.
          </p>
          <div className="mt-5 max-w-xs">
            <label className="mb-2 block text-sm font-medium text-slate-700">Candidate limit</label>
            <Input
              inputMode="numeric"
              value={limit}
              onChange={(event) => setLimit(event.target.value)}
              placeholder="100"
            />
          </div>
        </Card>

        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Latest Dry-Run</p>
          {!lastRun ? (
            <div className="mt-3 text-sm text-slate-500">
              No dry-run executed in this session yet.
            </div>
          ) : (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <p className="text-sm text-slate-500">Dispatch mode</p>
                <p className="mt-1 text-lg font-semibold text-slate-950">{lastRun.dispatch_mode}</p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Job status</p>
                <p className="mt-1 text-lg font-semibold text-slate-950">{lastRun.job.status}</p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Created</p>
                <p className="mt-1 text-sm text-slate-900">{formatDate(lastRun.job.created_at)}</p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Attempts</p>
                <p className="mt-1 text-sm text-slate-900">
                  {lastRun.job.attempts}/{lastRun.job.max_attempts}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Eligible</p>
                <p className="mt-1 text-lg font-semibold text-slate-950">
                  {lastRun.result?.eligible ?? "Queued"}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Already purged</p>
                <p className="mt-1 text-lg font-semibold text-slate-950">
                  {lastRun.result?.already_purged ?? "Queued"}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Skipped non-expired</p>
                <p className="mt-1 text-lg font-semibold text-slate-950">
                  {lastRun.result?.skipped_non_expired ?? "Queued"}
                </p>
              </div>
              <div>
                <p className="text-sm text-slate-500">Skipped legal hold</p>
                <p className="mt-1 text-lg font-semibold text-slate-950">
                  {lastRun.result?.skipped_legal_hold ?? "Queued"}
                </p>
              </div>
            </div>
          )}
        </Card>
      </div>
    </PageShell>
  );
}
