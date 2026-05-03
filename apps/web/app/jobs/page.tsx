"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { JobRecord } from "@/types/api";

function matchesSearch(job: JobRecord, search: string): boolean {
  const blob = `${job.job_type} ${job.status} ${job.idempotency_key} ${job.last_error || ""}`.toLowerCase();
  return blob.includes(search.toLowerCase());
}

export default function JobsPage() {
  const { token } = useSession();
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");

  const queryString = statusFilter ? `?status=${statusFilter}` : "";
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.listJobs(token || "", queryString),
    [token, queryString],
    Boolean(token),
  );

  const filtered = (data || []).filter((job) => matchesSearch(job, search));

  return (
    <PageShell
      title="Jobs"
      description="Track queued governance work for notifications, approved execution, and future background controls."
    >
      <Card className="mb-6">
        <div className="grid gap-4 md:grid-cols-[1fr_220px]">
          <Input
            placeholder="Search by type, status, idempotency key, or error"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
            <option value="retry_exhausted">Retry exhausted</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </Card>

      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading jobs...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>Type</Th>
                <Th>Status</Th>
                <Th>Attempts</Th>
                <Th>Next Run</Th>
                <Th>Error</Th>
                <Th>Created</Th>
              </tr>
            </TableHead>
            <TableBody>
              {filtered.map((job) => (
                <tr key={job.id}>
                  <Td>
                    <div className="font-medium">{job.job_type}</div>
                    <div className="text-xs text-slate-500">{job.idempotency_key}</div>
                  </Td>
                  <Td><Badge tone={job.status}>{job.status}</Badge></Td>
                  <Td>{job.attempts}/{job.max_attempts}</Td>
                  <Td>{formatDate(job.next_run_at)}</Td>
                  <Td>
                    <div className="max-w-sm text-sm text-slate-700">
                      {job.last_error || "No error recorded."}
                    </div>
                  </Td>
                  <Td>{formatDate(job.created_at)}</Td>
                </tr>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </PageShell>
  );
}
