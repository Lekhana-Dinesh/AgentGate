"use client";

import { useParams } from "next/navigation";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function TraceReplayPage() {
  const { id } = useParams<{ id: string }>();
  const { token } = useSession();
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.getTrace(token || "", id),
    [token, id],
    Boolean(token),
  );

  return (
    <PageShell
      title="Trace Replay"
      description="Review the exact decision path the agent followed across intent, risk, policy, and approval layers."
    >
      <Card>
        {loading ? <p className="text-sm text-slate-500">Loading trace...</p> : null}
        {error ? <p className="text-sm text-rose-700">{error}</p> : null}
        {data ? (
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <Badge tone={data.status}>{data.status}</Badge>
              <span className="text-sm text-slate-500">{data.original_intent}</span>
            </div>
            <div className="mt-6 space-y-4">
              {data.steps.map((step) => (
                <div key={step.id} className="rounded-3xl border border-slate-200 bg-white px-5 py-5">
                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-900 text-sm font-semibold text-white">
                        {step.step_number}
                      </div>
                      <div>
                        <p className="font-semibold text-slate-900">{step.type.replace("_", " ")}</p>
                        <p className="text-sm text-slate-500">{formatDate(step.created_at)}</p>
                      </div>
                    </div>
                    <Badge tone={step.type}>{step.type}</Badge>
                  </div>
                  <p className="mt-4 text-sm leading-6 text-slate-700">{step.content}</p>
                  <pre className="mt-4 overflow-x-auto rounded-2xl bg-slate-950 p-4 text-xs text-slate-100">
                    {JSON.stringify(step.metadata_json, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </Card>
    </PageShell>
  );
}

