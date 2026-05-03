"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function AuditPage() {
  const { token } = useSession();
  const [search, setSearch] = useState("");
  const { data, loading, error } = useAuthedQuery(
    () => apiClient.listAuditEvents(token || ""),
    [token],
    Boolean(token),
  );

  const filtered = (data || []).filter((event) =>
    `${event.event_type} ${event.actor_type} ${event.resource_type}`.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <PageShell
      title="Audit Logs"
      description="Filter immutable decision history by actor, resource, and event type for investigations and governance reviews."
    >
      <Card className="mb-6">
        <Input
          placeholder="Filter by event type, actor, or resource"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </Card>
      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading audit log...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>Event</Th>
                <Th>Actor</Th>
                <Th>Resource</Th>
                <Th>Timestamp</Th>
              </tr>
            </TableHead>
            <TableBody>
              {filtered.map((event) => (
                <tr key={event.id}>
                  <Td>{event.event_type}</Td>
                  <Td>{event.actor_type}</Td>
                  <Td>
                    <div className="font-medium">{event.resource_type}</div>
                    <div className="mono text-xs text-slate-500">{event.resource_id}</div>
                  </Td>
                  <Td>{formatDate(event.created_at)}</Td>
                </tr>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </PageShell>
  );
}

