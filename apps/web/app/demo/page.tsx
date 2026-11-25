"use client";

import Link from "next/link";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate, formatRisk } from "@/lib/utils";
import type { DemoScenarioResponse, GitHubGovernedDemoResponse, ToolCall } from "@/types/api";

function getToolArguments(call: ToolCall): Record<string, unknown> {
  const candidate = call.request_payload?.arguments;
  if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
    return candidate as Record<string, unknown>;
  }
  return {};
}

function getGitHubTarget(call: ToolCall): string {
  const args = getToolArguments(call);
  const repository =
    typeof args.repository === "string"
      ? args.repository
      : typeof args.owner === "string" && typeof args.repo === "string"
        ? `${args.owner}/${args.repo}`
        : "";
  const numberValue = args.pull_number ?? args.number;
  const issueNumber =
    typeof numberValue === "number"
      ? numberValue
      : typeof numberValue === "string"
        ? Number(numberValue)
        : null;
  return [repository, Number.isFinite(issueNumber) ? `#${issueNumber}` : ""].filter(Boolean).join(" ");
}

function formatApiError(err: unknown, fallback: string) {
  if (err instanceof ApiError && err.requestId) {
    return `${err.message} Request ID: ${err.requestId}`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return fallback;
}

export default function DemoPage() {
  const { token } = useSession();
  const [githubResult, setGithubResult] = useState<GitHubGovernedDemoResponse | null>(null);
  const [githubError, setGithubError] = useState<string | null>(null);
  const [githubLoading, setGithubLoading] = useState(false);
  const [salesResult, setSalesResult] = useState<DemoScenarioResponse | null>(null);
  const [salesError, setSalesError] = useState<string | null>(null);
  const [salesLoading, setSalesLoading] = useState(false);

  async function runGovernedGitHubScenario() {
    if (!token) {
      return;
    }
    setGithubLoading(true);
    setGithubError(null);
    try {
      const response = await apiClient.runGovernedGitHubScenario(token);
      setGithubResult(response);
    } catch (err) {
      setGithubError(formatApiError(err, "GitHub demo run failed."));
    } finally {
      setGithubLoading(false);
    }
  }

  async function runSalesScenario() {
    if (!token) {
      return;
    }
    setSalesLoading(true);
    setSalesError(null);
    try {
      const response = await apiClient.runSalesScenario(token);
      setSalesResult(response);
    } catch (err) {
      setSalesError(formatApiError(err, "Demo run failed."));
    } finally {
      setSalesLoading(false);
    }
  }

  return (
    <PageShell
      title="Demo Workflows"
      description="Run curated governed workflows that show policy simulation, approval routing, execution control, and operator evidence."
    >
      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="space-y-6">
          <Card>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Primary workflow</p>
            <h3 className="mt-2 text-2xl font-semibold text-slate-950">Governed GitHub workflow</h3>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              Show an enterprise buyer exactly what happens when an AI agent tries to leave a customer-visible
              GitHub update: AgentGate simulates the policy outcome, pauses the live attempt for approval,
              executes only after review, and leaves trace and audit evidence behind.
            </p>
            <div className="mt-5 space-y-3 text-sm text-slate-600">
              <p>1. Simulate a public GitHub issue comment against a customer-visible repository.</p>
              <p>2. Route the real tool call through the gateway and require approval before execution.</p>
              <p>3. Approve with the seeded reviewer and complete execution through a demo-safe GitHub path.</p>
              <p>4. Open the trace replay, approval record, tool call, and audit evidence from the result panel.</p>
            </div>
            <div className="mt-6 flex flex-wrap gap-3">
              <Button onClick={runGovernedGitHubScenario} disabled={githubLoading}>
                {githubLoading ? "Running..." : "Run governed GitHub workflow"}
              </Button>
              <Badge tone="high">Approval-first</Badge>
              <Badge tone="low">Demo-safe connector required</Badge>
            </div>
            {githubError ? <p className="mt-4 text-sm text-rose-700">{githubError}</p> : null}
          </Card>

          {githubResult ? (
            <>
              <Card>
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h3 className="text-xl font-semibold text-slate-950">
                      {githubResult.execution_mode === "queued" ? "Approved execution queued"
                        : githubResult.trace_status === "completed" ? "Governed run completed"
                        : "Governed run needs attention"}
                    </h3>
                    <p className="mt-2 text-sm text-slate-500">
                      Trace status: <span className="font-semibold text-slate-700">{githubResult.trace_status}</span>.
                      {" "}
                      {githubResult.trace_summary}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Badge tone={githubResult.governed_attempt.decision}>
                      {githubResult.governed_attempt.decision}
                    </Badge>
                    <Badge tone={githubResult.tool_call.status}>{githubResult.tool_call.status}</Badge>
                    <Badge tone={githubResult.simulation.risk_band}>{githubResult.simulation.risk_band}</Badge>
                  </div>
                </div>
                <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700">
                  {githubResult.execution_mode === "queued"
                    ? "The worker will run the demo-safe GitHub step. Open the trace or approved request to check its outcome."
                    : githubResult.execution_mode === "demo_safe_mock"
                      ? "Demo-safe execution is active. AgentGate completed the approved GitHub step without sending a live GitHub request."
                      : "Check the trace and approved request for the execution outcome."}
                </div>
                <div className="mt-5 flex flex-wrap gap-3 text-sm">
                  <Link className="font-semibold text-signal" href={githubResult.evidence_links.trace_path}>
                    Open trace replay
                  </Link>
                  <Link className="font-semibold text-signal" href={githubResult.evidence_links.approvals_path}>
                    Open approved request
                  </Link>
                  <Link className="font-semibold text-signal" href={githubResult.evidence_links.tool_calls_path}>
                    Open tool calls
                  </Link>
                  <Link className="font-semibold text-signal" href={githubResult.evidence_links.audit_path}>
                    Open audit logs
                  </Link>
                </div>
              </Card>

              <div className="grid gap-6 md:grid-cols-2">
                <Card>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Simulation</p>
                  <h4 className="mt-2 text-lg font-semibold text-slate-950">Policy flagged the request before execution</h4>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Badge tone={githubResult.simulation.decision}>{githubResult.simulation.decision}</Badge>
                    <Badge tone={githubResult.simulation.risk_band}>{githubResult.simulation.risk_band}</Badge>
                  </div>
                  <p className="mt-4 text-sm text-slate-600">{githubResult.simulation.explanation}</p>
                  <ul className="mt-4 space-y-2 text-sm text-slate-600">
                    {githubResult.simulation.matched_policies.map((match) => (
                      <li key={`${match.name}-${match.source}`}>
                        {match.name} ({match.source})
                      </li>
                    ))}
                  </ul>
                </Card>

                <Card>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Governed attempt</p>
                  <h4 className="mt-2 text-lg font-semibold text-slate-950">
                    GitHub.comment_on_issue_or_pr
                  </h4>
                  <p className="mt-2 text-sm text-slate-500">{getGitHubTarget(githubResult.tool_call)}</p>
                  <div className="mt-4 grid gap-4 sm:grid-cols-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Risk score</p>
                      <p className="mt-2 font-semibold text-slate-900">
                        {formatRisk(githubResult.governed_attempt.risk.score)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Intent match</p>
                      <p className="mt-2 font-semibold text-slate-900">
                        {githubResult.governed_attempt.intent.intent_match ? "Matched" : "Mismatch detected"}
                      </p>
                    </div>
                  </div>
                  <ul className="mt-4 space-y-2 text-sm text-slate-600">
                    {githubResult.governed_attempt.policies.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </Card>

                <Card>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Approval and execution</p>
                  <h4 className="mt-2 text-lg font-semibold text-slate-950">
                    Approved by {githubResult.approval.reviewer_email}
                  </h4>
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Badge tone={githubResult.approval.status}>{githubResult.approval.status}</Badge>
                    <Badge tone={githubResult.tool_call.status}>{githubResult.tool_call.status}</Badge>
                    <Badge tone="low">{githubResult.execution_mode}</Badge>
                  </div>
                  <p className="mt-4 text-sm text-slate-600">
                    {githubResult.approval.approver_comment || "No approver comment recorded."}
                  </p>
                  <p className="mt-4 text-sm text-slate-500">
                    Decided at {githubResult.approval.decided_at ? formatDate(githubResult.approval.decided_at) : "N/A"}
                  </p>
                </Card>

                <Card>
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Audit evidence</p>
                  <h4 className="mt-2 text-lg font-semibold text-slate-950">Operator-visible event trail</h4>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {githubResult.audit_events.map((event) => (
                      <Badge key={event.id} tone="low">{event.event_type}</Badge>
                    ))}
                  </div>
                  <div className="mt-4 space-y-2 text-sm text-slate-600">
                    {githubResult.audit_events.map((event) => (
                      <p key={`${event.id}-detail`}>
                        {formatDate(event.created_at)}: {event.event_type}
                      </p>
                    ))}
                  </div>
                </Card>
              </div>
            </>
          ) : null}
        </div>

        <div className="space-y-6">
          <Card>
            <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Secondary workflow</p>
            <h3 className="mt-2 text-2xl font-semibold text-slate-950">Sales renewal scenario</h3>
            <p className="mt-4 text-sm leading-6 text-slate-600">
              Keep the existing multi-step sales run handy when you want to show a broader gateway story across CRM,
              pricing, and outbound communications.
            </p>
            <div className="mt-5 space-y-3 text-sm text-slate-600">
              <p>1. Read Salesforce account context for Acme Corp.</p>
              <p>2. Read internal pricing data for the renewal package.</p>
              <p>3. Attempt a 30% discount.</p>
              <p>4. Attempt an external email with internal pricing attached.</p>
            </div>
            <div className="mt-6">
              <Button onClick={runSalesScenario} disabled={salesLoading}>
                {salesLoading ? "Running..." : "Run sales workflow"}
              </Button>
            </div>
            {salesError ? <p className="mt-4 text-sm text-rose-700">{salesError}</p> : null}
          </Card>

          {salesResult ? (
            <>
              <Card>
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-xl font-semibold text-slate-950">Run complete</h3>
                    <p className="mt-2 text-sm text-slate-500">
                      Trace status: <span className="font-semibold text-slate-700">{salesResult.trace_status}</span>.
                      {" "}
                      Replay the end-to-end trace to inspect how each decision was made.
                    </p>
                  </div>
                  <Link className="font-semibold text-signal" href={`/traces/${salesResult.trace_id}`}>
                    Open trace
                  </Link>
                </div>
                {salesResult.approval_actions.length ? (
                  <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    The demo auto-approved the discount step through the seeded reviewer so the run could continue to the external email decision.
                  </div>
                ) : null}
              </Card>

              {salesResult.results.map((item) => (
                <Card key={item.tool_call_id}>
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-sm text-slate-500">Tool call</p>
                      <h4 className="text-lg font-semibold text-slate-950">{item.tool_call_id}</h4>
                    </div>
                    <div className="flex gap-2">
                      <Badge tone={item.decision}>{item.decision}</Badge>
                      <Badge tone={item.risk.band}>{item.risk.band}</Badge>
                    </div>
                  </div>
                  <div className="mt-4 grid gap-4 md:grid-cols-2">
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Risk score</p>
                      <p className="mt-2 font-semibold text-slate-900">{formatRisk(item.risk.score)}</p>
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Intent match</p>
                      <p className="mt-2 font-semibold text-slate-900">
                        {item.intent.intent_match ? "Matched" : "Mismatch detected"}
                      </p>
                    </div>
                  </div>
                  <p className="mt-4 text-sm text-slate-600">{item.risk.summary}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {item.risk.factors.map((factor) => (
                      <Badge key={`${item.tool_call_id}-${factor.key}`} tone={item.risk.band}>
                        +{factor.weight} {factor.label}
                      </Badge>
                    ))}
                  </div>
                  <ul className="mt-4 space-y-2 text-sm text-slate-600">
                    {item.policies.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </Card>
              ))}
            </>
          ) : null}
        </div>
      </div>
    </PageShell>
  );
}
