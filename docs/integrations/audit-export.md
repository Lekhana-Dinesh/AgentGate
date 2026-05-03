# Audit Export

## Overview

AgentGate can now export sanitized tenant-scoped audit events to external systems through the async jobs layer.

Supported destination types in this build:

- `webhook`
- `http_json`
- `splunk_hec`
- `datadog`
- `custom_placeholder`

The current goal is a safe export foundation, not a full SIEM product. Export is durable, tenant-scoped, and sanitized, but it is not yet an immutable archival pipeline.

## What gets exported

Each exported event contains:

- Audit event identifiers and tenant scope
- Actor and resource references
- Event type
- Sanitized metadata
- Inferred severity
- IP address if it was already present on the audit event
- Creation timestamp

AgentGate does not export:

- Raw secrets
- Decrypted execution arguments
- Payload-protection ciphertext internals
- Connector credentials
- OIDC client secrets
- Slack bot tokens

Audit metadata is sanitized when written and sanitized again during export.

## Configuration model

Create a tenant-scoped config with `POST /v1/audit-exports`.

Important fields:

- `name`
- `destination_type`
- `enabled`
- `endpoint_url`
- `secret_ref` or `token_env_var`
- `event_type_filters`
- `severity_filters`
- `max_batch_size`

Raw tokens are never stored in the database.
`endpoint_url` must use `http` or `https` and must not embed credentials, query parameters, or fragments.

Credential patterns:

- `token_env_var`: references an environment variable name such as `AGENTGATE_SPLUNK_HEC_TOKEN`
- `secret_ref`: uses the shared secret-reference format such as `env:AGENTGATE_SPLUNK_HEC_TOKEN`

The current build resolves env-backed references. Placeholder `secret_ref:` and `vault:` references fail closed until an external secret-manager adapter is added.

## Destination behavior

### Webhook and HTTP JSON

- Sends a JSON body with `source`, `destination_type`, `config_name`, and `events`
- May omit auth headers, though production deployments should usually authenticate the destination

### Splunk HEC

- Sends one HEC event object per line
- Uses `Authorization: Splunk <token>`
- Requires `token_env_var` or `secret_ref`

### Datadog

- Sends a JSON array of log objects
- Uses `DD-API-KEY: <token>`
- Requires `token_env_var` or `secret_ref`

### Custom placeholder

- Reuses the generic JSON webhook shape in this build
- Exists as a clean extension point for future destination-specific adapters

## Running exports

Manual dry-run:

```bash
curl -X POST http://localhost:8000/v1/audit-exports/<config-id>/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

Manual real run:

```bash
curl -X POST http://localhost:8000/v1/audit-exports/<config-id>/run \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": false}'
```

Status:

```bash
curl -H "Authorization: Bearer <token>" \
  http://localhost:8000/v1/audit-exports/<config-id>/status
```

In `inline` mode, the API can complete the export during the request after commit.
In `worker` mode, the API creates a durable job and `python -m app.worker` performs the export later.

## Cursor and idempotency behavior

Each `AuditExportConfig` keeps its own cursor:

- `last_exported_at`
- `last_exported_event_id`

This means:

- Multiple destinations per tenant are supported
- One destination does not advance another destination's progress
- Successfully exported events are not exported again on later runs for the same config

Dry-run does not advance the cursor.

## Retry behavior

Audit export retries only for safe, transient conditions:

- Network errors
- Timeouts
- `429`
- `5xx`

Audit export does not retry for:

- `401`
- `403`
- `404`
- `409`
- `422`
- Invalid or unsupported secret references

Configure behavior with:

- `AGENTGATE_AUDIT_EXPORT_TIMEOUT_SECONDS`
- `AGENTGATE_JOB_AUDIT_EXPORT_MAX_ATTEMPTS`
- `AGENTGATE_JOB_AUDIT_EXPORT_RETRY_BACKOFF_SECONDS`

## Dashboard visibility

The `/audit-exports` page shows:

- Config name
- Destination type
- Enabled or disabled state
- Credential source and status
- Last export status
- Last exported timestamp
- Manual dry-run and run buttons

It does not show raw tokens, secret refs, or destination secrets.

## Production recommendations

- Use HTTPS destinations only.
- Prefer destination-side authentication even for generic webhooks.
- Start with low `max_batch_size` values while validating downstream parsing.
- Monitor `failed` and `retry_exhausted` export jobs.
- Keep downstream SIEM retention and RBAC aligned with the sensitivity of audit data, even though AgentGate exports sanitized views only.
- If you use worker mode, run at least one dedicated worker process.
- Schedule export runs externally until AgentGate gains a built-in recurring scheduler.

## Limitations

- There is no built-in recurring scheduler yet.
- There is no destination verification handshake or signed webhook flow yet.
- There is no dead-letter queue or immutable archival guarantee yet.
- Severity filters are inferred at export time rather than stored as a first-class audit-event column.
- `custom_placeholder` is an extension point, not a specialized adapter.
