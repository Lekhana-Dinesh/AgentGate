# MCP Connector

## Purpose

AgentGate's MCP connector is a governed proxy for MCP-compatible HTTP tool servers.
Agents should call MCP tools through AgentGate so the normal gateway controls still apply: tenant auth, intent checks, risk scoring, policy evaluation, approvals, audit, traces, and payload protection.
For controlled pilots, keep MCP disabled by default unless the remote server is internal, tightly allowlisted, and explicitly reviewed.

## Supported Transport

- HTTP only in this build
- AgentGate uses the existing tool `base_url` as the MCP server URL
- The current implementation expects a simple JSON-RPC style MCP endpoint for `tools/list` and `tools/call`

This is intentionally a narrow foundation, not a full MCP transport matrix.

## Supported Actions

- `list_tools`
- `call_tool`

`call_tool` is only allowed when:

- the requested remote tool name is present in `config.allowed_tool_names`
- the remote tool name is not present in `config.blocked_tool_names`
- the request body stays within `config.max_request_bytes`
- the response body stays within `config.max_response_bytes`

Unknown or destructive-looking MCP actions are blocked at the adapter layer.

## Authentication

Supported `config.auth_mode` values:

- `none`
- `bearer_env`
- `api_key_env`

Supported secret-reference fields:

- `token_env_var` for `bearer_env`
- `api_key_env_var` for `api_key_env`

Raw bearer tokens, API keys, Authorization headers, and secret-bearing header maps are rejected from tool config and must not be stored in the database.

## Example Config

```json
{
  "name": "MCP",
  "type": "mcp",
  "base_url": "https://mcp.example.test",
  "config": {
    "transport": "http",
    "auth_mode": "bearer_env",
    "token_env_var": "AGENTGATE_MCP_TOKEN",
    "allowed_tool_names": ["knowledge_search", "ticket_comment"],
    "blocked_tool_names": ["delete_records"],
    "max_request_bytes": 16384,
    "max_response_bytes": 65536,
    "timeout_ms": 5000,
    "trust_domain": "internal",
    "max_read_retries": 1,
    "retry_backoff_seconds": 0.0
  },
  "risk_level": "high",
  "enabled": true
}
```

## Trust Domains

Supported `config.trust_domain` values:

- `internal`
- `external`
- `unknown`

Trust domain influences runtime risk and approval behavior. External and unknown MCP servers should be treated as materially riskier than internal ones.
They are poor day-one pilot defaults. If you use MCP in a controlled pilot at all, prefer a narrowly scoped internal server with explicit approval coverage.

## Safety Model

- MCP calls do not bypass the gateway.
- Tool allowlists are mandatory.
- `list_tools` may retry on safe upstream failures.
- `call_tool` is single-attempt only and is not blindly retried.
- Timeouts are explicit and bounded.
- Health checks expose safe status only and can optionally probe `tools/list`.
- Error handling avoids echoing raw credentials, Authorization headers, or protected payloads.

## Example Policy Patterns

- Require approval for `tool_name=MCP` plus `recipient_domain=external`
- Require approval for `tool_name=MCP` plus `data_classification contains remote_tool_side_effect`
- Block `tool_name=MCP` plus `data_classification contains dangerous_remote_tool_name`

## Required Permissions On The MCP Server

AgentGate does not grant permissions itself. The MCP server or its downstream integrations must still be configured with the minimum privileges needed for the allowlisted tools.

Keep the remote server scoped narrowly:

- expose only the tools the tenant actually needs
- keep AgentGate `allowed_tool_names` narrower than the full server catalog where possible
- avoid exposing destructive, shell, or admin-capable tools unless you intentionally want them approval-gated or blocked

## Limitations

- not a recommended default first live connector or a broad enterprise tool-access layer
- HTTP transport only
- No stdio transport
- No long-lived MCP session management or stream transport support
- No prompts, resources, or other non-tool MCP surfaces
- No unrestricted tool discovery or execution
- No automatic remote tool schema normalization beyond the returned `name`, `description`, and `inputSchema`

Use this foundation when you want governed MCP tool access, not when you need the entire MCP protocol universe inside AgentGate.
