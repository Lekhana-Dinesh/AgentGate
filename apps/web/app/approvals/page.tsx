"use client";

import { useEffect, useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate, formatRisk } from "@/lib/utils";

function formatNotificationStatus(status: string | undefined) {
  switch (status) {
    case "queued":
      return "Slack notification queued";
    case "running":
      return "Slack notification in progress";
    case "sent":
      return "Slack notification sent";
    case "failed":
      return "Slack notification failed";
    case "retry_exhausted":
      return "Slack notification retries exhausted";
    case "cancelled":
      return "Slack notification cancelled";
    case "unconfigured":
      return "Slack notification unavailable";
    case "not_attempted":
      return "Slack notification not attempted";
    case "disabled":
      return "Slack notifications disabled";
    default:
      return "Slack notification status unknown";
  }
}

function formatExecutionStatus(status: string | undefined) {
  switch (status) {
    case "queued":
      return "Approved execution queued";
    case "running":
      return "Approved execution running";
    case "succeeded":
      return "Approved execution completed";
    case "failed":
      return "Approved execution failed";
    case "retry_exhausted":
      return "Approved execution retries exhausted";
    case "cancelled":
      return "Approved execution cancelled";
    case "not_requested":
      return "Execution not requested";
    default:
      return "Execution status unavailable";
  }
}

