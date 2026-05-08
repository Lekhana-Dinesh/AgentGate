# Identity Lifecycle

## Overview

AgentGate now includes a tenant-scoped identity lifecycle foundation that lets enterprise operators deactivate and reactivate users without replacing the existing local JWT, optional cookie-session browser mode, or optional OIDC login model.

This foundation is intentionally deactivation-first:

- local login still exists
- optional tenant-scoped OIDC still exists
- minimal SCIM user provisioning and deprovisioning now exists
- user lifecycle enforcement happens through the existing current-user checks rather than a separate session store

## User Lifecycle Fields

Each user record now carries:

- `is_active`
- `provisioned_source`
- `deactivated_at`
- `deactivation_reason`

`status` is exposed through API responses as a safe derived value:

- `active`
- `deactivated`

Current `provisioned_source` values:

- `local`
- `oidc`
- `scim`
- `system`

`local`, `oidc`, and `scim` are exercised in the current build. `system` remains a platform-owned lifecycle marker.

## Enforcement Model

When a user is deactivated:

- local login fails closed
- OIDC exchange fails closed
- previously issued JWTs stop working on the next authenticated request
- existing cookie-authenticated browser sessions also stop working on the next authenticated request
- tenant APIs reject the user because current-user resolution reloads the user row and checks `is_active`
- privileged flows such as approvals, settings access, and gateway usage are blocked
- active agent API keys created by that user are revoked

Reactivation restores the user account, but it does not restore revoked agent API keys.

## Admin APIs

Current lifecycle endpoints:

- `GET /v1/users`
- `GET /v1/users/{user_id}`
- `PATCH /v1/users/{user_id}`
- `POST /v1/users/{user_id}/deactivate`
- `POST /v1/users/{user_id}/reactivate`

RBAC:

- `owner`, `admin`, and `security_reviewer` can view users
- `owner` and `admin` can update or change lifecycle state
- only `owner` can manage another owner account or promote a user to owner

Safe update scope today:

- `full_name`
- `role`

Not supported here:

- password reset workflows
- tenant-admin SCIM bearer token issuance or rotation
- tenant-admin OIDC config CRUD
- IdP-driven group sync

## Owner Lockout Protection

AgentGate prevents removing the last active owner in a tenant.

That means the last active owner cannot:

- deactivate themselves
- be deactivated by another operator
- be demoted away from the `owner` role

This protection is enforced server-side in the user lifecycle service.

## OIDC Relationship

OIDC JIT-provisioned or OIDC-bound users are marked with `provisioned_source=oidc`.

Important behavior:

- deactivated users are not auto-reactivated by a later OIDC login
- deactivated users are not auto-escalated by later OIDC role mapping
- OIDC continues to act as an authentication source, not a hidden account-recovery path
- cookie mode is also stateless, so deactivation depends on the same current-user lookup rather than a server-side session revocation table

## SCIM Scope

This build now ships a minimal SCIM v2 `/Users` surface.

What is present:

- tenant-scoped `GET`, `POST`, `PUT`, and `PATCH` support for `/v1/scim/v2/Users`
- SCIM-created users marked with `provisioned_source=scim`
- `active=false` using the same deactivation logic as the admin user APIs
- `active=true` using the same reactivation logic as the admin user APIs
- owner lockout protection and audit logging on SCIM lifecycle changes

What is not present:

- SCIM `Groups`
- SCIM-driven role promotion or owner creation
- per-tenant SCIM bearer token management UI or CRUD APIs
- automatic group membership sync
- broad SCIM filter coverage

## Frontend Surface

The `/users` page provides a minimal operator surface for:

- listing tenant users
- viewing role, status, and provisioning source
- deactivating or reactivating users when RBAC allows it

It intentionally does not expose secrets, raw OIDC subjects, or unsafe config dumps.

## Operational Notes

- Treat deactivation as the supported user offboarding path in the current build.
- Use SCIM for basic provisioning and deprovisioning only. It is not yet a full identity-governance control plane.
- If a deployment requires full SCIM server behavior, tenant-local time-zone-aware lifecycle policies, or group-sync semantics, that should be implemented as a separate follow-on capability rather than folded into the current auth paths.
