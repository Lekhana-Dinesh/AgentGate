# Policy Management

## Purpose

Use the policy management surface to review deterministic runtime policies, create conservative starter policies from guided templates, and understand how the pilot policy pack fits into a controlled evaluation.

The current browser UX is intentionally narrow.

It is meant to help operator teams evaluate and run a pilot without turning the web console into a broad free-form policy editor.

## What The Browser UI Supports

On `/policies`, tenant operators can:

- review existing tenant policies
- see enabled or disabled state
- see decision and severity
- review target conditions such as tool, action, recipient, and repo-trust hints
- review risk and data conditions such as environment, data classification, numeric thresholds, and intent mismatch
- see created and updated timestamps
- copy policy JSON for API or script-driven review

Owner and admin roles can also:

- enable or disable an existing policy
- create a new policy from a conservative starter template
- review the generated JSON before creation

## Safe Starter Templates

The browser currently provides guided starter templates for:

- require approval for external or customer-visible actions
- block destructive actions
- require approval for production-like writes
- require approval for external MCP tool calls
- block dangerous MCP tool names
- block confidential data externalization

These templates are intentionally conservative.

They help a pilot start with reviewable guardrails, but they do not replace tenant-specific policy review.

## Pilot Policy Pack Review

The `/policies` page also helps operators review the shipped pilot pack:

- it explains that the pack is conservative and approval-heavy
- it reminds operators that GitHub is the strongest first live connector, Jira is optional, and MCP should stay disabled by default unless it is internal and tightly allowlisted
- it shows the repo doc path and validation or dry-run commands

The browser does not apply the policy pack.

Use the documented scripts instead:

```bash
python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json
```

```bash
AGENTGATE_API_URL=http://127.0.0.1:8000 \
AGENTGATE_EMAIL=admin@demo.agentgate.example.com \
AGENTGATE_PASSWORD=AgentGate123! \
AGENTGATE_TENANT_SLUG=demo-agentgate \
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json --dry-run
```

## What Remains API Or Script Driven

The current browser UX does not replace the existing policy APIs or pack scripts.

Still API or script driven:

- deep condition editing beyond the guided starter templates
- bulk policy creation or replacement
- exact pilot-pack apply and update workflows
- conflict review for same-name policies
- advanced local customization of a policy pack

## RBAC

- `owner` and `admin` can create and update policies in the browser
- `security_reviewer` can review policies but does not get browser mutation controls
- `developer`, `viewer`, and `approver` do not get browser mutation controls

Tenant isolation still applies to every policy API response and mutation.

## Limitations

- There is no browser-side drag ordering or explicit manual priority control
- the browser does not expose a broad free-form JSON editor anymore
- the browser does not apply policy packs directly
- templates are conservative starters, not complete production policy libraries
- connector allowlists, trust hints, and reviewer staffing still matter more than policy text alone