export default function ApprovalsPage() {
  const { token } = useSession();
  const [statusFilter, setStatusFilter] = useState("pending");
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listApprovals(token || "", statusFilter === "all" ? "" : `?status=${statusFilter}`),
    [token, statusFilter],
    Boolean(token),
  );
  const [comments, setComments] = useState<Record<string, string>>({});
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeApprovalId, setActiveApprovalId] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const status = new URLSearchParams(window.location.search).get("status");
    if (status === "approved" || status === "rejected" || status === "pending") {
      setStatusFilter(status);
    }
  }, []);

  async function handleApprove(id: string) {
    if (!token) {
      return;
    }
    setActiveApprovalId(id);
    setActionError(null);
    try {
      const updated = await apiClient.approveRequest(token, id, comments[id] || "Approved by reviewer.", true);
      setData((current) => current?.map((item) => (item.id === id ? updated : item)) || [updated]);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Approval failed.";
      setActionError(message);
    } finally {
      setActiveApprovalId(null);
    }
  }

  async function handleReject(id: string) {
    if (!token) {
      return;
    }
    setActiveApprovalId(id);
    setActionError(null);
    try {
      const updated = await apiClient.rejectRequest(token, id, comments[id] || "Rejected pending further review.");
      setData((current) => current?.map((item) => (item.id === id ? updated : item)) || [updated]);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Rejection failed.";
      setActionError(message);
    } finally {
      setActiveApprovalId(null);
    }
  }

  return (
    <PageShell
      title="Approval Inbox"
      description="Review risky actions before they are allowed to proceed to enterprise tools."
    >
      <Card className="mb-6">
        <div className="grid gap-4 md:grid-cols-[220px_1fr] md:items-center">
          <select
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="pending">Pending approvals</option>
            <option value="approved">Approved requests</option>
            <option value="rejected">Rejected requests</option>
            <option value="all">All statuses</option>
          </select>
          <p className="text-sm text-slate-500">
            Switch between pending, approved, and rejected requests to review the full governed decision trail.
          </p>
        </div>
      </Card>
      {loading ? <Card><p className="text-sm text-slate-500">Loading approval queue...</p></Card> : null}
      {error ? <Card><p className="text-sm text-rose-700">{error}</p></Card> : null}
      {actionError ? <Card><p className="text-sm text-rose-700">{actionError}</p></Card> : null}
      <div className="grid gap-6">
        {(data || []).map((approval) => {
          const toolCall = approval.tool_call;
          const policyMatches =
            (toolCall?.response_payload?.policies as { matched_policies?: Array<{ name: string }> } | undefined)
              ?.matched_policies || [];
          const originalIntent = String(toolCall?.request_payload?.original_intent || "Unknown intent");
          const classifications = (toolCall?.request_payload?.data_classifications as string[] | undefined) || [];
          const notificationStatus = approval.notification_status;
          const executionStatus = approval.execution_status;

          return (
            <Card key={approval.id}>
              <div className="grid gap-5 xl:grid-cols-[1.2fr_0.8fr]">
                <div>
                  <div className="flex items-center gap-3">
                    <Badge tone={approval.status}>{approval.status}</Badge>
                    <span className="text-xs text-slate-500">{formatDate(approval.created_at)}</span>
                  </div>
                  <h3 className="mt-4 text-xl font-semibold text-slate-950">
                    {toolCall?.tool_name}.{toolCall?.action_name}
                  </h3>
                  <p className="mt-3 text-sm text-slate-500">{originalIntent}</p>

                  <div className="mt-5 grid gap-4 md:grid-cols-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Risk score</p>
                      <p className="mt-2 text-lg font-semibold text-slate-900">
                        {toolCall ? formatRisk(toolCall.risk_score) : "N/A"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Data classes</p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {classifications.map((item) => (
                          <Badge key={item} tone="low">{item}</Badge>
                        ))}
                      </div>
                    </div>
                  </div>

                  <div className="mt-5">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Triggered policies</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {policyMatches.map((match) => (
                        <Badge key={match.name} tone="high">{match.name}</Badge>
                      ))}
                    </div>
                  </div>

                  <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                    <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Notification status</p>
                    <p className="mt-2 text-sm font-medium text-slate-900">
                      {formatNotificationStatus(notificationStatus?.status)}
                    </p>
                    {notificationStatus?.status === "failed" ? (
                      <p className="mt-2 text-xs text-rose-700">
                        {notificationStatus.message || "Slack notification failed."}
                        {notificationStatus.request_id ? ` Request ID: ${notificationStatus.request_id}` : ""}
                      </p>
                    ) : null}
                    {notificationStatus?.status === "retry_exhausted" ? (
                      <p className="mt-2 text-xs text-rose-700">{notificationStatus.message || "Slack retries were exhausted."}</p>
                    ) : null}
                    {notificationStatus?.status === "queued" && notificationStatus.job ? (
                      <p className="mt-2 text-xs text-slate-500">
                        Attempt {notificationStatus.job.attempts} of {notificationStatus.job.max_attempts}
                      </p>
                    ) : null}
                    {notificationStatus?.status === "sent" && notificationStatus.created_at ? (
                      <p className="mt-2 text-xs text-slate-500">
                        Sent at {formatDate(notificationStatus.created_at)}
                      </p>
                    ) : null}
                    {notificationStatus?.status === "unconfigured" && notificationStatus.message ? (
                      <p className="mt-2 text-xs text-amber-700">{notificationStatus.message}</p>
                    ) : null}
                  </div>

                  {executionStatus ? (
                    <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Execution status</p>
                      <p className="mt-2 text-sm font-medium text-slate-900">
                        {formatExecutionStatus(executionStatus.status)}
                      </p>
                      {executionStatus.message ? (
                        <p className="mt-2 text-xs text-slate-500">{executionStatus.message}</p>
                      ) : null}
                      {executionStatus.job ? (
                        <p className="mt-2 text-xs text-slate-500">
                          Attempt {executionStatus.job.attempts} of {executionStatus.job.max_attempts}
                        </p>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                <div>
                  <label className="mb-2 block text-sm font-medium text-slate-700">Reviewer comment</label>
                  <Textarea
                    placeholder="Document why you are approving or rejecting this action."
                    value={comments[approval.id] || ""}
                    onChange={(event) =>
                      setComments((current) => ({ ...current, [approval.id]: event.target.value }))
                    }
                  />
                  <div className="mt-4 flex gap-3">
                    <Button
                      disabled={activeApprovalId === approval.id || approval.status !== "pending"}
                      onClick={() => handleApprove(approval.id)}
                    >
                      {activeApprovalId === approval.id ? "Processing..." : "Approve and execute"}
                    </Button>
                    <Button
                      variant="danger"
                      disabled={activeApprovalId === approval.id || approval.status !== "pending"}
                      onClick={() => handleReject(approval.id)}
                    >
                      {activeApprovalId === approval.id ? "Processing..." : "Reject"}
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </PageShell>
  );
}
