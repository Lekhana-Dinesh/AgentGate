"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableHead, Td, Th } from "@/components/ui/table";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { UserRecord } from "@/types/api";

function renderLabel(value: string): string {
  return value.replaceAll("_", " ");
}

export default function UsersPage() {
  const { token, user } = useSession();
  const [refreshKey, setRefreshKey] = useState(0);
  const [activeKey, setActiveKey] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listUsers(token || ""),
    [token, refreshKey],
    Boolean(token),
  );

  const canManageUsers = user?.role === "owner" || user?.role === "admin";

  async function handleLifecycleAction(target: UserRecord) {
    if (!token) {
      return;
    }
    setActionError(null);
    setActiveKey(target.id);
    try {
      const updated = target.is_active
        ? await apiClient.deactivateUser(token, target.id, "manual_admin_deactivation")
        : await apiClient.reactivateUser(token, target.id);
      setData((current) => current?.map((item) => (item.id === updated.id ? updated : item)) || []);
    } catch (err) {
      setActionError(
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "User lifecycle update failed.",
      );
    } finally {
      setActiveKey(null);
    }
  }

  return (
    <PageShell
      title="Users & Identity"
      description="Review tenant-scoped user lifecycle state, local versus OIDC provisioning source, and deprovisioning status without replacing the existing JWT or OIDC login model."
      actions={
        <Button variant="ghost" onClick={() => setRefreshKey((current) => current + 1)} disabled={!token}>
          Refresh
        </Button>
      }
    >
      {actionError ? (
        <Card className="mb-6">
          <p className="text-sm text-rose-700">{actionError}</p>
        </Card>
      ) : null}

      <Card className="mb-6">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Identity Lifecycle</p>
        <h3 className="mt-3 text-xl font-semibold text-slate-950">Safe deactivation foundation</h3>
        <p className="mt-2 text-sm text-slate-500">
          Deactivated users are blocked on subsequent API requests and login attempts. User-created agent API keys are revoked during deactivation, and reactivation does not restore revoked keys.
        </p>
        <p className="mt-2 text-sm text-slate-500">
          SCIM is intentionally not enabled yet. This page prepares tenant operators for future SCIM-managed lifecycle flows without exposing secret config or replacing local and OIDC auth.
        </p>
      </Card>

      <Card>
        {loading ? (
          <p className="text-sm text-slate-500">Loading users...</p>
        ) : error ? (
          <p className="text-sm text-rose-700">{error}</p>
        ) : !data?.length ? (
          <p className="text-sm text-slate-500">No users were found for this tenant.</p>
        ) : (
          <Table>
            <TableHead>
              <tr>
                <Th>User</Th>
                <Th>Role</Th>
                <Th>Status</Th>
                <Th>Source</Th>
                <Th>Last Updated</Th>
                <Th>Actions</Th>
              </tr>
            </TableHead>
            <TableBody>
              {data.map((item) => (
                <tr key={item.id}>
                  <Td>
                    <div className="font-medium text-slate-950">{item.full_name}</div>
                    <div className="mt-1 text-xs text-slate-500">{item.email}</div>
                    <div className="mt-1 text-xs text-slate-500">
                      {item.deactivation_reason || "No deactivation reason recorded."}
                    </div>
                  </Td>
                  <Td>
                    <Badge tone="low">{renderLabel(item.role)}</Badge>
                  </Td>
                  <Td>
                    <Badge tone={item.is_active ? "enabled" : "disabled"}>{item.status}</Badge>
                  </Td>
                  <Td>
                    <Badge tone="low">{item.provisioned_source}</Badge>
                  </Td>
                  <Td>{formatDate(item.updated_at)}</Td>
                  <Td>
                    {canManageUsers ? (
                      <Button
                        variant={item.is_active ? "secondary" : "primary"}
                        onClick={() => void handleLifecycleAction(item)}
                        disabled={activeKey !== null}
                      >
                        {activeKey === item.id
                          ? "Saving..."
                          : item.is_active
                            ? "Deactivate"
                            : "Reactivate"}
                      </Button>
                    ) : (
                      <span className="text-xs text-slate-500">View only</span>
                    )}
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
