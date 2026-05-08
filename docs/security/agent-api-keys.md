# Agent API Keys

Agent API keys let a non-human caller invoke the governed gateway path for a specific agent without using a browser login flow.

The current build keeps that lifecycle intentionally narrow and safety-focused.

## Lifecycle Summary

1. An owner, admin, or the owning developer creates a key for one agent.
2. AgentGate returns the raw secret once in the create response.
3. AgentGate stores only the key hash plus safe metadata at rest.
4. Later list views return metadata only, never the raw secret again.
5. Gateway requests update `last_used_at` when the key is accepted.
6. Expired or revoked keys are rejected before gateway execution begins.
7. Revocation stops future use immediately and writes an audit event.

## Browser UI Behavior

The agent detail page provides a minimal lifecycle surface:

- list key summaries
- show status, scope, expiration, and last-used metadata
- create a new key with a label, scope, and expiry choice
- reveal the raw secret once immediately after creation
- revoke an existing key with confirmation

The browser UI must not:

- retrieve old raw secrets
- display hashed key material
- expose secret refs, connector credentials, or payload data
- persist newly created raw secrets in local storage or URLs

## Role And Access Model

- `owner` and `admin` can review, create, and revoke keys for any agent in their tenant
- `security_reviewer` can review key summaries but cannot create or revoke keys
- `developer` can review, create, and revoke keys only for agents they own
- `viewer` and `approver` do not get API-key lifecycle access

Tenant isolation still applies to every key route and every browser view.

## What The API Stores And Returns

Stored at rest:

- hash of the key
- key id
- label
- tenant and agent binding
- creator id
- scopes
- created, expiry, last-used, and revoked timestamps

Returned in later list responses:

- key id
- label
- safe prefix
- scope list
- created timestamp
- creator id
- expiry timestamp
- last-used timestamp
- revoked timestamp
- computed active state

Not returned after creation:

- raw key secret
- hashed key value
- any reusable secret material

## Recommendations

- prefer short-lived expirations for non-human integrations
- treat the one-time create response like a credential handoff moment and copy it into a proper secret store immediately
- revoke unused, orphaned, or suspicious keys instead of leaving them active
- review `last_used_at` when investigating stale or unexpectedly active automation
- prefer creating a new key and retiring the old one over keeping a long-lived key in place indefinitely

## Limitations

- the current scope set is intentionally narrow and centers on `gateway:invoke`
- there is no browser-side bulk rotate or bulk revoke workflow
- there is no per-key IP allowlist or signed-request scheme yet
- non-expiring keys are still possible for owner or admin operators, so deployment policy should treat them as exceptions rather than defaults
- user reactivation does not restore previously revoked user-created agent API keys
