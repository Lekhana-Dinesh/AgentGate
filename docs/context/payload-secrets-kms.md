# Payload, Secrets, And KMS Context

## 1. Purpose

This file covers payload protection, secret-reference resolution, key management, and AWS KMS-backed envelope behavior.

## 2. Main files/directories

- `apps/api/app/security/payload_protection.py`
- `apps/api/app/security/key_management.py`
- `apps/api/app/security/secret_references.py`
- `apps/api/app/services/payload_service.py`
- `apps/api/app/models/tool_call.py`
- `apps/api/app/api/routes/security.py`
- `apps/api/app/tools/github_auth.py`
- `docs/security/payload-protection.md`
- `docs/security/key-and-secret-management.md`

## 3. Current capabilities

- Field-level protection of sensitive execution arguments before `ToolCall` persistence
- Sanitized public payload views with protected execution payloads hidden from API and UI consumers
- Trusted-path decryption only during actual execution
- Env-backed provider for local and simple deployments
- AWS KMS-backed provider that stores wrapped data keys in envelopes rather than plaintext key material
- Shared secret-reference resolver for GitHub, Slack, OIDC, payload keys, and audit-anchor credentials
- Safe `GET /v1/security/key-status` operator visibility
- Manual rotation scaffolding with active key refs and additional decrypt-only refs

## 4. Critical invariants / must-not-break rules

- Do not expose decrypted payloads, raw secret values, or raw envelope internals in APIs, logs, docs, or UI pages.
- Unsupported `secret_ref:` and `vault:` patterns must keep failing closed until implemented for real.
- Trusted execution paths may decrypt only when a connector actually needs the original value.
- Retention purge must redact without decrypting archived execution payloads.
- Production validation must keep rejecting missing or unsafe key configuration.

## 5. Security boundaries

- Payload protection separates operator-visible summaries from replayable execution state.
- Secret injection stays outside the database.
- AWS KMS mode protects per-envelope data keys while keeping ciphertext local to AgentGate storage.
- Key-status and readiness surfaces expose safe metadata only.

## 6. Known limitations

- Encryption is environment-scoped, not tenant-scoped.
- Only `env` and `aws_kms` providers exist today.
- No automatic rewrap or key rotation workflow exists yet.
- External secret-manager resolvers are not implemented beyond env-backed behavior.

## 7. Relevant tests

- `apps/api/app/tests/test_payload_protection.py`
- `apps/api/app/tests/test_key_and_secret_management.py`
- `apps/api/app/tests/test_github_connector.py`
- `apps/api/app/tests/test_operational_hardening.py`

## 8. When future Codex sessions should read this file

Read this before editing payload serialization, secret reference parsing, key-provider config, AWS KMS behavior, or any flow that touches encrypted execution arguments.
