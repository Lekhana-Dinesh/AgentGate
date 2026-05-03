"use client";

import Link from "next/link";
import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatRisk } from "@/lib/utils";
import type { DemoScenarioResponse } from "@/types/api";

export default function DemoPage() {
  const { token } = useSession();
  const [result, setResult] = useState<DemoScenarioResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runScenario() {
    if (!token) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.runSalesScenario(token);
      setResult(response);
    } catch (err) {
      const message =
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Demo run failed.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageShell
      title="Demo Scenario"
      description="Run a realistic sales proposal workflow that exercises safe reads, risk scoring, approval routing, and trace replay."
      actions={
        <Button onClick={runScenario} disabled={loading}>
          {loading ? "Running..." : "Run Sales Agent Risk Scenario"}
        </Button>
      }
    >
      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <Card>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-500">Scenario</p>
          <h3 className="mt-2 text-2xl font-semibold text-slate-950">Renewal proposal with risky externalization</h3>
          <div className="mt-4 space-y-3 text-sm text-slate-600">
            <p>1. Read Salesforce account context for Acme Corp.</p>
            <p>2. Read internal pricing data for the renewal package.</p>
            <p>3. Attempt a 30% discount.</p>
            <p>4. Attempt an external email with internal pricing attached.</p>
          </div>
          {error ? <p className="mt-4 text-sm text-rose-700">{error}</p> : null}
        </Card>

        <div className="space-y-6">
          {result ? (
            <>
              <Card>
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-xl font-semibold text-slate-950">Run complete</h3>
                    <p className="mt-2 text-sm text-slate-500">
                      Trace status: <span className="font-semibold text-slate-700">{result.trace_status}</span>. Replay the end-to-end trace to inspect how each decision was made.
                    </p>
                  </div>
                  <Link className="font-semibold text-signal" href={`/traces/${result.trace_id}`}>
                    Open trace
                  </Link>
                </div>
                {result.approval_actions.length ? (
                  <div className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    The demo auto-approved the discount step through the seeded reviewer so the run could continue to the external email decision.
                  </div>
                ) : null}
              </Card>

              {result.results.map((item) => (
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
