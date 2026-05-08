# SSO And OIDC

## Overview

AgentGate now supports a production-minded OIDC foundation alongside the existing local email/password login flow.

- Local auth remains enabled and is still the default for development and bootstrap workflows.
- OIDC is optional and tenant-scoped.
- Successful OIDC login ends in the same AgentGate JWT model used by the rest of the application.
- OIDC-created or OIDC-bound users are marked with `provisioned_source=oidc` for downstream lifecycle and audit handling.

## Tenant OIDC configuration

Each tenant OIDC config stores:

- `provider_name`
- `issuer_url`
- `client_id`
- `client_secret_env_var`
- `client_secret_ref`
- `redirect_uri`
- `scopes`
- `enabled`
- `allowed_email_domains`
- `role_mapping`

Raw client secrets are not stored in the database.

## Secret reference approach

Current build behavior:

- `client_secret_env_var` is fully supported and is the recommended path today.
- `client_secret_ref` can already use the shared secret-reference syntax such as `env:AGENTGATE_OKTA_CLIENT_SECRET`.
- Placeholder `secret_ref:` and `vault:` values are parsed and fail closed until a real external resolver is added.

## Browser login flow

1. Frontend checks `GET /v1/auth/oidc/{tenant_slug}/config-status`.
2. Browser starts login at `GET /v1/auth/oidc/{tenant_slug}/login`.
3. AgentGate creates a signed state token and nonce, then redirects to the provider authorization endpoint.
4. Provider returns to `GET /v1/auth/oidc/{tenant_slug}/callback`.
5. AgentGate validates state, tenant binding, issuer/audience via the provider abstraction, allowed email domain, and role mapping inputs.
6. AgentGate provisions or updates the tenant user and issues a short-lived exchange ticket.
7. Frontend redeems the exchange ticket at `POST /v1/auth/oidc/exchange` to receive the normal AgentGate JWT.

If a tenant user has already been deactivated through the lifecycle APIs, the OIDC callback or exchange flow fails closed instead of reactivating or re-privileging that account implicitly.

## Role mapping

Current foundation supports:

- Group-to-role mapping
- Claim-value-to-role mapping
- `default_role`

Example shape:

```json
{
  "default_role": "viewer",
  "groups": {
    "agentgate-admins": "admin",
    "agentgate-reviewers": "security_reviewer"
  },
  "claims": {
    "department": {
      "security": "security_reviewer"
    }
  }
}
```

Behavior:

- If a mapping matches, that mapped AgentGate role is used.
- If no mapping matches, new JIT users fall back to `viewer` or the configured `default_role`.
- `owner` is only granted when the mapping explicitly resolves to it.

## Allowed email domains

- If `allowed_email_domains` is empty, domain filtering is not enforced.
- If populated, the OIDC identity email must belong to one of those domains.
- Domain mismatches fail closed and are audited.

## Production hardening checklist

- Set `AGENTGATE_PUBLIC_API_URL` and `AGENTGATE_PUBLIC_APP_URL` correctly for the external deployment.
- Use `client_secret_env_var` only with secrets injected from your runtime or secret manager.
- If you want config shape parity with a future secret-manager deployment, use `client_secret_ref=env:...` rather than storing the secret itself.
- Keep local auth available only as long as your operational model requires it.
- Review role mappings carefully before assigning any privileged roles from broad enterprise groups.
- Treat OIDC role mapping as role resolution only, not as an automatic reactivation path for deactivated accounts.
- Audit `auth.oidc.login.failed` events and investigate repeated domain, state, or token validation failures.
- Prefer HTTPS origins for both API and app before enabling production SSO.

## Current limitations

- Local auth is still present; this is a dual-mode auth model, not a local-auth removal.
- There is no tenant-admin API/UI yet for managing OIDC configs.
- `client_secret_ref` is modeled and env references work, but real external secret-manager adapters are still not implemented in this build.
- There is no SAML, broad SCIM identity-governance coverage, or IdP metadata sync yet.
- The current login route shape effectively assumes one practical active provider path per tenant entrypoint.
