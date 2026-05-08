# Tool Management

## Purpose

The `/tools` page is a safe operator posture and metadata-management surface for governed tools and connectors.

It helps a tenant admin or security reviewer answer:

- Which tools or connectors are configured?
- Which connector type does each tool use?
- Is the connector enabled, scoped, and healthy enough for review?
- Which non-secret metadata can be safely created or edited in the browser?
- Which docs or next steps should the operator read?

## What The Page Shows

- tool name and description
- connector type such as GitHub, Jira, MCP, or Mock
- enabled or disabled state
- base URL host only in the inventory view and sanitized base URL in safe detail
- auth mode label
- trust-domain hint when applicable
- scoped allowlist counts in inventory and safe allowlist values in detail
- supported action list
- safe health posture
- warning flags
- connector guide paths

For owner and admin roles, the page can also:

- create safe connector metadata from guided templates
- edit safe non-secret metadata for GitHub, Jira, MCP, and mock connectors
- enable or disable connector records
- trigger a safe outbound connector health probe

Security reviewers stay view-only in the browser.

## What The Page Does Not Allow

- It does not edit raw tool config.
- It does not display raw `config`.
- It does not display tokens, private keys, secret refs, env-var names, or auth emails.
- It does not accept raw tokens, private keys, auth emails, or Authorization headers from the browser.
- It does not replace the broader programmatic tool APIs when an operator deliberately needs raw config control.

## Safe Browser Metadata Scope

The current browser flow is intentionally narrow.

Supported managed connector types:

- GitHub
- Jira
- MCP
- Mock

Supported browser-managed metadata:

- connector name and description
- enabled or disabled state
- risk level
- sanitized base URL
- auth mode label
- trust-domain hint for MCP
- safe allowlists such as repositories, Jira projects, or MCP tool names
- GitHub App `app_id` and `installation_id`

The server preserves or injects external credential bindings as needed for validation, but those bindings are not returned to the browser.

## Secret Configuration

Operators should continue to configure connector secrets outside the browser UI:

- runtime environment variables
- future secret-manager integrations
- the broader validated tool APIs when needed for deliberate raw-config control

The browser page is intentionally not a secret editor.

## Recommended Operator Flow

1. Open `/tools`.
2. Confirm the expected tools exist and are enabled.
3. Review connector type, scope counts, auth mode, and trust-domain hints.
4. If needed, create or update safe metadata from a guided template.
5. Finish credential injection outside AgentGate before expecting a live probe or real execution to succeed.
6. Run a health probe if you are an owner or admin and need a fresh readiness signal.
7. Follow the connector guide paths in `docs/connectors/` for deeper configuration guidance.

## Limitations

- There is still no browser CRUD flow for real connector secrets.
- The safe browser workflow covers only a small connector set and a narrow metadata field set.
- Repo connector guides still live as markdown docs and are referenced by path instead of being fully rendered inside the UI.
- Mock tools and some other generic tool types do not expose the same health richness or browser management path as governed external connectors.
