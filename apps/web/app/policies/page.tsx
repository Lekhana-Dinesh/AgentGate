"use client";

import { FormEvent, useMemo, useState } from "react";

import { PageShell } from "@/components/layout/page-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input, Textarea } from "@/components/ui/input";
import { useAuthedQuery } from "@/hooks/use-authed-query";
import { useSession } from "@/hooks/use-session";
import { ApiError, apiClient } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { Policy, PolicyCondition, PolicyConditionSet, PolicyDecision, PolicySeverity } from "@/types/api";

type PolicyTemplateId =
  | "external_customer_visible"
  | "destructive_action_block"
  | "production_write_approval"
  | "external_mcp_approval"
  | "dangerous_mcp_block"
  | "confidential_externalization_block";

type PolicyDraft = {
  name: string;
  description: string;
  enabled: boolean;
  severity: PolicySeverity;
  decision: PolicyDecision;
  conditions: PolicyConditionSet;
};

type PolicyTemplate = {
  id: PolicyTemplateId;
  title: string;
  description: string;
  operatorNote: string;
  draft: PolicyDraft;
};

const POLICY_PACK_DOC_PATH = "docs/operations/pilot-policy-pack.md";
const POLICY_PACK_VALIDATE_COMMAND = "python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json";
const POLICY_PACK_DRY_RUN_COMMAND =
  "AGENTGATE_API_URL=http://127.0.0.1:8000 AGENTGATE_EMAIL=admin@demo.agentgate.example.com AGENTGATE_PASSWORD=AgentGate123! AGENTGATE_TENANT_SLUG=demo-agentgate python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json --dry-run";

const POLICY_TEMPLATES: PolicyTemplate[] = [
  {
    id: "external_customer_visible",
    title: "Require approval for external or customer-visible actions",
    description: "Conservative starter for outbound or customer-facing actions where human review is safer than silent execution.",
    operatorNote: "Good first template when reviewers want a visible approval path before public or customer-visible side effects.",
    draft: {
      name: "Require approval for external or customer-visible actions",
      description: "Routes external or customer-visible actions through human review during early pilot workflows.",
      enabled: true,
      severity: "high",
      decision: "require_approval",
      conditions: {
        match: "all",
        rules: [
          { field: "recipient_domain", operator: "equals", value: "external" },
          { field: "data_classification", operator: "contains", value: "customer_visible" },
        ],
      },
    },
  },
  {
    id: "destructive_action_block",
    title: "Block destructive actions",
    description: "Simple destructive-action guardrail for delete-style operations while connector allowlists and human review policy mature.",
    operatorNote: "Use this as a broad starter. If you later need more nuance, keep adapter-level destructive blocks in place and refine through scripts or APIs.",
    draft: {
      name: "Block destructive actions",
      description: "Blocks delete-style actions until the workflow has a deliberately reviewed exception path.",
      enabled: true,
      severity: "critical",
      decision: "block",
      conditions: {
        match: "all",
        rules: [{ field: "action_name", operator: "contains", value: "delete" }],
      },
    },
  },
  {
    id: "production_write_approval",
    title: "Require approval for production-like writes",
    description: "Adds a narrow production-focused approval gate for create-style write operations.",
    operatorNote: "This is intentionally conservative and narrow. Broader write coverage can still be layered in through the pilot pack or scripted API updates.",
    draft: {
      name: "Require approval for production-like writes",
      description: "Routes create-style write actions for production-like agents through human review.",
      enabled: true,
      severity: "high",
      decision: "require_approval",
      conditions: {
        match: "all",
        rules: [
          { field: "environment", operator: "equals", value: "production" },
          { field: "action_name", operator: "contains", value: "create" },
        ],
      },
    },
  },
  {
    id: "external_mcp_approval",
    title: "Require approval for external MCP tool calls",
    description: "Starter approval gate for MCP `call_tool` actions aimed at external trust boundaries.",
    operatorNote: "Use only if MCP is intentionally enabled. The pilot recommendation is still to keep MCP disabled by default unless it is internal and tightly allowlisted.",
    draft: {
      name: "Require approval for external MCP tool calls",
      description: "Routes external MCP tool calls through human review.",
      enabled: true,
      severity: "high",
      decision: "require_approval",
      conditions: {
        match: "all",
        rules: [
          { field: "tool_name", operator: "equals", value: "MCP" },
          { field: "action_name", operator: "equals", value: "call_tool" },
          { field: "recipient_domain", operator: "equals", value: "external" },
        ],
      },
    },
  },
  {
    id: "dangerous_mcp_block",
    title: "Block dangerous MCP tool names",
    description: "Blocks MCP calls that the gateway has already classified as dangerous remote tool names.",
    operatorNote: "This pairs with allowlists; it does not make broad MCP exposure safe by itself.",
    draft: {
      name: "Block dangerous MCP tool names",
      description: "Blocks dangerous MCP tool-name patterns such as shell, execute, admin, delete, or transfer.",
      enabled: true,
      severity: "critical",
      decision: "block",
      conditions: {
        match: "all",
        rules: [
          { field: "tool_name", operator: "equals", value: "MCP" },
          { field: "data_classification", operator: "contains", value: "dangerous_remote_tool_name" },
        ],
      },
    },
  },
  {
    id: "confidential_externalization_block",
    title: "Block confidential data externalization",
    description: "Conservative starter for keeping confidential data classes off external channels during a pilot.",
    operatorNote: "This is one of the strongest early-pilot defaults because it blocks a bad outcome rather than hoping later review catches it.",
    draft: {
      name: "Block confidential data to external recipients",
      description: "Blocks confidential data classes from being routed to external recipients.",
      enabled: true,
      severity: "critical",
      decision: "block",
      conditions: {
        match: "all",
        rules: [
          { field: "recipient_domain", operator: "equals", value: "external" },
          { field: "data_classification", operator: "contains", value: "confidential" },
        ],
      },
    },
  },
];

