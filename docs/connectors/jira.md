# Jira Connector

## Overview

AgentGate includes a governed Jira connector behind the standard tool-adapter interface. Every Jira action still goes through the normal gateway path for tenant checks, caller identity, intent analysis, risk scoring, policy evaluation, approvals, audit logging, and trace replay.
For controlled pilots, treat Jira as a constrained optional second-phase connector after a GitHub-first workflow is stable.

Supported actions in this build:

- `get_issue`
- `search_issues`
- `create_issue`
- `add_comment`
- `transition_issue`
- `assign_issue`

Destructive and unknown actions are explicitly blocked at the adapter layer. This build does not expose a generic Jira REST passthrough.

## Auth Modes

Supported `config.auth_mode` values:

- `env_token`
- `basic_env`

Guidance:

- `env_token` is the simpler local or self-hosted bearer-token path.
- `basic_env` is useful for Jira Cloud-style email plus API token auth.

## Example Configuration

Bearer-token example:

```json
{
  "name": "Jira",
  "type": "jira",
  "description": "Governed Jira issue workflow connector",
  "base_url": "https://jira.example.com",
  "config": {
    "auth_mode": "env_token",
    "token_env_var": "AGENTGATE_JIRA_TOKEN",
    "project_allowlist": ["OPS", "SUPPORT"],
    "issue_type_allowlist": ["task", "bug", "incident"],
    "external_project_keys": ["SUPPORT"],
    "transition_allowlist": ["31", "done"],
    "assignee_allowlist": ["acct-support-1", "acct-oncall-1"],
    "timeout_seconds": 15,
    "max_read_retries": 2,
    "retry_backoff_seconds": 0.2
  },
  "risk_level": "high",
  "enabled": true
}
```

Basic auth example:

```json
{
  "config": {
    "auth_mode": "basic_env",
    "api_token_env_var": "AGENTGATE_JIRA_API_TOKEN",
    "email_env_var": "AGENTGATE_JIRA_EMAIL",
    "project_allowlist": ["OPS", "SUPPORT"],
    "issue_type_allowlist": ["task", "incident"],
    "transition_allowlist": ["31", "done"],
    "assignee_allowlist": ["acct-support-1"]
  }
}
```

## Required Configuration

- `base_url`
- `project_allowlist`
- one supported auth mode

Write-specific scoping:

- `create_issue` requires `issue_type_allowlist`
- `transition_issue` requires `transition_allowlist`
- `assign_issue` requires `assignee_allowlist`

`external_project_keys` is optional metadata for operator policy design and future trust classification work. It does not bypass gateway controls.

## Required Jira Permissions

Minimum practical permissions depend on the actions you enable:

- `Browse projects` for `get_issue` and `search_issues`
- `Create issues` for `create_issue`
- `Add comments` for `add_comment`
- `Transition issues` for `transition_issue`
- `Assign issues` for `assign_issue`

If you only need reads, scope the Jira credential to read-only permissions where your Jira deployment supports that.

## Safety Model

- Jira tool config stores only safe metadata and env-var references.
- Raw Jira tokens, API tokens, passwords, and auth emails are rejected from tool config.
- All Jira requests still go through the normal gateway decision path.
- Project allowlists are enforced before outbound Jira calls.
- For early pilots, keep project allowlists narrow and prefer internal or non-customer-facing workflows first.
- Writes are intentionally single-attempt. AgentGate does not blindly retry issue creation, comments, transitions, or assignments.
- Destructive or unknown actions are blocked at the adapter boundary even if a caller tries to invoke them.

## Reliability Behavior

- The connector uses explicit connect, read, write, and pool timeouts.
- Safe read actions may retry with bounded exponential backoff.
- Writes are not retried.
- Upstream handling is sanitized and mapped to stable connector errors:
  - `401` -> `jira_auth_failed`
  - `403` -> `jira_forbidden`
  - `404` -> `jira_resource_not_found`
  - `409` -> `jira_conflict`
  - `400` or `422` -> `jira_validation_failed`
  - `429` -> `jira_rate_limited`
  - `5xx` or transport failures -> `jira_upstream_unavailable`

## Health Checks

Jira tools expose:

- `GET /v1/tools/{tool_id}/health`
- `GET /v1/tools/{tool_id}/health?probe=true`

Safe health fields can include:

- `auth_provider`
- `token_present`
- `credentials_configured`
- `token_env_var`
- `api_token_env_var`
- `email_env_var`
- `project_allowlist_count`
- `issue_type_allowlist_count`
- `external_project_key_count`
- warnings and sanitized error codes

`probe=true` performs a safe Jira project-search probe. It does not perform destructive writes.

## Approval Examples

Practical policy patterns for Jira:

- Require approval for production issue transitions.
- Require approval for customer-visible comments using a request classification such as `customer_visible`.
- Block confidential data in Jira comments.
- Block destructive Jira action names such as `delete_issue`.

## Current Limitations

- best treated as an opt-in later-phase connector, not the default first live workflow
- no delete issue or other destructive actions
- no attachment uploads
- no bulk edit or arbitrary JQL passthrough beyond constrained search usage
- no webhook sync or issue-event ingestion
- no tenant-admin secret-management UI
- no automatic project trust sync from Jira
