# SCIM Provisioning

## Overview

AgentGate includes a minimal SCIM v2 foundation for tenant-scoped user provisioning and deprovisioning.

What this build supports:

- `GET /v1/scim/v2/Users`
- `GET /v1/scim/v2/Users/{id}`
- `POST /v1/scim/v2/Users`
- `PUT /v1/scim/v2/Users/{id}`
- `PATCH /v1/scim/v2/Users/{id}`

This foundation is intentionally narrow. It is designed to integrate with the existing identity lifecycle model, not replace it or claim full identity governance.

## Configuration

SCIM is disabled by default.

Enable it with a tenant-to-token reference mapping:

```env
AGENTGATE_SCIM_TENANT_TOKEN_REFS={"tenant-a":"env:AGENTGATE_SCIM_TOKEN_TENANT_A"}
```

Current token-reference rules:

- use `env:...`, a bare environment variable name, or a future `secret_ref:` / `vault:` placeholder
- do not put literal SCIM bearer tokens directly in config
- do not store SCIM tokens in the database

## Auth Model

- SCIM uses bearer-token authentication only
- SCIM does not use cookie or browser session auth
- each SCIM token must map to exactly one tenant
- token comparison uses constant-time comparison for matched secret values where practical
- SCIM requests are rate limited through the existing control-plane limiter

## Lifecycle Behavior

- SCIM-created users are marked with `provisioned_source=scim`
- new SCIM users default to the `viewer` role
- SCIM cannot create or promote an `owner` in the current build
- `active=false` uses the existing deactivation behavior
- `active=true` uses the existing reactivation behavior
- owner lockout protection still applies
- deactivated users remain blocked for local login, OIDC exchange, cookie sessions, and future JWT-authenticated requests

## Security Properties

- tenant isolation is enforced on every SCIM request
- SCIM changes still emit audit events
- raw SCIM secrets are not returned through APIs or logs
- SCIM reuses the existing user-lifecycle enforcement path instead of introducing a second offboarding model

## Current Limitations

- no full identity-governance surface beyond tenant-scoped `/Users` provisioning and deprovisioning
- no SCIM `Groups` API
- no role sync beyond the fixed default `viewer` role
- no tenant-admin SCIM token issuance or rotation UI
- no external secret-manager implementation beyond env-backed resolution
- filter support is intentionally minimal
- no SAML; OIDC and SCIM remain separate limited identity foundations in the current build
