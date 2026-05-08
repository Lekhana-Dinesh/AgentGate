# Connectors Context

## 1. Purpose

This file covers the external integration boundary for tool adapters and platform-side notifications.

## 2. Main files/directories

- `apps/api/app/tools/base.py`, `registry.py`, `mock_adapter.py`
- `apps/api/app/tools/github_adapter.py`, `github_auth.py`
- `apps/api/app/tools/jira_adapter.py`, `jira_auth.py`
- `apps/api/app/tools/mcp_adapter.py`, `mcp_auth.py`
- `apps/api/app/services/tool_summary_service.py`
- `apps/api/app/notifications/slack_notifier.py`
- `apps/api/app/api/routes/tools.py`, `approvals.py`
- `docs/connectors/github.md`
- `docs/connectors/jira.md`
- `docs/connectors/mcp.md`
- `docs/integrations/slack.md`

## 3. Current capabilities

- Mock tool adapters for local demo and development flows
- Hardened GitHub connector with `env_pat`, `env_token`, and `github_app` auth modes
- Governed Jira connector with `env_token` and `basic_env` auth modes
- Governed MCP HTTP connector foundation with `none`, `bearer_env`, and `api_key_env` auth modes
- Conservative repo-shipped pilot policy pack aligned to GitHub, Jira, MCP, and mock external-communication risk surfaces
- GitHub App JWT and installation-token exchange with in-memory token caching only
- GitHub action allowlist limited to safe read actions plus `create_issue` and `comment_on_issue_or_pr`
- Jira action allowlist limited to safe reads plus scoped `create_issue`, `add_comment`, `transition_issue`, and `assign_issue`
- MCP action allowlist limited to `list_tools` plus `call_tool` for explicitly allowlisted remote tool names only
- Connector health checks for supported tool types
- Safe tool-summary, safe-detail, probe-health, and narrow owner/admin metadata-management APIs for tenant operators
- Outbound Slack approval notifications as best-effort governance alerts

## 4. Critical invariants / must-not-break rules

- All connector activity must still go through the gateway path.
- Do not place raw GitHub tokens, installation tokens, JWTs, private keys, or Slack bot tokens in tool config or database records.
- Do not place raw Jira tokens, API tokens, passwords, or auth emails in tool config or database records.
- Do not place raw MCP bearer tokens, API keys, or Authorization headers in tool config or database records.
- Tool visibility APIs and the `/tools` UI must not expose raw config, secret refs, env-var token names, auth emails, or full secret-bearing base URLs.
- Destructive or unknown GitHub actions must stay blocked at the adapter layer.
- Destructive or unknown Jira actions must stay blocked at the adapter layer.
- Disallowed or dangerous MCP remote tool names must stay blocked or approval-gated before they become unrestricted execution paths.
- GitHub writes remain single-attempt to avoid duplicate side effects.
- Jira writes remain single-attempt to avoid duplicate issue, comment, transition, or assignment side effects.
- MCP `call_tool` remains single-attempt to avoid duplicate side effects on remote MCP servers.
- Slack notifications must remain non-authoritative. They do not approve, reject, or execute actions.

## 5. Security boundaries

- Tool config stores safe metadata and secret references only.
- GitHub App installation tokens are memory-only runtime state.
- Jira basic auth email and API token stay in the runtime environment only.
- MCP bearer tokens and API keys stay in the runtime environment only.
- Slack notification content must stay sanitized and non-secret.
- Connector health and settings surfaces expose safe status, not raw credentials.
- The tools/connectors page is a narrow safe-metadata surface, not a privileged secret editor or full generic connector builder.

## 6. Known limitations

- GitHub, Jira, and MCP are the governed connector foundations today.
- GitHub is the strongest current live connector and the recommended first pilot surface. Jira is better treated as a constrained opt-in second phase, and MCP should stay disabled by default unless the server is internal and tightly allowlisted.
- The pilot policy pack is a starter pack, not a substitute for reviewing actual repository, project, assignee, trust-domain, and reviewer coverage settings.
- There is no tenant-managed GitHub App installation discovery or webhook-driven sync.
- Jira is intentionally minimal: no destructive actions, no attachment writes, and no tenant-admin secret-management UI.
- MCP is intentionally narrow: HTTP only, tool allowlist only, no stdio transport, no streaming sessions, and no unrestricted remote execution.
- Slack is environment-scoped and outbound-only in the current build.
- No signed interactive Slack approval flow exists yet.
- There is still no browser UI for creating or editing real connector secrets; operators use deployment config, env injection, future secret-manager wiring, and the broader tool APIs when they deliberately need raw config control.

## 7. Relevant tests

- `apps/api/app/tests/test_github_connector.py`
- `apps/api/app/tests/test_jira_connector.py`
- `apps/api/app/tests/test_mcp_connector.py`
- `apps/api/app/tests/test_slack_notifications.py`
- `apps/api/app/tests/test_settings_overview.py`

## 8. When future Codex sessions should read this file

Read this before editing tool adapters, GitHub, Jira, or MCP auth and action support, Slack notification behavior, or connector-health surfaces.
