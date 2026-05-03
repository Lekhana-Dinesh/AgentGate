# Payload Protection

## Purpose

AgentGate needs enough execution state to support approvals, replay, and connector execution, but a runtime governance product should not keep raw secrets casually exposed in database records or API responses.

This payload protection layer adds a production-grade foundation for:

- field-level protection of sensitive execution arguments
- sanitized payload rendering for API and UI consumers
- trusted-path decryption only when execution actually needs original values
- enforced retention purge for expired protected execution payloads
- key metadata capture so manual rotation and future rewrap workflows can reason about historical ciphertext safely

## What Is Protected

Sensitive execution-argument fields are protected before the `ToolCall` record is committed.

Examples include:

- `token`
- `access_token`
- `authorization`
- `password`
- `secret`
- `api_key`
- `private_key`
- `client_secret`
- `refresh_token`
- `bearer`
- `cookie`
- `set_cookie`

Context-sensitive content fields can also be protected, including:

- email body or attachment-style fields when the tool call is handling `confidential`, `internal`, `internal_pricing`, or `financial` data
- GitHub comment or issue bodies when sensitive internal classifications are present
- Slack-style text fields when secret-like token content is detected

## Envelope Format

Protected fields are stored as identifiable envelopes:

```json
{
  "__agentgate_encrypted__": true,
  "alg": "local-fernet-v1",
  "algorithm": "local-fernet-v1",
  "ciphertext": "...",
  "key_ref": "configured-env",
  "key_version": "1",
  "provider": "env",
  "created_at": "2026-05-03T12:34:56Z"
}
```

These envelopes are internal storage details. Public APIs and UI views do not return them directly.

## What API and UI Consumers See

AgentGate exposes sanitized payload views only:

- `ToolCall.request_payload.arguments` is a sanitized operator-facing summary
- `ToolCall.request_payload.execution_arguments` is never returned through the public API
- traces, approvals, audit feeds, and Slack notifications use sanitized payload summaries only

Visible placeholders include:

- `[REDACTED]`
- `[PROTECTED]`

## Trusted Execution Path

Only trusted backend execution paths decrypt protected fields:

- immediate adapter execution inside the gateway
- approved execution inside the approval workflow

If a protected payload is corrupted or cannot be decrypted, execution fails closed with `protected_payload_invalid`.

## Configuration

Set a Fernet key with:

```bash
AGENTGATE_PAYLOAD_ENCRYPTION_KEY=your-generated-fernet-key
```

Optional explicit secret-reference wiring:

```bash
AGENTGATE_KEY_PROVIDER=env
AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY
AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF=payload-primary
AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION=2026-05
```

Optional decrypt-only rotation scaffolding:

```bash
AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS='{"configured-env":"env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS"}'
```

You can generate one with:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

Behavior by environment:

- `development` and `test`: if the key is unset, AgentGate uses a deterministic local fallback key so local setup and tests still work
- non-development environments: the key is required and startup fails if it is missing

## Retention Foundation

Each `ToolCall` now carries payload-protection metadata:

- `payload_protection_version`
- `payload_retention_class`
- `payload_expires_at`
- `payload_redaction_status`

Current behavior:

- retention classes are `standard`, `short_lived`, `extended`, and `legal_hold`
- expired protected payloads can be previewed or purged through the retention API and async job layer
- purge redacts `request_payload.execution_arguments` only and preserves sanitized operator-facing `request_payload.arguments`, decision data, trace references, and audit references
- `legal_hold` payloads are never purged automatically
- purge never decrypts archived values

## Current Limitations

- Encryption is environment-scoped, not tenant-scoped
- There is no cloud KMS-backed provider implementation yet
- There is no automatic re-encryption or rewrap workflow yet
- Trace and audit metadata are sanitized, not encrypted, because they are not part of the execution replay path
- The development/test fallback key is intentionally only a local convenience

## Production Hardening Path

- Replace the env key provider with AWS KMS, GCP KMS, Azure Key Vault, or Vault-backed providers
- Add a manual or queue-backed ciphertext rewrap workflow once key rotation procedures are operationally tested
- Add tenant-level retention policy configuration
- Add stronger per-connector data minimization so fewer raw values ever need to be replayable
