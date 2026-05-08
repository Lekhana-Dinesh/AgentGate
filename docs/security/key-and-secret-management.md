# Key And Secret Management

## Overview

AgentGate now has a shared foundation for:

- payload-protection key selection and envelope metadata
- local env-backed secret handling for GitHub, Jira, MCP, Slack, and OIDC credentials
- non-sensitive operator visibility through `GET /v1/security/key-status`

The implementation stays intentionally conservative:

- `env` remains the default provider for development and simple deployments
- `aws_kms` is available for production-minded payload protection
- unsupported secret-manager references still fail closed
- broader cloud and external secret-manager providers remain future work

## Key provider model

Supported providers today:

- `env`
- `aws_kms`

Current supported purpose:

- `payload_protection`

Provider interface concepts:

- `get_active_key(purpose, tenant_id optional)`
- `get_key_by_ref(key_ref, purpose, tenant_id optional)`
- `get_purpose_status(purpose, tenant_id optional)`
- `generate_data_key(...)` and `decrypt_data_key(...)` for providers that use wrapped per-envelope data keys

Key metadata tracked through the abstraction:

- `key_ref`
- `provider`
- `version`
- `purpose`
- `status`
- `region` when relevant and safe to show

## Local development behavior

Recommended simple setup:

```bash
AGENTGATE_KEY_PROVIDER=env
AGENTGATE_PAYLOAD_ENCRYPTION_KEY=<fernet-key>
```

Optional explicit ref wiring:

```bash
AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY
AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF=payload-primary
AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION=2026-05
```

Development and test fallback:

- if no payload key is configured, AgentGate uses a deterministic local fallback key
- this fallback exists only to keep local setup and tests simple
- never rely on the fallback outside `development` or `test`

## AWS KMS production behavior

Production-minded KMS setup:

```bash
AGENTGATE_KEY_PROVIDER=aws_kms
AGENTGATE_AWS_REGION=us-east-1
AGENTGATE_AWS_KMS_KEY_ID=alias/agentgate/payload
AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF=payload-kms-2026-05
AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION=2026-05
```

What this provider does:

- asks AWS KMS to generate a 32-byte data key per protected payload field
- converts that plaintext data key into a Fernet-compatible symmetric key locally
- encrypts the payload value locally with that Fernet key
- stores only payload ciphertext plus the KMS-wrapped encrypted data key in the envelope

What it does not do:

- it does not store plaintext key material in the database
- it does not expose AWS credentials, wrapped data keys, or decrypted payloads in APIs
- it does not automatically rewrap old ciphertext after key rotation

Recommended IAM permissions for the runtime principal:

- `kms:DescribeKey`
- `kms:GenerateDataKey`
- `kms:Decrypt`

Scope those permissions to the specific KMS key or alias used for payload protection.

## LocalStack and test support

For LocalStack or similar isolated testing:

```bash
AGENTGATE_KEY_PROVIDER=aws_kms
AGENTGATE_AWS_REGION=us-east-1
AGENTGATE_AWS_KMS_KEY_ID=alias/agentgate/payload
AGENTGATE_AWS_KMS_ENDPOINT_URL=http://localhost:4566
```

Notes:

- `AGENTGATE_AWS_KMS_ENDPOINT_URL` is optional and intended for local testing
- backend tests mock the KMS client and do not require real AWS access
- readiness and key-status surface that a custom KMS endpoint is configured without exposing credentials

## Secret reference pattern

Supported syntax today:

- `env:NAME`
- bare environment variable names where legacy env-var fields already exist, such as GitHub `token_env_var`

Parsed but not implemented yet:

- `secret_ref:...`
- `vault:...`

Behavior:

- env references resolve from the current process environment
- unsupported reference types fail closed
- raw secret values are never returned in APIs, audits, traces, or error details

## GitHub connector secret handling

GitHub connector auth now has two safe configuration paths:

- `auth_mode=env_pat` or `auth_mode=env_token`
- `auth_mode=github_app`

Env-token mode:

- stores only `token_env_var` in tool config
- resolves the token through the shared secret resolver
- keeps local development simple

GitHub App mode:

- stores `app_id` and `installation_id` in tool config
- stores only `private_key_env_var` or `private_key_secret_ref` in tool config
- signs a short-lived GitHub App JWT locally
- exchanges that JWT for a GitHub installation token
- caches the installation token in memory only until expiry or refresh

Safe GitHub App private key patterns:

```json
{
  "auth_mode": "github_app",
  "app_id": "12345",
  "installation_id": "67890",
  "private_key_env_var": "AGENTGATE_GITHUB_APP_PRIVATE_KEY"
}
```

