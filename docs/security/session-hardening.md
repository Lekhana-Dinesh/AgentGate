# Session Hardening

## Overview

AgentGate now supports two browser authentication modes:

- `token`: the existing local-development-friendly bearer JWT flow
- `cookie`: an optional browser-focused mode that stores the same stateless JWT in an HttpOnly cookie and adds CSRF enforcement for unsafe requests

This is a session-hardening foundation, not a full server-side session store.

## What Changes In Cookie Mode

When `AGENTGATE_AUTH_SESSION_MODE=cookie`:

- `POST /v1/auth/login`, `POST /v1/auth/bootstrap`, and `POST /v1/auth/oidc/exchange` set an HttpOnly session cookie
- those endpoints do not return the JWT in the response body
- `GET /v1/auth/me` works with the cookie-backed session
- `POST /v1/auth/logout` clears the session and CSRF cookies
- `GET /v1/auth/csrf-token` returns the current CSRF token for the active browser session

Machine auth still remains separate:

- bearer tokens still work for API clients and automation
- API keys still work for gateway invocation
- CSRF is not required for bearer-token or API-key requests

## CSRF Behavior

AgentGate uses a stateless double-submit style CSRF token:

- login or OIDC exchange returns a signed CSRF token in the response body and stores the same value in a cookie
- the browser client sends that value in `X-CSRF-Token` on unsafe methods such as `POST`, `PATCH`, `PUT`, and `DELETE`
- the server requires the header and cookie to match and validates the signed token against the current session JWT

Safe methods such as `GET`, `HEAD`, and `OPTIONS` do not require CSRF.

## Recommended Production Settings

Recommended browser settings:

- `AGENTGATE_AUTH_SESSION_MODE=cookie`
- `AGENTGATE_COOKIE_SECURE=true`
- `AGENTGATE_COOKIE_SAMESITE=lax`
- `AGENTGATE_CSRF_ENABLED=true`
- `AGENTGATE_COOKIE_DOMAIN` only when you need cross-subdomain cookie sharing
- `AGENTGATE_PUBLIC_APP_URL` and `AGENTGATE_PUBLIC_API_URL` set to the real external HTTPS origins

Validation fails closed outside development and test when:

- cookie mode is enabled without `AGENTGATE_COOKIE_SECURE=true`
- `AGENTGATE_COOKIE_SAMESITE=none` is used without secure cookies
- cookie mode disables CSRF

## Deactivation And Logout

AgentGate remains stateless on purpose:

- logout clears the browser cookies
- deactivated users are still rejected because authenticated requests reload the current user record and enforce `is_active`
- old bearer tokens and old cookies stop working once current-user resolution detects a deactivated account

This means AgentGate does not currently maintain a server-side session revocation table.

## Local Development

Local development can stay on:

- `AGENTGATE_AUTH_SESSION_MODE=token`

That keeps the current simple JWT-in-response flow and avoids extra cookie and CSRF setup while developing locally.

## What This Improves

- keeps browser-session JWTs out of `localStorage`
- uses HttpOnly cookies for browser session transport
- adds a clear CSRF story for unsafe browser actions
- preserves existing bearer and API-key behavior for non-browser clients

## Known Limitations

- this is not a stateful enterprise session-management system
- there is no server-side session inventory, forced remote logout list, or per-session admin console
- cookie mode still relies on the same JWT lifetime and current-user lookup model
- the frontend session model remains intentionally lightweight rather than a full auth framework
