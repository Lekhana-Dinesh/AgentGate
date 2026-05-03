# Key And Secret Management

## Overview

AgentGate now has a shared foundation for:

- payload-protection key selection and envelope metadata
- secret resolution for GitHub, Slack, and OIDC credentials
- non-sensitive operator visibility through `GET /v1/security/key-status`

The current implementation is intentionally conservative:

- local and production-friendly env-backed operation works today
- unsupported secret-manager references fail closed
- cloud KMS and secret-manager providers are documented future paths, not silently partial implementations

## Key provider model

Current provider:

- `env`

Key provider interface concepts:

- `get_active_key(purpose, tenant_id optional)`
- `get_key_by_ref(key_ref, purpose, tenant_id optional)`
- key metadata: `key_ref`, `provider`, `version`, `purpose`, `status`

Current supported purpose:

- `payload_protection`

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

## Payload encryption envelopes

New envelopes include non-sensitive key metadata:

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

Backward compatibility:

- older envelopes that only contain `alg`, `ciphertext`, and `key_ref` still decrypt
- decryption resolves key material by `key_ref`

## Rotation model

Current rotation scaffolding is manual and intentionally conservative.

Use:

- one active key ref for new encryption
- optional additional decrypt-only refs for older envelopes

Example:

```bash
AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF=payload-2026-05
AGENTGATE_PAYLOAD_ENCRYPTION_KEY=<new-fernet-key>
AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS='{"configured-env":"env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS"}'
```

This means:

- new payloads encrypt with `payload-2026-05`
- legacy envelopes referencing `configured-env` can still decrypt

What is not implemented yet:

- automatic re-encryption
- bulk rewrap jobs
- tenant-scoped key hierarchies
- cloud KMS-backed key material

## Key status endpoint

`GET /v1/security/key-status`

Returns non-sensitive status only:

- provider type
- configured purposes
- active key ref
- active key version
- configured key refs
- warnings such as missing or unresolved decrypt-only keys

Restricted roles:

- `owner`
- `admin`
- `security_reviewer`

## Production recommendations

- set an explicit Fernet key before any shared-environment deployment
- prefer explicit env secret references so production config matches the future secret-manager wiring pattern
- keep prior decrypt-only refs during manual rotations until historical ciphertext is rewrapped or allowed to expire under retention
- monitor `GET /v1/security/key-status` and failed decrypt events
- pair key rotation planning with retention windows so old ciphertext can be safely phased out

## Future provider path

Planned provider shapes:

- AWS KMS
- GCP KMS
- Azure Key Vault
- HashiCorp Vault

Intended future additions:

- provider-specific key clients
- external secret-manager resolver adapters
- rewrap jobs
- tenant-scoped key policies
- key-usage telemetry and rotation audits

## Current limitations

- only the env-backed provider is implemented today
- `secret_ref:` and `vault:` references are placeholders and fail closed
- no automatic rewrap or scheduled rotation workflow exists yet
- payload keys are environment-scoped, not tenant-scoped
