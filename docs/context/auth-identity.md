# Auth And Identity Context

## 1. Purpose

This file covers local auth, JWT and cookie session behavior, tenant-scoped OIDC, minimal SCIM provisioning, user lifecycle controls, and related identity surfaces.

## 2. Main files/directories

- `apps/api/app/api/routes/auth.py`, `users.py`, `scim.py`, `agents.py`
- `apps/api/app/services/auth_service.py`, `oidc_service.py`, `oidc_provider.py`, `user_service.py`, `scim_service.py`
- `apps/api/app/api/deps.py`, `apps/api/app/security/browser_sessions.py`, `apps/api/app/core/security.py`
- `apps/api/app/models/user.py`, `oidc_config.py`, `api_key.py`, `tenant.py`
- `apps/api/app/schemas/auth.py`, `agent.py`, `user.py`, `scim.py`
- `apps/web/app/login/page.tsx`, `apps/web/app/users/page.tsx`, `apps/web/app/agents/[id]/page.tsx`, `apps/web/hooks/use-session.ts`, `apps/web/lib/session.ts`
- `docs/security/sso-oidc.md`, `docs/security/identity-lifecycle.md`, `docs/security/scim.md`, `docs/security/agent-api-keys.md`

## 3. Current capabilities

- Local bootstrap and email/password login for development and initial operator setup
- JWT-authenticated operator APIs with current-user reload checks
- Optional HttpOnly cookie session mode for browser clients with CSRF enforcement on unsafe methods
- Optional tenant-scoped OIDC browser login with state, nonce, callback, and exchange-ticket flow
- Optional tenant-scoped SCIM v2 `/Users` foundation for list, get, create, replace, patch, and `active=false` deprovisioning
- JIT OIDC user provisioning and role mapping
- Tenant-scoped user listing, safe profile edits, deactivation, and reactivation
- Agent API key creation, metadata-only listing, last-used tracking, and revoke flow with one-time raw secret display at creation
- Role-scoped onboarding visibility for owner, admin, and security reviewer users, with narrow owner/admin-only onboarding actions
- Owner-lockout protection and revocation of agent API keys created by deactivated users

## 4. Critical invariants / must-not-break rules

- Every authenticated request must continue re-checking `User.is_active`.
- Token mode must remain available for local development and machine-style bearer clients.
- Cookie mode must keep JWTs out of the browser response body, keep cookies `HttpOnly`, and require CSRF on unsafe browser requests.
- Deactivated users must stay blocked for local login, OIDC exchange, and future JWT-authenticated requests.
- The last active owner in a tenant must not be demoted or deactivated.
- SCIM must remain bearer-token-only, must not accept browser session auth, and must map each token to exactly one tenant.
- SCIM must not create or promote tenant owners in the current build.
- Onboarding actions must not bypass role checks, create owners implicitly, or weaken existing owner-protection rules.
- Agent API keys must remain hashed at rest, metadata-only after creation, and tied to one agent plus one tenant.
- Raw agent API key secrets may be returned once at creation time, but they must not be retrievable later through browser or API list surfaces.
- Raw OIDC client secrets, JWTs, API keys, or GitHub App private keys must never be stored in database config or exposed in APIs.
- OIDC must keep issuing a short-lived exchange ticket first, not the final AgentGate JWT directly to the callback URL.

## 5. Security boundaries

- Identity remains tenant-scoped.
- Browser cookie auth is a transport option for the same stateless JWT, not a separate trust domain or session store.
- OIDC config is safe metadata plus secret references, not raw secret storage.
- SCIM bearer tokens are deployment-managed secret references that bind exactly one tenant and never rely on browser cookies.
- Agent API keys are hashed at rest, scoped at runtime, and only revealed once at creation time.
- User lifecycle state is enforced in the normal auth path rather than a separate session invalidation system.

## 6. Known limitations

- Local auth remains enabled alongside OIDC.
- Cookie mode remains stateless, so deactivation is enforced by current-user lookup rather than a server-side session revocation list.
- SCIM is intentionally minimal: no Groups API, no role sync, and no tenant-admin token management UI or CRUD API.
- There is no tenant-admin CRUD UI or API for OIDC config in the current build.
- `secret_ref:` and `vault:` references are modeled for SCIM and OIDC, but still fail closed unless env-backed.

## 7. Relevant tests

- `apps/api/app/tests/test_oidc_auth.py`
- `apps/api/app/tests/test_scim.py`
- `apps/api/app/tests/test_session_hardening.py`
- `apps/api/app/tests/test_user_lifecycle.py`
- `apps/api/app/tests/test_api_keys.py`
- `apps/web/e2e/login.spec.ts`
- `apps/web/e2e/auth.setup.ts`

## 8. When future Codex sessions should read this file

Read this before editing login flows, JWT handling, OIDC or SCIM behavior, user lifecycle APIs, owner protections, or API key behavior.
