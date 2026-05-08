# Deployment Validation

Use `scripts/validate-deployment.py` after local startup, production-style Compose startup, or an upgrade rollout to confirm that AgentGate is sane from an operator perspective.

If you want the broader pilot-prep wrapper that also checks repo hygiene, pilot docs, and the default policy pack, use [Pilot Rehearsal](pilot-rehearsal.md).

This validator is intentionally lightweight:

- it checks only internal AgentGate surfaces
- it does not require GitHub, Jira, MCP, Slack, AWS, or other external systems
- it does not mutate tenant data beyond login and logout
- it is a smoke test, not a full certification of deployment health

## What It Checks

The validator checks:

- `GET /health`
- `GET /ready`
- web login page reachability
- operator login with the provided tenant slug and credentials
- `GET /v1/auth/me`
- `GET /v1/settings/overview`
- `GET /v1/onboarding/status`
- `GET /v1/tools/summary`
- `GET /v1/jobs`
- `GET /v1/audit-integrity/status`
- `GET /metrics` when metrics validation is enabled or auto-detected as local-only
- `POST /v1/auth/logout`

For cookie-session mode it also confirms that logout clears the browser session cookie. For token mode it validates that the logout endpoint is reachable, while honestly noting that bearer-token mode stays stateless.

## Required Environment Variables

- `AGENTGATE_VALIDATE_API_URL`
- `AGENTGATE_VALIDATE_WEB_URL`
- `AGENTGATE_VALIDATE_EMAIL`
- `AGENTGATE_VALIDATE_PASSWORD`
- `AGENTGATE_VALIDATE_TENANT_SLUG`

Optional:

- `AGENTGATE_VALIDATE_TIMEOUT_SECONDS`
- `AGENTGATE_VALIDATE_RETRIES`
- `AGENTGATE_VALIDATE_RETRY_DELAY_SECONDS`
- `AGENTGATE_VALIDATE_CHECK_METRICS`

`AGENTGATE_VALIDATE_CHECK_METRICS` accepts:

- `auto`
- `true`
- `false`
- `always`
- `never`

`auto` is the default. In that mode the script checks `/metrics` only when the API URL is loopback-based, such as `127.0.0.1` or `localhost`.

## Commands

Generic:

```bash
AGENTGATE_VALIDATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_VALIDATE_WEB_URL=https://agentgate.example.com \
AGENTGATE_VALIDATE_EMAIL=owner@example.com \
AGENTGATE_VALIDATE_PASSWORD='<password>' \
AGENTGATE_VALIDATE_TENANT_SLUG=customer-tenant \
python scripts/validate-deployment.py
```

Local seeded demo:

```bash
make validate-local
```

Generic Make target:

```bash
make validate-deployment
```

Restore-validation Make target:

```bash
make verify-restore
```

The validation account should be an `owner`, `admin`, or `security_reviewer` so the script can reach the privileged read-only operator APIs it checks.

## Expected Output

Successful output looks like a short checklist:

```text
[ok] API /health: API health endpoint returned ok.
[ok] API /ready: API readiness is ready (...)
[ok] Operator login: Operator login succeeded using token session mode.
[ok] Summary: Deployment validation completed successfully.
```

Failures are concise and avoid printing tokens, cookies, or passwords.

Exit codes:

- `0` success
- `1` validation failed
- `2` invalid configuration or missing required settings
- `3` unexpected runtime error

## When To Run It

Run deployment validation:

- after `docker compose up` in local or self-hosted testing
- after the first production-style startup
- after schema migrations and service restarts during upgrades
- after a PostgreSQL restore drill or real recovery event
- after reverse-proxy, cookie-session, or public-URL changes
- after operator-auth changes that could affect browser or API access
- as the live-environment step inside `python scripts/run-pilot-rehearsal.py`

## Additional Restore Checks

After a restore, pair the validator with a few recovery-specific operator checks:

- review `GET /v1/audit-integrity/status`
- review `GET /v1/audit-integrity/checkpoints` if checkpointing is enabled
- verify the latest checkpoint with `POST /v1/audit-integrity/checkpoints/{id}/verify` when external anchoring matters
- confirm the expected checkpoint objects still exist in the external anchor destination if you use object storage
- confirm no production environment still allows the local demo credentials

The full recovery flow is documented in `docs/operations/backup-and-restore.md`.

## What It Intentionally Does Not Validate

The script does not:

- validate GitHub, Jira, MCP, Slack, OIDC, SCIM, or AWS connectivity
- create checkpoints, run retention purge, or trigger connector probes
- prove worker job throughput or scheduler liveness
- prove `/metrics` should be public
- replace full runbook checks, load tests, browser E2E, or external monitoring
- replace restore-drill review of audit checkpoints, worker status, or external anchor retention

## Limitations

- the script assumes valid operator credentials already exist
- it is strongest when run from the same trusted network path that operators use
- metrics validation defaults to local-only auto detection unless explicitly enabled
- a successful run does not prove that background workers, external dependencies, or audit-anchor destinations are healthy beyond the safe surfaces already exposed by AgentGate