or:

```json
{
  "auth_mode": "github_app",
  "app_id": "12345",
  "installation_id": "67890",
  "private_key_secret_ref": "env:AGENTGATE_GITHUB_APP_PRIVATE_KEY"
}
```

Current limitation:

- `private_key_secret_ref` can safely store `env:...`, `secret_ref:...`, or `vault:...`
- only env-backed resolution is implemented today
- unresolved or unsupported secret-reference types fail closed at runtime

## Payload encryption envelopes

Env-backed envelopes look like this:

```json
{
  "__agentgate_encrypted__": true,
  "alg": "local-fernet-v1",
  "ciphertext": "...",
  "key_ref": "payload-primary",
  "key_version": "2026-05",
  "provider": "env",
  "created_at": "2026-05-03T12:34:56Z"
}
```

AWS KMS-backed envelopes add wrapped data-key metadata:

```json
{
  "__agentgate_encrypted__": true,
  "alg": "local-fernet-v1",
  "ciphertext": "...",
  "key_ref": "payload-kms-2026-05",
  "key_version": "2026-05",
  "provider": "aws_kms",
  "encrypted_data_key": "...",
  "encrypted_data_key_algorithm": "aws-kms-generate-data-key",
  "created_at": "2026-05-03T12:34:56Z"
}
```

Backward compatibility:

- older env-backed envelopes that only contain `alg`, `ciphertext`, and `key_ref` still decrypt
- decryption resolves legacy env envelopes by `key_ref`
- AWS KMS envelopes decrypt through their stored wrapped data key, not by storing reusable plaintext keys

## Rotation model

Current rotation scaffolding is manual and intentionally conservative.

For env-backed rotation:

- use one active key ref for new encryption
- keep optional additional decrypt-only refs for older envelopes

Example:

```bash
AGENTGATE_KEY_PROVIDER=env
AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF=payload-2026-05
AGENTGATE_PAYLOAD_ENCRYPTION_KEY=<new-fernet-key>
AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS='{"payload-2026-04":"env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS"}'
```

For migration from env to AWS KMS:

- switch the active provider to `aws_kms`
- keep legacy env key refs in `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS` until old ciphertext ages out or is manually rewrapped later

Example:

```bash
AGENTGATE_KEY_PROVIDER=aws_kms
AGENTGATE_AWS_REGION=us-east-1
AGENTGATE_AWS_KMS_KEY_ID=alias/agentgate/payload
AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF=payload-kms-2026-05
AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS='{"payload-env-2026-04":"env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS"}'
```

What is not implemented yet:

- automatic re-encryption
- bulk rewrap jobs
- tenant-scoped key hierarchies
- KMS alias or CMK lifecycle orchestration

## Key status endpoint

`GET /v1/security/key-status`

Returns non-sensitive status only:

- provider type
- provider readiness
- configured purposes
- active key ref
- active key version
- configured key refs
- AWS region when applicable
- warnings such as missing config, unavailable KMS, or unresolved decrypt-only keys

Restricted roles:

- `owner`
- `admin`
- `security_reviewer`

## Production recommendations

- prefer `AGENTGATE_KEY_PROVIDER=aws_kms` for shared or production-like environments
- use a stable KMS alias where possible so the operator-facing `key_ref` remains readable
- keep prior decrypt-only refs during manual rotations until historical ciphertext is rewrapped or allowed to expire under retention
- monitor `GET /v1/security/key-status`, `GET /ready`, and failed decrypt events
- pair key rotation planning with retention windows so old ciphertext can be safely phased out
- keep GitHub, Jira, MCP, Slack, and OIDC secrets env-backed or behind a future secret manager; do not store raw connector credentials in the database

## Future provider path

Planned provider shapes:

- GCP KMS
- Azure Key Vault
- HashiCorp Vault

Intended future additions:

- provider-specific client health probes beyond basic readiness
- external secret-manager resolver adapters
- rewrap jobs
- tenant-scoped key policies
- key-usage telemetry and rotation audits

## Current limitations

- AWS KMS is the only cloud-backed provider implemented today
- GitHub App private keys can be referenced safely, but only env-backed secret resolution is implemented today
- `secret_ref:` and `vault:` references are placeholders and fail closed
- no automatic rewrap or scheduled rotation workflow exists yet
- payload keys are environment-scoped, not tenant-scoped
- AWS KMS readiness verifies safe key availability but does not prove every downstream policy or IAM edge case before first real encrypt/decrypt
