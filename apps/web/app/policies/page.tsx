"use client";

import { useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";

export default function PoliciesPage() {
  const { token } = useSession();
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listPolicies(token || ""),
    [token],
    Boolean(token),
  );
  const [draftConditions, setDraftConditions] = useState<Record<string, string>>({});
  const [newPolicy, setNewPolicy] = useState({
    name: "",
    description: "",
    severity: "high",
    decision: "require_approval",
    conditions: JSON.stringify(
      {
        match: "all",
        rules: [{ field: "recipient_domain", operator: "equals", value: "external" }],
      },
      null,
      2,
    ),
  });

  async function savePolicy(id: string) {
    if (!token || !data) {
      return;
    }
    const policy = data.find((item) => item.id === id);
    if (!policy) {
      return;
    }
    const parsed = JSON.parse(draftConditions[id] || JSON.stringify(policy.conditions));
    const updated = await apiClient.updatePolicy(token, id, {
      enabled: policy.enabled,
      severity: policy.severity,
      decision: policy.decision,
      description: policy.description,
      conditions: parsed,
    });
    setData((current) => current?.map((item) => (item.id === id ? updated : item)) || []);
  }

  async function createPolicy() {
    if (!token) {
      return;
    }
    const created = await apiClient.createPolicy(token, {
      name: newPolicy.name,
      description: newPolicy.description,
      enabled: true,
      severity: newPolicy.severity,
      decision: newPolicy.decision,
      conditions: JSON.parse(newPolicy.conditions),
    });
    setData((current) => [created, ...(current || [])]);
    setNewPolicy({
      name: "",
      description: "",
      severity: "high",
      decision: "require_approval",
      conditions: newPolicy.conditions,
    });
  }

  return (
    <PageShell
      title="Policy Management"
      description="Create and adjust deterministic runtime policies that decide whether tool calls are allowed, blocked, redacted, or routed for review."
    >
      <Card className="mb-6">
        <h3 className="text-xl font-semibold text-slate-950">Create Policy</h3>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <Input
            placeholder="Policy name"
            value={newPolicy.name}
            onChange={(event) => setNewPolicy((current) => ({ ...current, name: event.target.value }))}
          />
          <Input
            placeholder="Short description"
            value={newPolicy.description}
            onChange={(event) =>
              setNewPolicy((current) => ({ ...current, description: event.target.value }))
            }
          />
          <select
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
            value={newPolicy.severity}
            onChange={(event) => setNewPolicy((current) => ({ ...current, severity: event.target.value }))}
          >
            <option value="low">Low</option>
            <option value="medium">Medium</option>
            <option value="high">High</option>
            <option value="critical">Critical</option>
          </select>
          <select
            className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm"
            value={newPolicy.decision}
            onChange={(event) => setNewPolicy((current) => ({ ...current, decision: event.target.value }))}
          >
            <option value="allow">Allow</option>
            <option value="block">Block</option>
            <option value="require_approval">Require approval</option>
            <option value="redact">Redact</option>
          </select>
        </div>
        <Textarea
          className="mt-4"
          value={newPolicy.conditions}
          onChange={(event) => setNewPolicy((current) => ({ ...current, conditions: event.target.value }))}
        />
        <div className="mt-4">
          <Button onClick={createPolicy}>Create policy</Button>
        </div>
      </Card>

      <div className="grid gap-6">
        {loading ? <Card><p className="text-sm text-slate-500">Loading policies...</p></Card> : null}
        {error ? <Card><p className="text-sm text-rose-700">{error}</p></Card> : null}
        {(data || []).map((policy) => (
          <Card key={policy.id}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <div className="flex items-center gap-3">
                  <h3 className="text-xl font-semibold text-slate-950">{policy.name}</h3>
                  <Badge tone={policy.severity}>{policy.severity}</Badge>
                  <Badge tone={policy.decision}>{policy.decision}</Badge>
                </div>
                <p className="mt-2 text-sm text-slate-500">{policy.description}</p>
              </div>
              <Button variant="secondary" onClick={() => savePolicy(policy.id)}>
                Save JSON
              </Button>
            </div>
            <Textarea
              className="mt-4"
              value={draftConditions[policy.id] || JSON.stringify(policy.conditions, null, 2)}
              onChange={(event) =>
                setDraftConditions((current) => ({ ...current, [policy.id]: event.target.value }))
              }
            />
          </Card>
        ))}
      </div>
    </PageShell>
  );
}

