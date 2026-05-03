# Demo Scenario

## Scenario Name

Sales Agent Risk Scenario

## User Intent

`Prepare and send a renewal proposal to Acme Corp.`

## Agent Actions

1. Read Salesforce account data.
2. Read internal pricing data.
3. Attempt a 30% discount and route it through approval.
4. Resume the trace after approval and attempt an external email with internal pricing attached.

## Expected Runtime Outcomes

- Salesforce read is allowed and executed via mock adapter.
- Pricing read is allowed and executed via mock adapter.
- Large discount triggers approval routing and the seeded reviewer auto-approves it in the demo flow so the run can continue.
- External email with sensitive internal pricing leaves the trace pending approval for the operator to inspect.
- If Slack approval notifications are enabled, the pending approval writes a redacted Slack notification job and either sends it inline or through the worker.
- Trace steps are written for intent, risk, policy, approval, and final outcome.
- Audit events are created for the decision path.
- Tool-call, approval, trace, and audit views show sanitized payload summaries rather than raw email bodies or protected execution arguments.
- The `Retention` page can preview whether any protected execution payloads from the scenario are eligible for purge once their retention window expires.
- The `Audit Exports` page can show whether a tenant-configured SIEM destination is ready to forward the scenario's audit trail without exposing any destination credentials.

## UI Walkthrough

1. Log in to the demo tenant.
2. Open the `Demo` page.
3. Click `Run Sales Agent Risk Scenario`.
4. Inspect the resulting decisions.
5. Open the generated trace replay.
6. Visit `Approvals` to review pending requests.
7. If you are running worker mode, visit `Jobs` to watch notification and approved-execution job state.
8. Visit `Retention` to run a safe dry-run preview of future payload purge impact.
9. Visit `Audit Exports` if you have configured a tenant destination and want to dry-run or trigger export of the scenario's audit events.
10. Use `GET /v1/security/key-status` if you want to confirm which payload-protection key ref is active without exposing key material.

## Authentication Note

The seeded demo flow still uses local username/password login by default. OIDC is available as an optional tenant-scoped foundation, but the demo does not preconfigure an external identity provider.

## Optional Connector Demo

If `AGENTGATE_GITHUB_TOKEN` is configured, the seeded demo tenant also includes a `GitHub` tool for safe connector testing. See [GitHub Connector](connectors/github.md) for the repository metadata and public comment approval demo flow.

## Optional Slack Notification Demo

If Slack notifications are enabled with a bot token and default destination, the pending approval created in this scenario will also generate a redacted Slack message. In worker mode, that message is delivered by `python -m app.worker`. See [Slack Notifications](integrations/slack.md) for setup and hardening guidance.