const TARGET_FIELDS = new Set<PolicyCondition["field"]>([
  "tool_name",
  "action_name",
  "recipient_domain",
  "repo_trust",
]);

function cloneConditionSet(conditions: PolicyConditionSet): PolicyConditionSet {
  return {
    match: conditions.match,
    rules: conditions.rules.map((rule) => ({ ...rule })),
  };
}

function cloneDraft(draft: PolicyDraft): PolicyDraft {
  return {
    ...draft,
    conditions: cloneConditionSet(draft.conditions),
  };
}

function getTemplateById(templateId: PolicyTemplateId): PolicyTemplate {
  return POLICY_TEMPLATES.find((item) => item.id === templateId) || POLICY_TEMPLATES[0];
}

function formatDecisionLabel(decision: PolicyDecision): string {
  return decision.replaceAll("_", " ");
}

function formatFieldLabel(field: PolicyCondition["field"]): string {
  return field.replaceAll("_", " ");
}

function formatConditionValue(value: string | number | boolean): string {
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return String(value);
}

function describeRule(rule: PolicyCondition): string {
  const operatorLabel =
    rule.operator === "greater_than" ? ">" : rule.operator === "contains" ? "contains" : "=";
  return `${formatFieldLabel(rule.field)} ${operatorLabel} ${formatConditionValue(rule.value)}`;
}

function splitRules(conditions: PolicyConditionSet) {
  return conditions.rules.reduce(
    (acc, rule) => {
      if (TARGET_FIELDS.has(rule.field)) {
        acc.targetRules.push(rule);
      } else {
        acc.riskRules.push(rule);
      }
      return acc;
    },
    { targetRules: [] as PolicyCondition[], riskRules: [] as PolicyCondition[] },
  );
}

function toPolicyPayload(draft: PolicyDraft) {
  return {
    name: draft.name.trim(),
    description: draft.description.trim(),
    enabled: draft.enabled,
    severity: draft.severity,
    decision: draft.decision,
    conditions: draft.conditions,
  };
}

