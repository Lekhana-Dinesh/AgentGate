# Frontend Context

## 1. Purpose

This file covers the Next.js admin console, typed API client, and the main operator-facing page structure.

## 2. Main files/directories

- `apps/web/app/`: page routes such as `login`, `onboarding`, `tools`, `approvals`, `jobs`, `audit`, `audit-exports`, `audit-integrity`, `retention`, `scheduled-tasks`, `settings`, `users`, `tool-calls`, and `traces`
- `apps/web/components/`: shared UI and layout components
- `apps/web/lib/api.ts`: typed API client
- `apps/web/lib/session.ts`: browser session storage helpers and cookie-session markers
- `apps/web/types/api.ts`: frontend API contracts
- `apps/web/hooks/use-session.ts`: login, logout, token, and cookie-session hydration
- `apps/web/hooks/use-authed-query.ts`: common authenticated data-fetching pattern
- `apps/web/e2e/`: Playwright smoke coverage for login, navigation, and core operator surfaces

## 3. Current capabilities

- Admin-console-style protected pages for the major operator workflows
- Local login plus OIDC discovery and exchange-ticket handling on the login page
- Optional cookie-session browser auth support without storing JWTs in localStorage
- Agent detail view with API key lifecycle review, one-time post-create key display, and revoke controls for authorized operators
- Policy management page with policy review, safe enable or disable controls for owner or admin roles, guided starter-template creation, and pilot policy-pack review guidance
- Policy management page now also includes a dry-run simulation panel for owner, admin, and security reviewer roles so operators can test likely policy outcomes before changing live state
- Typed client calls for audit export, audit integrity, scheduled tasks, users, settings, jobs, and other control-plane APIs
- Safe browser controls for owner/admin operators to enable or disable scheduled tasks, enable or disable audit exports, run those workflows manually, and launch retention dry-runs without exposing secrets
- Minimal but practical status pages for retention, audit checkpoints, and operator health
- A first-run onboarding page and dashboard card that summarize safe tenant setup status and route operators into the existing admin surfaces
- A dedicated tools/connectors page that summarizes safe connector posture, supports guided non-secret metadata templates for GitHub, Jira, MCP, and mock connectors, and keeps secret-backed config out of the browser
- Playwright smoke coverage for login, key navigation flows, onboarding, settings, tools, users, scheduled tasks, audit integrity, audit exports, and retention

## 4. Critical invariants / must-not-break rules

- Do not expose secrets, raw secret refs, decrypted payloads, or unsafe audit metadata in the browser.
- Keep using the typed API client and shared page patterns rather than creating ad hoc fetch logic everywhere.
- Preserve clear loading, error, and empty states for operational pages.
- Keep the UI as an admin console, not a consumer chat product.
- Agent API key secrets may appear in the browser only once immediately after creation and must never be written into local storage, URLs, logs, or later list responses.
- Keep onboarding as a safe status-and-navigation layer, not a full setup wizard or secret editor.
- Keep the tools page as a narrow safe-metadata layer, not a full connector-management or secret-editing UI.
- Keep policy authoring narrow: structured starter templates, safe enable or disable, and JSON preview only unless the backend contract deliberately expands.
- Keep policy simulation narrow and advisory: reuse the typed API client, do not echo secrets or raw payloads back into the browser, and do not turn the page into a general execution console.
- Keep scheduled-task, audit-export, and retention browser controls narrow: non-secret toggles, manual runs, and dry-runs only.
- When backend contracts change, keep `lib/api.ts`, `types/api.ts`, and affected pages aligned.

## 5. Security boundaries

- The browser only receives sanitized API responses.
- The login flow must keep using the backend-issued JWT or OIDC exchange-ticket path, not direct browser-side secret handling.
- In cookie mode, the frontend must treat the browser session and CSRF token as separate concerns and must not reintroduce raw JWT storage.
- Agent key management is a narrow exception to the usual read-only posture: creation can reveal a raw secret once, but the frontend still must not persist or re-fetch that secret.
- Settings, audit, retention, and user pages are privileged surfaces and must remain safe-summary oriented.
- Owner and admin roles can mutate only the narrow non-secret operational controls that already exist in the backend APIs; security reviewers stay read-only in the browser even when they can inspect the same pages.
- Policy review is broader than policy mutation: the browser may show policy state to more roles than it allows to edit, but only owner and admin roles should get mutation controls.
- Policy simulation is broader than policy mutation too: security reviewers may use the dry-run surface, but developer, approver, and viewer roles should not gain simulation access.
- Onboarding must continue returning only safe tenant setup posture. It must not expose raw connector config, token env vars, secret refs, or decrypted payloads.
- Tool and connector pages may expose narrow non-secret metadata controls, but they must stay on the safe side of the boundary and must not reintroduce raw config, secret refs, env-var token names, auth emails, or secret-bearing URLs.
- Frontend code should not become a secret editor for deployment configuration.

## 6. Known limitations

- The frontend is intentionally operational and minimal rather than deeply polished.
- Browser E2E coverage is still intentionally narrow and Chromium-only, even though it now covers more operator pages.
- There is no visual regression suite.
- External integrations such as GitHub, Slack, AWS KMS, and OIDC are not comprehensively exercised in browser automation.
- Browser auth is still intentionally simple and does not include a richer session-management UI or multi-tab coordination model.
- There is still no dedicated browser UI for wiring real connector secrets; the tools page now supports narrow non-secret metadata create and edit flows for a small connector set, but it is still not a full secret-onboarding or generic tool-admin surface.
- The API key surface is intentionally narrow: it supports create, list, and revoke only, and there is no bulk rotation or cross-agent management workflow.
- Operational browser controls remain intentionally narrow: scheduled-task creation and detailed audit-export destination editing still belong to APIs or deployment workflows, not the settings UI.
- Policy management remains intentionally narrow: no drag ordering, no broad free-form browser editor, and no browser-side apply of the pilot policy pack.
- The policy simulation panel is intentionally minimal: it helps operators review simulated outcomes, but it does not prove live connector success or replace deeper script-driven policy analysis.

## 7. Relevant tests

- `apps/web/e2e/login.spec.ts`
- `apps/web/e2e/workspace.spec.ts`
- `apps/web/e2e/operator-surfaces.spec.ts`
- `apps/web/e2e/auth.setup.ts`
- Frontend build in `.github/workflows/ci.yml`

## 8. When future Codex sessions should read this file

Read this before editing the web UI, page routing, typed API client, frontend auth behavior, or Playwright coverage.
