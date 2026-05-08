# Onboarding

## Purpose

AgentGate's onboarding surface is a safe first-run checklist for tenant operators.

It helps a new admin, owner, or security reviewer answer:

- Is the tenant basically configured?
- What should I open next?
- Can I safely run the first governed workflow?

It does not replace the existing admin APIs or deployment docs.

## First-Run Flow

1. Sign in with an owner, admin, or security reviewer account.
2. Open `/onboarding`.
3. Review whether the tenant has:
   - an active owner
   - at least one agent
   - at least one tool or connector
   - at least one policy
   - approval coverage
   - audit-integrity visibility
4. Follow the recommended next step and jump into the linked page.
5. When the tenant is ready, run the first governed workflow from `/demo` or through the gateway APIs.

## What Onboarding Does

- Returns tenant-scoped safe setup status through `GET /v1/onboarding/status`
- Points operators to the existing product pages for agents, tools, policies, settings, audit integrity, and demo flow
- Lets owner or admin users dismiss the checklist if it becomes noise
- Lets owner or admin users reset the walkthrough state
- Optionally creates one starter demo policy if it does not already exist

## What Onboarding Does Not Do

- It does not create connectors that require secrets.
- It does not inject or edit secret material.
- It does not create fake external integrations.
- It does not replace the existing `/v1/agents`, `/v1/tools`, `/v1/policies`, `/v1/users`, or `/v1/settings` APIs.
- It does not guarantee that the tenant is production-ready.

## Seeded Demo Data

With `python -m app.db.seed` or `docker compose exec api python -m app.db.seed`, the demo tenant already has:

- a seeded admin and reviewer
- a governed agent
- seeded tools and connectors
- seeded policies
- the demo workflow at `/demo`

For that path, onboarding is mainly a quick status check and navigation layer before the live walkthrough.

## Demo Policy

The optional onboarding demo policy is intentionally simple:

- name: `Onboarding Demo - Require Approval For High-Risk Actions`
- effect: require approval for `risk_score > 70`

This is a starter policy for evaluation workflows, not a universal production policy set.

## Security Notes

- Onboarding returns safe status only.
- It must not expose raw connector config, env-var token names, secret refs, decrypted payloads, or unsafe audit metadata.
- View access is limited to owner, admin, and security reviewer roles.
- Dismiss, reset, and demo-policy actions are limited to owner and admin roles.

## Limitations

- There is no full setup wizard.
- There is no browser UI for wiring real connector secrets.
- The tools page is visibility-only. Operators still use the existing `/v1/tools` API and deployment-side secret injection for real connector creation or secret changes.
- Demo docs still live in `docs/demo/` in the repository and are not fully rendered inside the dashboard UI.
