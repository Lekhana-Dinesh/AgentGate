"use client";

import { useState } from "react";

import { StatCard } from "@/components/dashboard/stat-card";
import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type {
  AuditIntegrityCheckpointRecord,
  AuditIntegrityCheckpointRunResponse,
  AuditIntegrityVerifyResponse,
} from "@/types/api";

export default function AuditIntegrityPage() {
  const { token } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [verification, setVerification] = useState<AuditIntegrityVerifyResponse | null>(null);
  const [checkpointRun, setCheckpointRun] = useState<AuditIntegrityCheckpointRunResponse | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [creatingCheckpoint, setCreatingCheckpoint] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.getAuditIntegrityStatus(token || ""),
    [token, refreshKey],
    Boolean(token),
  );
  const {
    data: checkpoints,
    loading: checkpointsLoading,
    error: checkpointsError,
  } = useAuthedQuery(
    () => apiClient.listAuditIntegrityCheckpoints(token || ""),
    [token, refreshKey],
    Boolean(token),
  );
  const latestCheckpoint: AuditIntegrityCheckpointRecord | null = checkpoints?.[0] ?? null;

  async function handleVerify() {
    if (!token) {
      return;
    }
    setVerifying(true);
    setActionError(null);
    try {
      const result = await apiClient.verifyAuditIntegrity(token);
      setVerification(result);
      setRefreshKey((current) => current + 1);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Integrity verification failed.";
      setActionError(message);
    } finally {
      setVerifying(false);
    }
  }

  async function handleCreateCheckpoint() {
    if (!token) {
      return;
    }
    setCreatingCheckpoint(true);
    setActionError(null);
    try {
      const result = await apiClient.createAuditIntegrityCheckpoint(token);
      setCheckpointRun(result);
      setRefreshKey((current) => current + 1);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Checkpoint creation failed.";
      setActionError(message);
    } finally {
      setCreatingCheckpoint(false);
    }
  }

  return (
    <PageShell
      title="Audit Integrity"
      description="Confirm the tenant-scoped audit hash chain is present, inspect the latest chain and checkpoint state, and run safe verification without exposing sensitive event content."
      actions={
        <>
          <Button
            variant="ghost"
            onClick={() => setRefreshKey((current) => current + 1)}
            disabled={!token || verifying || creatingCheckpoint}
          >
            Refresh
          </Button>
          <Button onClick={handleCreateCheckpoint} disabled={!token || verifying || creatingCheckpoint}>
            {creatingCheckpoint ? "Creating checkpoint..." : "Create checkpoint"}
          </Button>
          <Button onClick={handleVerify} disabled={!token || verifying || creatingCheckpoint}>
            {verifying ? "Verifying..." : "Run verification"}
          </Button>
        </>
      }
    >
      {loading || checkpointsLoading ? <Card><p className="text-sm text-slate-500">Loading audit integrity status...</p></Card> : null}
      {error ? <Card><p className="text-sm text-rose-700">{error}</p></Card> : null}
      {checkpointsError ? <Card><p className="text-sm text-rose-700">{checkpointsError}</p></Card> : null}
      {actionError ? <Card><p className="text-sm text-rose-700">{actionError}</p></Card> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-7">
        <StatCard
          label="Chain status"
          value={data?.status ?? "unknown"}
          detail="Current tenant-scoped audit chain state."
          accent="integrity"
        />
        <StatCard
          label="Total events"
          value={data?.total_events ?? 0}
          detail="Sanitized audit events tracked for this tenant."
          accent="events"
        />
        <StatCard
          label="Anchored events"
          value={data?.anchored_events ?? 0}
          detail="Events already linked into the tamper-evident chain."
          accent="anchored"
        />
        <StatCard
          label="Legacy events"
          value={data?.legacy_unanchored_events ?? 0}
          detail="Older events that predate current chain anchoring."
          accent="legacy"
        />
        <StatCard
          label="Latest sequence"
          value={data?.latest_sequence_number ?? "none"}
          detail="Most recent anchored sequence number."
          accent="sequence"
        />
        <StatCard
          label="Checkpoints"
          value={checkpoints?.length ?? 0}
          detail="Stored checkpoint records for this tenant."
          accent="events"
        />
        <StatCard
          label="Latest checkpoint"
          value={latestCheckpoint?.status ?? "none"}
          detail="Most recent checkpoint outcome."
          accent="anchored"
        />
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Chain Metadata</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Current audit-chain posture</h3>
          <div className="mt-5 grid gap-4">
            <div>
              <p className="text-sm text-slate-500">Scope</p>
              <p className="mt-1 text-sm font-medium text-slate-950">{data?.chain_scope || "Unavailable"}</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Hash algorithm</p>
              <p className="mt-1 text-sm font-medium text-slate-950">{data?.hash_algorithm || "Unavailable"}</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Latest event ID</p>
              <p className="mt-1 break-all text-sm font-medium text-slate-950">
                {data?.latest_event_id || "No anchored event yet"}
              </p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Latest anchored at</p>
              <p className="mt-1 text-sm font-medium text-slate-950">{formatDate(data?.latest_anchored_at)}</p>
            </div>
            <div>
              <p className="text-sm text-slate-500">Latest checkpoint at</p>
              <p className="mt-1 text-sm font-medium text-slate-950">{formatDate(latestCheckpoint?.anchored_at)}</p>
            </div>
          </div>
        </Card>

        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Checkpoint Snapshot</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Latest external anchor state</h3>
          {!latestCheckpoint ? (
            <div className="mt-3 text-sm text-slate-500">
              No checkpoint has been anchored for this tenant yet.
            </div>
          ) : (
            <div className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={latestCheckpoint.status === "anchored" ? "active" : "critical"}>
                  {latestCheckpoint.status}
                </Badge>
                <span className="text-sm text-slate-500">
                  {latestCheckpoint.event_count} event
                  {latestCheckpoint.event_count === 1 ? "" : "s"}
                </span>
                <Badge tone="low">{latestCheckpoint.checkpoint_type.replaceAll("_", " ")}</Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-sm text-slate-500">Range</p>
                  <p className="mt-1 text-sm font-medium text-slate-950">
                    {latestCheckpoint.from_sequence_number} to {latestCheckpoint.to_sequence_number}
                  </p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Anchored at</p>
                  <p className="mt-1 text-sm font-medium text-slate-950">
                    {formatDate(latestCheckpoint.anchored_at)}
                  </p>
                </div>
              </div>
              <div>
                <p className="text-sm text-slate-500">Checkpoint hash</p>
                <p className="mt-1 break-all text-sm font-medium text-slate-950">
                  {latestCheckpoint.checkpoint_hash || "Unavailable"}
                </p>
              </div>
            </div>
          )}
          {checkpointRun?.result?.status === "no_new_events" ? (
            <p className="mt-4 text-sm text-slate-500">
              No newly anchored audit events were available for a fresh checkpoint.
            </p>
          ) : null}
        </Card>
      </div>

      <div className="mt-6">
        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Latest Verification</p>
          {!verification ? (
            <div className="mt-3 text-sm text-slate-500">
              No manual verification has been run in this browser session yet.
            </div>
          ) : (
            <div className="mt-4 space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <Badge tone={verification.chain_valid ? "active" : "critical"}>
                  {verification.chain_valid ? "chain valid" : "chain broken"}
                </Badge>
                <span className="text-sm text-slate-500">
                  {verification.verified_events} verified event
                  {verification.verified_events === 1 ? "" : "s"}
                </span>
                {verification.boundary_limited ? (
                  <Badge tone="high">boundary limited</Badge>
                ) : null}
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div>
                  <p className="text-sm text-slate-500">Verification status</p>
                  <p className="mt-1 text-sm font-medium text-slate-950">{verification.status}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Latest sequence</p>
                  <p className="mt-1 text-sm font-medium text-slate-950">
                    {verification.latest_sequence_number ?? "Unavailable"}
                  </p>
                </div>
              </div>
              <div>
                <p className="text-sm text-slate-500">Issues</p>
                {!verification.issues.length ? (
                  <p className="mt-1 text-sm font-medium text-emerald-700">No integrity issues reported.</p>
                ) : (
                  <div className="mt-2 space-y-2">
                    {verification.issues.map((issue, index) => (
                      <div key={`${issue.code}-${index}`} className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3">
                        <p className="text-sm font-semibold text-rose-800">{issue.code}</p>
                        <p className="mt-1 text-sm text-rose-700">{issue.detail}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>
      </div>
    </PageShell>
  );
}
