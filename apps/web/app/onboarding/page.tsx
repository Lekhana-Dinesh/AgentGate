"use client";

import Link from "next/link";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";

function renderLabel(value: string) {
  return value.replaceAll("_", " ");
}

function statusTone(complete: boolean) {
  return complete ? "ready" : "warning";
}

export default function OnboardingPage() {
  const { token, user } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const canView = user ? ["owner", "admin", "security_reviewer"].includes(user.role) : false;
  const canManage = user ? ["owner", "admin"].includes(user.role) : false;
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.getOnboardingStatus(token || ""),
    [token, refreshKey],
    Boolean(token) && canView,
  );

  async function runAction(
    action: "dismiss" | "reset" | "demo-policy",
    runner: () => Promise<{ message: string }>,
  ) {
    if (!token || !canManage) {
      return;
    }
    setBusyAction(action);
    setActionMessage(null);
    setActionError(null);
    try {
      const response = await runner();
      setActionMessage(response.message);
      const nextStatus = await apiClient.getOnboardingStatus(token);
      setData(nextStatus);
      setRefreshKey((current) => current + 1);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "The onboarding action could not be completed.";
      setActionError(message);
    } finally {
      setBusyAction(null);
    }
  }

  if (!canView) {
    return (
      <PageShell
        title="Onboarding"
        description="Safe first-run guidance is limited to tenant operators with admin or security review access."
      >
        <Card>
          <p className="text-sm text-slate-600">
            Your current role can use the rest of the workspace, but onboarding status is limited to owner, admin,
            and security reviewer roles because it summarizes tenant setup posture.
          </p>
        </Card>
      </PageShell>
    );
  }

  return (
    <PageShell
      title="Onboarding"
      description="Review safe tenant setup status, follow the next recommended step, and prepare a first governed workflow without exposing secrets or replacing the existing admin APIs."
      actions={
        <Button variant="ghost" onClick={() => setRefreshKey((current) => current + 1)} disabled={!token}>
          Refresh
        </Button>
      }
    >
      {loading ? <Card><p className="text-sm text-slate-500">Loading onboarding status...</p></Card> : null}
      {error ? <Card><p className="text-sm text-rose-700">{error}</p></Card> : null}

      {data ? (
        <>
          <div className="grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
            <Card>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Recommended next step</p>
                  <h3 className="mt-3 text-2xl font-semibold text-slate-950">Complete the first governed workflow</h3>
                  <p className="mt-3 max-w-2xl text-sm text-slate-600">{data.recommended_next_step}</p>
                </div>
                <Badge tone={data.dismissed ? "disabled" : "ready"}>{data.dismissed ? "dismissed" : "active"}</Badge>
              </div>
              <div className="mt-5 flex flex-wrap gap-3">
                <Link
                  href={data.recommended_next_step_href}
                  className="inline-flex items-center justify-center rounded-xl bg-ink px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-900"
                >
                  Open next step
                </Link>
                <Link
                  href="/demo"
                  className="inline-flex items-center justify-center rounded-xl bg-white/60 px-4 py-2 text-sm font-semibold text-slate-700 transition hover:bg-white"
                >
                  Open demo page
                </Link>
              </div>
              {actionMessage ? <p className="mt-4 text-sm text-emerald-700">{actionMessage}</p> : null}
              {actionError ? <p className="mt-4 text-sm text-rose-700">{actionError}</p> : null}
            </Card>

            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Current status</p>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div>
                  <p className="text-sm text-slate-500">Agents</p>
                  <p className="mt-1 text-2xl font-semibold text-slate-950">{data.agent_count}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Tools</p>
                  <p className="mt-1 text-2xl font-semibold text-slate-950">{data.tool_count}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Policies</p>
                  <p className="mt-1 text-2xl font-semibold text-slate-950">{data.policy_count}</p>
                </div>
                <div>
                  <p className="text-sm text-slate-500">Audit integrity</p>
                  <div className="mt-2">
                    <Badge tone={data.audit_integrity_status === "legacy_only" ? "warning" : "ready"}>
                      {renderLabel(data.audit_integrity_status)}
                    </Badge>
                  </div>
                </div>
              </div>
              <div className="mt-5 flex flex-wrap gap-2">
                <Badge tone={data.active_owner_exists ? "ready" : "warning"}>
                  {data.active_owner_exists ? "owner present" : "owner missing"}
                </Badge>
                <Badge tone={data.approval_workflow_available ? "ready" : "warning"}>
                  {data.approval_workflow_available ? "approval available" : "approval unavailable"}
                </Badge>
                <Badge tone={data.settings_overview_available ? "ready" : "warning"}>
                  settings overview
                </Badge>
              </div>
            </Card>
          </div>

          <Card className="mt-6">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Setup checklist</p>
                <h3 className="mt-3 text-xl font-semibold text-slate-950">Safe first-run readiness</h3>
              </div>
              {canManage ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => runAction("demo-policy", () => apiClient.createOnboardingDemoPolicy(token || ""))}
                    disabled={!token || busyAction !== null}
                  >
                    {busyAction === "demo-policy" ? "Creating..." : "Create demo policy"}
                  </Button>
                  {!data.dismissed ? (
                    <Button
                      variant="ghost"
                      onClick={() => runAction("dismiss", () => apiClient.dismissOnboarding(token || ""))}
                      disabled={!token || busyAction !== null}
                    >
                      {busyAction === "dismiss" ? "Saving..." : "Dismiss"}
                    </Button>
                  ) : (
                    <Button
                      variant="ghost"
                      onClick={() => runAction("reset", () => apiClient.resetOnboarding(token || ""))}
                      disabled={!token || busyAction !== null}
                    >
                      {busyAction === "reset" ? "Resetting..." : "Reset walkthrough"}
                    </Button>
                  )}
                </div>
              ) : null}
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.checklist.map((item) => (
                <Link key={item.key} href={item.href} className="rounded-2xl border border-slate-200 bg-white/70 px-5 py-4 transition hover:bg-white">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-semibold text-slate-950">{item.label}</p>
                      <p className="mt-2 text-sm text-slate-500">{item.description}</p>
                    </div>
                    <Badge tone={statusTone(item.complete)}>{item.complete ? "ready" : "needs review"}</Badge>
                  </div>
                </Link>
              ))}
            </div>
          </Card>

          <div className="mt-6 grid gap-6 xl:grid-cols-[1fr_1fr]">
            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Where to go next</p>
              <div className="mt-4 grid gap-3">
                {data.links.map((link) => (
                  <Link key={link.label} href={link.href} className="rounded-2xl border border-slate-200 bg-white/70 px-4 py-4 transition hover:bg-white">
                    <p className="text-sm font-semibold text-slate-950">{link.label}</p>
                    <p className="mt-1 text-sm text-slate-500">{link.description}</p>
                  </Link>
                ))}
              </div>
            </Card>

            <Card>
              <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Demo docs in the repo</p>
              <h3 className="mt-3 text-xl font-semibold text-slate-950">Use the docs package alongside the UI</h3>
              <p className="mt-2 text-sm text-slate-500">
                The browser UI points you to the right product surfaces. The fuller demo and design-partner materials still live in the repository docs.
              </p>
              <div className="mt-4 space-y-3 text-sm text-slate-600">
                <p><span className="font-semibold text-slate-900">Guide:</span> <code>docs/demo/ENTERPRISE_DEMO_GUIDE.md</code></p>
                <p><span className="font-semibold text-slate-900">Evaluation:</span> <code>docs/demo/DESIGN_PARTNER_EVALUATION.md</code></p>
                <p><span className="font-semibold text-slate-900">Script:</span> <code>docs/demo/DEMO_SCRIPT.md</code></p>
                <p><span className="font-semibold text-slate-900">Screenshots:</span> <code>docs/demo/SCREENSHOT_CHECKLIST.md</code></p>
              </div>
            </Card>
          </div>
        </>
      ) : null}
    </PageShell>
  );
}
