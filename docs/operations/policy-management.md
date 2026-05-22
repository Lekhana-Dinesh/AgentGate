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
- run an advisory policy simulation for a proposed tool-call shape before changing live policy state
- see created and updated timestamps
- copy policy JSON for API or script-driven review

Owner and admin roles can also:

- enable or disable an existing policy
- create a new policy from a conservative starter template
- review the generated JSON before creation

Owner, admin, and security reviewer roles can also:

- run a dry-run simulation that reuses the deterministic gateway intent, risk, policy, and guardrail logic
- review the simulated decision, matched policies, risk band, and explanation without executing any external action

## Policy Simulation

The `/policies` page now includes a minimal policy simulation panel.

Use it when you want to answer questions such as:

- would this action be allowed, blocked, or routed to approval today
- which policies are driving that result
- how a proposed new policy would change the outcome before it is enabled

The browser panel is intentionally narrow:

- choose an existing tenant agent
- choose an existing tenant tool
- enter an action name, original intent, payload hints, and classification hints
- run a dry run against the current enabled tenant policies

The API also supports a more advanced simulation shape for script-driven review:

- explicit `policy_ids` if you want to simulate against a selected subset of saved policies
- `proposed_policies` if you want to include unsaved policy definitions in the simulation set

## What Simulation Does

Simulation reuses the existing deterministic governance path for:

- intent analysis
- risk scoring
- policy matching
- built-in guardrails such as critical-risk escalation and external intent-mismatch review

It returns:

- the simulated final decision
- whether approval would be required
- matched policies
- risk band and risk factors
- intent mismatch status
- operator-facing explanation

## What Simulation Does Not Do

Simulation is advisory only.

It does not:

- execute GitHub, Jira, MCP, Slack, AWS, or any other external tool
- create tool-call records
- create approvals
- enqueue jobs
- mutate policy state
- prove that a real downstream connector call would succeed
- replace connector allowlists, reviewer coverage, or deployment-specific change review

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
- `security_reviewer` can review policies and run dry-run simulation, but does not get browser mutation controls
- `developer`, `viewer`, and `approver` do not get browser mutation controls
- `developer`, `viewer`, and `approver` also cannot use policy simulation

Tenant isolation still applies to every policy API response and mutation.

## Limitations

- There is no browser-side drag ordering or explicit manual priority control
- the browser does not expose a broad free-form JSON editor anymore
- the browser does not apply policy packs directly
- policy simulation is advisory and does not prove connector correctness, downstream permissions, or end-to-end execution success
- templates are conservative starters, not complete production policy libraries
- connector allowlists, trust hints, and reviewer staffing still matter more than policy text alone
