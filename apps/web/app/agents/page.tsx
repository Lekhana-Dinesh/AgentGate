"use client";

import Link from "next/link";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export default function AgentsPage() {
  const { token } = useSession();
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listAgents(token || ""),
    [token],
    Boolean(token),
  );

  async function handleAction(agentId: string, action: "suspend" | "revoke") {
    if (!token) {
      return;
    }
    const updated =
      action === "suspend"
        ? await apiClient.suspendAgent(token, agentId)
        : await apiClient.revokeAgent(token, agentId);
    setData((current) => (current ? current.map((agent) => (agent.id === agentId ? updated : agent)) : current));
  }

  return (
    <PageShell
      title="Agent Registry"
      description="Review runtime ownership, environment, status, and operating scope for each registered agent."
    >
      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading agents...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : data?.length ? (
          <Table>
            <TableHead>
              <tr>
                <Th>Agent</Th>
                <Th>Environment</Th>
                <Th>Status</Th>
                <Th>Risk</Th>
                <Th>Allowed Tools</Th>
                <Th>Updated</Th>
                <Th>Actions</Th>
              </tr>
            </TableHead>
            <TableBody>
              {data.map((agent) => (
                <tr key={agent.id}>
                  <Td>
                    <Link className="font-semibold text-slate-900 hover:text-signal" href={`/agents/${agent.id}`}>
                      {agent.name}
                    </Link>
                    <div className="mt-1 text-xs text-slate-500">{agent.description || agent.purpose}</div>
                  </Td>
                  <Td>{agent.environment}</Td>
                  <Td><Badge tone={agent.status}>{agent.status}</Badge></Td>
                  <Td><Badge tone={agent.risk_level}>{agent.risk_level}</Badge></Td>
                  <Td>{agent.allowed_tools.join(", ")}</Td>
                  <Td>{formatDate(agent.updated_at)}</Td>
                  <Td>
                    <div className="flex gap-2">
                      <Button variant="secondary" onClick={() => handleAction(agent.id, "suspend")}>
                        Suspend
                      </Button>
                      <Button variant="danger" onClick={() => handleAction(agent.id, "revoke")}>
                        Revoke
                      </Button>
                    </div>
                  </Td>
                </tr>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState
            title="No agents registered"
            description="Create agents through the API or seed the demo tenant to populate the registry."
          />
        )}
      </Card>
    </PageShell>
  );
}

