# Admin Settings

## Overview

AgentGate now includes a tenant-authenticated operator settings surface:

- frontend page: `/settings`
- backend overview endpoint: `GET /v1/settings/overview`

This surface is intentionally read-only in the current build.

Its purpose is to help tenant owners, tenant admins, and security reviewers confirm whether key control-plane settings are healthy without exposing secrets, raw config dumps, or protected payload content.

The page can now link operators into narrower browser-managed operational surfaces for:

- scheduled task enable or disable
- scheduled task run-now
- audit export enable or disable
- audit export manual run
- retention dry-run launch

Those operational actions do not happen on `/settings` itself. The settings page remains a summary and navigation surface.

## What It Shows

The settings overview combines safe summaries for:

- tenant profile status
- OIDC / SSO status
- GitHub connector status
- Slack notification status
- audit export status
- retention status
- scheduled tasks status
- key provider status
- rate limiter status
- readiness and metrics links

Some of these are tenant-scoped records such as audit exports and scheduled tasks.
Others are deployment-level statuses, such as key-provider or rate-limiter health, rendered inside the same tenant-authenticated page because operators usually need both views together.

The settings page also links to:

- `/scheduled-tasks`
- `/audit-exports`
- `/retention`
- `/tools`
- `/ready`
- `/metrics`

## Security Model

The settings overview must not expose:

- raw GitHub tokens
- Slack bot tokens
- OIDC client secrets
- GitHub App private keys
- decrypted payloads
- raw secret references or unsafe config dumps

The page and API return only:

- safe booleans such as whether credentials are present
- safe provider names
- safe readiness states
- bounded counts
- sanitized hostnames or labels where useful

The linked operational pages must still avoid:

- secret refs
- env-var token names
- raw connector config
- private keys
- destination tokens
- real purge payload contents

## Access Control

Read access is restricted to:

- `owner`
- `admin`
- `security_reviewer`

Developer, approver, and viewer roles do not have access to the settings overview.

Linked operational-surface mutation stays narrower:

- `owner` and `admin` can enable or disable scheduled tasks, run a task now, enable or disable audit exports, run audit exports manually, and launch retention dry-runs
- `security_reviewer` can inspect those pages but cannot mutate them
- `developer`, `approver`, and `viewer` do not get those operational controls

## Current Limitations

- `/settings` itself is still read-only. It summarizes status and links into narrower pages rather than editing config directly.
- Secret-backed changes are still managed through environment injection, deployment config, or narrower privileged APIs.
- Scheduled-task creation and full config editing remain API-driven.
- Audit-export destination creation and detailed endpoint or filter editing remain API-driven.
- Retention browser controls remain dry-run only. Real purge still requires the privileged API path.
- Deployment-level statuses such as key provider and rate limiter are shared across tenants, even though the page itself is tenant-authenticated.
- The page summarizes health and safe metadata; it is not a replacement for `/ready`, `/metrics`, logs, or deeper integration-specific operator workflows.
