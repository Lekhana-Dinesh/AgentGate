# Pilot Policy Pack

Use the default pilot pack when you want a conservative starting point for a controlled AgentGate design-partner pilot without hand-creating every policy.

If you are reviewing policies in the browser first, use `/policies` as the operator-facing review surface.

That page can:

- review existing policy state
- show safe starter templates
- explain the pack posture and dry-run workflow

It does not apply the pack from the browser.

## Included Artifact

- `policy-packs/pilot-default/policies.json`

This pack is intentionally approval-heavy. It is meant to reduce the chance that a pilot starts with under-specified runtime controls.

Included policy categories:

- cross-tool externalization guardrails for confidential outbound data and intent-mismatch external actions
- demo or mock external-email approval for production-like agents
- GitHub approval for public or customer-visible comments
- GitHub approval for issue creation by production-like agents
- GitHub destructive-action blocking
- Jira approval for production transitions
- Jira approval for customer-visible or external-project comments
- Jira confidential-comment blocking
- Jira destructive-action blocking
- MCP approval for external or side-effecting tool calls
- MCP blocking for dangerous remote tool-name patterns through the existing `dangerous_remote_tool_name` signal

## What It Does Not Do

- It does not enable connectors.
- It does not inject secrets.
- It does not replace connector allowlists, repo classification, project classification, or reviewer staffing.
- It does not make MCP safe if you broadly expose remote admin or shell-capable tools.
- It is not a universal production policy library or a compliance control set.

## Review Before Applying

Review these items first:

- GitHub repository allowlists and public or internal trust hints
- Jira project, issue-type, transition, and assignee allowlists
- Whether any Jira projects should carry `external_project` or `customer_visible` classifications
- Whether MCP is disabled, internal-only, or intentionally approval-gated
- Whether you have real human reviewer coverage for approval-required actions
- Whether the pack is being applied to a seeded demo tenant that already contains overlapping policies

## Validate The Pack

From the repo root:

```bash
python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json
```

The broader pilot rehearsal wrapper also runs this validator unless you explicitly skip it:

```bash
python scripts/run-pilot-rehearsal.py --skip-live-api
```

The validator checks:

- JSON structure
- required policy fields
- safe condition field and operator usage
- duplicate names
- obvious secret-like values or secret references
- conservative constraints for the shipped `pilot-default` pack

You can also review the pack guidance in:

- `/policies` in the web console for operator-facing explanation
- `docs/operations/policy-management.md` for the broader browser versus script boundary

## Dry-Run The Apply Plan

Prefer a dry run first.

With an existing access token:

```bash
AGENTGATE_API_URL=http://127.0.0.1:8000 \
AGENTGATE_ACCESS_TOKEN=<operator-token> \
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json --dry-run
```

With local demo credentials:

```bash
AGENTGATE_API_URL=http://127.0.0.1:8000 \
AGENTGATE_EMAIL=admin@demo.agentgate.example.com \
AGENTGATE_PASSWORD=AgentGate123! \
AGENTGATE_TENANT_SLUG=demo-agentgate \
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json --dry-run
```

The apply helper:

- authenticates with a bearer token or a normal operator login
- supports both token-mode and cookie-mode deployments
- lists existing tenant policies
- skips exact name-matched policies that already match the pack
- reports differing name-matched policies as conflicts by default
- updates differing name-matched policies only when `--update-existing` is set

This remains the supported apply path.

The browser policy UI does not execute these apply actions for you.

## Apply The Pack

After review:

```bash
AGENTGATE_API_URL=http://127.0.0.1:8000 \
AGENTGATE_EMAIL=admin@demo.agentgate.example.com \
AGENTGATE_PASSWORD=AgentGate123! \
AGENTGATE_TENANT_SLUG=demo-agentgate \
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json
```

If you intentionally want to replace existing same-name policies:

```bash
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json --update-existing
```

## Safe Customization Guidance

Customize carefully:

- tighten connector allowlists before weakening policy conditions
- add more approval coverage before removing existing approval coverage
- prefer narrower tool- or classification-specific conditions over broad allow rules
- use the browser starter templates as a draft aid, not as a substitute for reviewing the generated rule set
- keep destructive actions blocked at the adapter layer even if you later refine policy conditions
- verify one approval-required GitHub, Jira, or mock external-communication path before pilot traffic

## Recommended Use In A Pilot

For the first controlled pilot:

- apply the pack to a clean pilot tenant or dry-run it against the seeded demo tenant
- verify at least one approval path for GitHub or demo email
- if Jira is enabled, verify a transition or comment route goes to approval
- keep MCP disabled unless the server is internal, allowlisted, and explicitly reviewed

## Limitations

- The pack depends on the current gateway signals and connector trust hints already being present and accurate.
- It does not replace human review of tenant-specific workflows.
- It does not solve reviewer fatigue by itself.
- It is intentionally conservative and may create more approvals than a mature long-term deployment would want.