export default function PoliciesPage() {
  const { token, user } = useSession();
  const [selectedTemplateId, setSelectedTemplateId] = useState<PolicyTemplateId>(POLICY_TEMPLATES[0].id);
  const [draft, setDraft] = useState<PolicyDraft>(() => cloneDraft(POLICY_TEMPLATES[0].draft));
  const [creating, setCreating] = useState(false);
  const [activePolicyId, setActivePolicyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const { data, loading, error, setData } = useAuthedQuery(
    () => apiClient.listPolicies(token || ""),
    [token],
    Boolean(token),
  );

  const canManagePolicies = user?.role === "owner" || user?.role === "admin";
  const selectedTemplate = getTemplateById(selectedTemplateId);
  const draftPreview = useMemo(() => JSON.stringify(toPolicyPayload(draft), null, 2), [draft]);

  function loadTemplate(templateId: PolicyTemplateId) {
    const template = getTemplateById(templateId);
    setSelectedTemplateId(templateId);
    setDraft(cloneDraft(template.draft));
    setActionError(null);
    setActionMessage(null);
    setCopiedKey(null);
  }

  async function handleCopy(label: string, text: string, key: string) {
    if (!navigator?.clipboard?.writeText) {
      setActionError("Clipboard access is not available in this browser.");
      return;
    }
    await navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setActionMessage(`${label} copied.`);
  }

  async function handleCreatePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token || !canManagePolicies) {
      return;
    }
    setCreating(true);
    setActionError(null);
    setActionMessage(null);
    try {
      const created = await apiClient.createPolicy(token, toPolicyPayload(draft));
      setData((current) => [created, ...(current || []).filter((item) => item.id !== created.id)]);
      setActionMessage(`Policy "${created.name}" created from the selected starter template.`);
    } catch (err) {
      setActionError(
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Policy creation failed.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleTogglePolicy(policy: Policy) {
    if (!token || !canManagePolicies) {
      return;
    }
    setActivePolicyId(policy.id);
    setActionError(null);
    setActionMessage(null);
    try {
      const updated = await apiClient.updatePolicy(token, policy.id, { enabled: !policy.enabled });
      setData((current) => current?.map((item) => (item.id === updated.id ? updated : item)) || []);
      setActionMessage(`Policy "${policy.name}" ${updated.enabled ? "enabled" : "disabled"}.`);
    } catch (err) {
      setActionError(
        err instanceof ApiError && err.requestId
          ? `${err.message} Request ID: ${err.requestId}`
          : err instanceof Error
            ? err.message
            : "Policy update failed.",
      );
    } finally {
      setActivePolicyId(null);
    }
  }

  return (
    <PageShell
      title="Policy Management"
      description="Review deterministic governance rules, create safe starter policies from structured templates, and understand the conservative pilot pack without turning the browser into a free-form policy editor."
    >
      {actionError ? (
        <Card className="mb-6">
          <p className="text-sm text-rose-700">{actionError}</p>
        </Card>
      ) : null}
      {actionMessage ? (
        <Card className="mb-6">
          <p className="text-sm text-emerald-700">{actionMessage}</p>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Policy Review</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Deterministic engine, narrow browser authoring</h3>
          <p className="mt-2 text-sm text-slate-500">
            AgentGate still evaluates policies with the existing deterministic engine. This page helps owners and admins review policies, enable or disable them, and create conservative starter rules without rewriting engine semantics.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="block">block wins first</Badge>
            <Badge tone="require_approval">approval next</Badge>
            <Badge tone="redact">redact after that</Badge>
            <Badge tone="allow">allow last</Badge>
          </div>
          <p className="mt-3 text-sm text-slate-500">
            There is no manual browser ordering field in the current build. Effective precedence still comes from decision strength, severity, and existing engine rules.
          </p>
        </Card>

        <Card>
          <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Pilot Policy Pack</p>
          <h3 className="mt-3 text-xl font-semibold text-slate-950">Conservative starter pack review</h3>
          <p className="mt-2 text-sm text-slate-500">
            The shipped pack is intentionally approval-heavy and conservative. It helps a pilot start from reviewed defaults, but it does not replace connector allowlists, trust hints, or reviewer staffing.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Badge tone="medium">GitHub-first</Badge>
            <Badge tone="warning">Jira optional</Badge>
            <Badge tone="disabled">MCP off by default</Badge>
          </div>
          <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
            Review the repo doc at <code>{POLICY_PACK_DOC_PATH}</code> before applying changes to a real tenant.
          </div>
          <div className="mt-4 space-y-3">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Validate the pack</p>
              <div className="mt-2 rounded-2xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-xs text-emerald-300">
                {POLICY_PACK_VALIDATE_COMMAND}
              </div>
              <div className="mt-2">
                <Button
                  variant="secondary"
                  onClick={() => void handleCopy("Validate command", POLICY_PACK_VALIDATE_COMMAND, "validate-command")}
                  type="button"
                >
                  {copiedKey === "validate-command" ? "Copied" : "Copy validate command"}
                </Button>
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Dry-run the apply plan</p>
              <div className="mt-2 rounded-2xl border border-slate-200 bg-slate-950 px-4 py-3 font-mono text-xs text-emerald-300">
                {POLICY_PACK_DRY_RUN_COMMAND}
              </div>
              <div className="mt-2">
                <Button
                  variant="secondary"
                  onClick={() => void handleCopy("Dry-run command", POLICY_PACK_DRY_RUN_COMMAND, "dry-run-command")}
                  type="button"
                >
                  {copiedKey === "dry-run-command" ? "Copied" : "Copy dry-run command"}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      </div>

      <Card className="mt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Starter Templates</p>
            <h3 className="mt-3 text-xl font-semibold text-slate-950">Guided policy creation</h3>
            <p className="mt-2 text-sm text-slate-500">
              Owners and admins can start from a conservative template, review the generated JSON, and create it through the existing policy API. Deeper edits still belong to scripts or direct API use.
            </p>
          </div>
          {user ? <Badge tone={canManagePolicies ? "active" : "degraded"}>{canManagePolicies ? "Manage" : "Read only"}</Badge> : null}
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {POLICY_TEMPLATES.map((template) => (
            <button
              key={template.id}
              className={`rounded-2xl border px-4 py-4 text-left transition ${
                selectedTemplateId === template.id
                  ? "border-signal bg-signal/5"
                  : "border-slate-200 bg-white hover:border-slate-300"
              }`}
              onClick={() => loadTemplate(template.id)}
              type="button"
            >
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={template.draft.decision}>{formatDecisionLabel(template.draft.decision)}</Badge>
                <Badge tone={template.draft.severity}>{template.draft.severity}</Badge>
              </div>
              <h4 className="mt-3 text-sm font-semibold text-slate-950">{template.title}</h4>
              <p className="mt-2 text-sm text-slate-500">{template.description}</p>
            </button>
          ))}
        </div>

        <form className="mt-6 grid gap-6 xl:grid-cols-[0.85fr_1.15fr]" onSubmit={handleCreatePolicy}>
          <div className="space-y-4">
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                Selected template
              </label>
              <select
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-slate-400"
                onChange={(event) => loadTemplate(event.target.value as PolicyTemplateId)}
                value={selectedTemplateId}
              >
                {POLICY_TEMPLATES.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.title}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                Policy name
              </label>
              <Input
                disabled={!canManagePolicies}
                maxLength={255}
                minLength={2}
                onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                required
                value={draft.name}
              />
            </div>
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">
                Description
              </label>
              <Textarea
                disabled={!canManagePolicies}
                maxLength={1000}
                onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                value={draft.description}
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <Badge tone={draft.decision}>{formatDecisionLabel(draft.decision)}</Badge>
              <Badge tone={draft.severity}>{draft.severity}</Badge>
              <Badge tone={draft.enabled ? "enabled" : "disabled"}>{draft.enabled ? "enabled" : "disabled"}</Badge>
            </div>
            <label className="flex items-center gap-3 text-sm text-slate-700">
              <input
                checked={draft.enabled}
                className="h-4 w-4 rounded border-slate-300"
                disabled={!canManagePolicies}
                onChange={(event) => setDraft((current) => ({ ...current, enabled: event.target.checked }))}
                type="checkbox"
              />
              Create this policy as enabled
            </label>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-600">
              {selectedTemplate.operatorNote}
            </div>
            <div className="flex flex-wrap gap-3">
              <Button
                disabled={creating || !canManagePolicies || draft.name.trim().length < 2}
                type="submit"
              >
                {creating ? "Creating..." : "Create from template"}
              </Button>
              <Button
                disabled={!canManagePolicies && !draftPreview}
                onClick={() => void handleCopy("Template JSON", draftPreview, "template-json")}
                type="button"
                variant="secondary"
              >
                {copiedKey === "template-json" ? "Copied" : "Copy template JSON"}
              </Button>
            </div>
            {!canManagePolicies ? (
              <p className="text-sm text-slate-500">
                Only owner and admin roles can create or update policies from the browser. Reviewers and other roles can still inspect the deterministic policy set.
              </p>
            ) : null}
          </div>

          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Generated preview</p>
            <Textarea className="mt-3 font-mono text-xs text-slate-800" readOnly value={draftPreview} />
            <p className="mt-3 text-sm text-slate-500">
              This browser surface deliberately avoids a free-form JSON editor. For deeper edits, use the existing policy API or the documented pilot-pack scripts after review.
            </p>
          </div>
        </form>
      </Card>

      <div className="mt-6">
        {loading ? (
          <Card>
            <p className="text-sm text-slate-500">Loading policies...</p>
          </Card>
        ) : error ? (
          <Card>
            <p className="text-sm text-rose-700">{error}</p>
          </Card>
        ) : !(data || []).length ? (
          <div className="space-y-4">
            <EmptyState
              title="No tenant policies yet"
              description="Start with a conservative template here, or review and dry-run the pilot policy pack before creating policies through scripts."
            />
            <Card>
              <p className="text-sm text-slate-600">
                Recommended starting point: validate <code>policy-packs/pilot-default/policies.json</code>, dry-run the apply script, and confirm connector allowlists and reviewer coverage before real pilot traffic.
              </p>
            </Card>
          </div>
        ) : (
          <div className="space-y-6">
            {(data || []).map((policy) => {
              const { targetRules, riskRules } = splitRules(policy.conditions);
              const policyJson = JSON.stringify(toPolicyPayload(policy), null, 2);
              return (
                <Card key={policy.id}>
                  <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="text-xl font-semibold text-slate-950">{policy.name}</h3>
                        <Badge tone={policy.enabled ? "enabled" : "disabled"}>
                          {policy.enabled ? "enabled" : "disabled"}
                        </Badge>
                        <Badge tone={policy.decision}>{formatDecisionLabel(policy.decision)}</Badge>
                        <Badge tone={policy.severity}>{policy.severity}</Badge>
                      </div>
                      <p className="mt-2 text-sm text-slate-500">{policy.description || "No description provided."}</p>
                      <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                        <span>Match mode: {policy.conditions.match}</span>
                        <span>{policy.conditions.rules.length} rule{policy.conditions.rules.length === 1 ? "" : "s"}</span>
                        <span>Updated {formatDate(policy.updated_at)}</span>
                        <span>Created {formatDate(policy.created_at)}</span>
                        <span>Created by {policy.created_by || "unknown"}</span>
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        onClick={() => void handleCopy(`Policy "${policy.name}" JSON`, policyJson, `policy:${policy.id}`)}
                        type="button"
                        variant="secondary"
                      >
                        {copiedKey === `policy:${policy.id}` ? "Copied" : "Copy JSON"}
                      </Button>
                      {canManagePolicies ? (
                        <Button
                          disabled={activePolicyId !== null}
                          onClick={() => void handleTogglePolicy(policy)}
                          type="button"
                          variant={policy.enabled ? "ghost" : "primary"}
                        >
                          {activePolicyId === policy.id
                            ? "Saving..."
                            : policy.enabled
                              ? "Disable"
                              : "Enable"}
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  <div className="mt-5 grid gap-4 xl:grid-cols-2">
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Target conditions</p>
                      {targetRules.length ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {targetRules.map((rule, index) => (
                            <Badge key={`${policy.id}:target:${index}`} tone="low">
                              {describeRule(rule)}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-3 text-sm text-slate-500">No explicit tool, action, recipient, or repo-trust conditions.</p>
                      )}
                    </div>
                    <div className="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
                      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Risk and data conditions</p>
                      {riskRules.length ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {riskRules.map((rule, index) => (
                            <Badge key={`${policy.id}:risk:${index}`} tone="warning">
                              {describeRule(rule)}
                            </Badge>
                          ))}
                        </div>
                      ) : (
                        <p className="mt-3 text-sm text-slate-500">No explicit risk, environment, data-classification, or numeric threshold conditions.</p>
                      )}
                    </div>
                  </div>

                  <details className="mt-5 rounded-2xl border border-slate-200 bg-white px-4 py-4">
                    <summary className="cursor-pointer text-sm font-semibold text-slate-900">Preview policy JSON</summary>
                    <Textarea className="mt-4 font-mono text-xs text-slate-800" readOnly value={policyJson} />
                  </details>
                </Card>
              );
            })}
          </div>
        )}
      </div>
    </PageShell>
  );
}
