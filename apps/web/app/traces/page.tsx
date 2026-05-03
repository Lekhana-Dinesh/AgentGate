"use client";

import Link from "next/link";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function TracesPage() {
  const { token } = useSession();
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.listTraces(token || ""),
    [token],
    Boolean(token),
  );

  return (
    <PageShell
      title="Execution Traces"
      description="Replay end-to-end agent runs, including intent analysis, policy decisions, approvals, and outcomes."
    >
      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading traces...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>Intent</Th>
                <Th>Status</Th>
                <Th>Started</Th>
                <Th>Replay</Th>
              </tr>
            </TableHead>
            <TableBody>
              {(data || []).map((trace) => (
                <tr key={trace.id}>
                  <Td>
                    <div className="font-medium">{trace.summary || "Trace replay available"}</div>
                    <div className="mt-1 text-xs text-slate-500">{trace.original_intent}</div>
                  </Td>
                  <Td><Badge tone={trace.status}>{trace.status}</Badge></Td>
                  <Td>{formatDate(trace.started_at)}</Td>
                  <Td>
                    <Link className="font-semibold text-signal" href={`/traces/${trace.id}`}>
                      Open timeline
                    </Link>
                  </Td>
                </tr>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </PageShell>
  );
}

