# Self-Hosted Evaluation

Use this guide for the first real AgentGate controlled-pilot rehearsal when you want the fastest credible self-hosted proof on a single VM with Docker Compose.

This path is intentionally narrow:

- one Linux VM
- external PostgreSQL
- external Redis
- externally injected GitHub credential
- one sandbox GitHub repository allowlist
- one real approval-gated GitHub action
- trace, approval, and audit evidence capture

Use this guide with:

- `compose.prod.example.yml`
- `.env.self-hosted-evaluation.example`
- [Self-Hosted Deployment](self-hosted-deployment.md)
- [Deployment Validation](deployment-validation.md)
- [Pilot Policy Pack](pilot-policy-pack.md)
- [Production Runbook](production-runbook.md)
- [Pilot Rehearsal](pilot-rehearsal.md)

This is a controlled-pilot evaluation package, not a claim of enterprise GA, managed SaaS, compliance certification, or full platform operations.

## What This Rehearsal Proves

This rehearsal is meant to prove product behavior first:

- AgentGate runs on a production-style Compose topology
- PostgreSQL and Redis are externalized
- the GitHub connector uses real external credentials
- the browser stays secretless
- policy can require approval before a side effect
- approval can trigger one real GitHub action
- trace and audit evidence are visible after execution

This is not a full deployment-maturity proof. It does not prove HA, autoscaling, Kubernetes, Terraform rollout maturity, restore success, or compliance posture.

## Hard Requirements

Use these rules for the first live rehearsal:

- Do not use local SQLite.
- Do not run `python -m app.db.seed`.
- Do not use the seeded demo tenant for the real pilot tenant.
- Do not enter raw GitHub tokens or private keys in the browser.
- Do not broaden the GitHub repository allowlist beyond a sandbox repo.
- Keep `AGENTGATE_ALLOW_DEMO_CREDENTIALS=false`.
- Require `connector_mode=live_connector` before the live action.
- Require `live_execution_ready=true` before the live action.
- Keep Jira out of the first rehearsal unless explicitly required.
- Keep MCP disabled unless it has been explicitly reviewed and tightly constrained.

## Recommended Topology

Recommended shape:

1. Run `api`, `web`, `worker`, and `scheduler` from `compose.prod.example.yml`.
2. Use an external PostgreSQL database with backup coverage.
3. Use an external Redis instance with authentication and network restrictions.
4. Put TLS termination and any reverse proxy in front of the loopback-bound `web` and `api` services.
5. Inject runtime secrets outside git through a host env file or your secret manager.
6. Use one sandbox GitHub repo only, such as `customer-sandbox/agentgate-pilot`.

## Preflight Checklist

Before the rehearsal window:

- Linux VM with Docker Engine and Docker Compose plugin
- public app URL and public API URL chosen
- HTTPS reverse proxy or ingress available
- external PostgreSQL reachable and backup coverage confirmed
- external Redis reachable and access controls confirmed
- S3-compatible bucket or prefix available if you want external audit-integrity checkpointing
- one sandbox GitHub repository created for the rehearsal
- one narrow GitHub credential prepared outside the repo:
  - fastest path: env token scoped only to the sandbox repo
  - stronger path: GitHub App with Metadata read and Issues read/write
- reviewer staffing confirmed for approval decisions
- policy scope frozen:
  - GitHub first
  - Jira optional
  - MCP off by default

No-go before you start if any of these are missing.

## Redacted Env Template

Start from `.env.self-hosted-evaluation.example`, copy it outside the repo, and fill real values privately.

Recommended location:

- `/etc/agentgate/pilot.env`

Do not commit real values.

## Build And Start Flow

From the repo root:

```bash
python scripts/check-no-live-secrets.py
python scripts/run-pilot-rehearsal.py --skip-live-api
docker compose -f compose.prod.example.yml --env-file /etc/agentgate/pilot.env config
docker compose -f compose.prod.example.yml --env-file /etc/agentgate/pilot.env build
docker compose -f compose.prod.example.yml --env-file /etc/agentgate/pilot.env --profile ops run --rm migrate
docker compose -f compose.prod.example.yml --env-file /etc/agentgate/pilot.env up -d api web worker scheduler
```

Health checks after startup:

- `GET /health`
- `GET /ready`
- login page loads at `/login`
- `GET /v1/workers/status` shows an active worker

Then run:

```bash
AGENTGATE_VALIDATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_VALIDATE_WEB_URL=https://agentgate.example.com \
AGENTGATE_VALIDATE_EMAIL=owner@example.com \
AGENTGATE_VALIDATE_PASSWORD='<password>' \
AGENTGATE_VALIDATE_TENANT_SLUG=customer-pilot \
python scripts/validate-deployment.py
```

## First Operator Account

For a clean environment, temporarily configure `AGENTGATE_BOOTSTRAP_TOKEN` as a strong random secret distinct from the JWT signing key. Supply that same secret from the operator shell:

```bash
curl -X POST https://api.agentgate.example.com/v1/auth/bootstrap \
  -H "X-AgentGate-Bootstrap-Token: ${AGENTGATE_BOOTSTRAP_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_name":"Customer Pilot",
    "tenant_slug":"customer-pilot",
    "email":"owner@example.com",
    "full_name":"Pilot Owner",
    "password":"<strong-password>"
  }'
```

After the first owner exists, remove the bootstrap token from the API configuration and restart the service. Bootstrap also locks once a user exists.

Do not use demo seed credentials in a real company rehearsal.

## Live GitHub Connector Smoke Test

Use the existing safe metadata route or the tools page, but keep the browser secretless. The browser may display only safe reference names like `AGENTGATE_GITHUB_TOKEN`; it must not accept or show token values or private keys.

For the first real rehearsal, configure the GitHub connector with:

- `auth_mode=env_token` or `github_app`
- one sandbox repository allowlist
- internal or sandbox trust hints only
- `enabled=true`
- no `demo_safe_mock`

Before the live action, verify:

1. `GET /v1/tools/{tool_id}/safe-detail`
2. `GET /v1/tools/{tool_id}/health?probe=true`

Required results:

- `connector_mode=live_connector`
- `live_execution_ready=true`
- health `status=ready`
- no secret values in API responses
- repository allowlist is exactly the sandbox scope you reviewed

No-go immediately if:

- `demo_safe_mock` is still active
- `live_execution_ready` is false
- the health probe fails
- the allowlist is broader than the sandbox repo

## Policy Dry Run And Apply

Use the pilot-default pack conservatively:

```bash
python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json
```

Dry run first:

```bash
AGENTGATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_ACCESS_TOKEN=<operator-token> \
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json --dry-run
```

Then apply:

```bash
AGENTGATE_API_URL=https://api.agentgate.example.com \
AGENTGATE_ACCESS_TOKEN=<operator-token> \
python scripts/apply-policy-pack.py --pack policy-packs/pilot-default/policies.json
```

## First Live Action

For the first real side effect, prefer `create_issue` in the sandbox repo.

Why this is the safest first proof:

- it is a real external side effect
- it is low blast radius
- it proves approval gating cleanly
- it avoids public or customer-visible posting as the first live action

The governed path should be:

1. the agent attempts `create_issue`
2. AgentGate evaluates policy and requires approval
3. a reviewer approves with `execute_now=true`
4. AgentGate executes the GitHub action
5. operators review trace, approval, tool-call, and audit evidence

Do not use the seeded governed GitHub demo route for this live rehearsal. That path is intentionally demo-safe and does not prove live external execution.

## Exact Validation Steps

Confirm all of the following:

1. `GET /health` returns `200`
2. `GET /ready` returns `200`
3. `python scripts/validate-deployment.py` succeeds
4. `python scripts/run-pilot-rehearsal.py` succeeds with live inputs
5. `GET /v1/tools/{tool_id}/safe-detail` shows `connector_mode=live_connector`
6. `GET /v1/tools/{tool_id}/safe-detail` shows `live_execution_ready=true`
7. `GET /v1/tools/{tool_id}/health?probe=true` returns `status=ready`
8. policy-pack validation and dry run are clean
9. the first governed `POST /v1/gateway/tool-call` returns `decision=require_approval`
10. the approval response returns `status=approved`
11. the execution status returns `succeeded`
12. the sandbox GitHub issue exists
13. `GET /v1/workers/status` shows at least one healthy worker
14. trace and audit evidence are visible for the tool call

## Evidence To Capture

Capture at minimum:

- `GET /health`
- `GET /ready`
- deployment validator output
- pilot rehearsal wrapper output
- GitHub tool `safe-detail` output
- GitHub tool `health?probe=true` output
- policy-pack validation output
- policy-pack dry-run or apply output
- governed gateway decision response
- approval response
- created GitHub issue link or screenshot
- trace evidence
- audit evidence
- `GET /v1/workers/status`

Good operator screenshots:

- `/tools`
- `/approvals`
- `/tool-calls`
- `/traces/[id]`
- `/audit`
- `/audit-integrity`

Use [Pilot Rehearsal Evidence Checklist](../reviews/PILOT_REHEARSAL_EVIDENCE_CHECKLIST.md) for the final packaging step.

## No-Go Conditions

Stop the rehearsal if any of these are true:

- PostgreSQL is missing, misconfigured, or unverified
- Redis is missing, misconfigured, or unreachable
- `/ready` fails
- `demo_safe_mock` is still active on the live GitHub connector
- `connector_mode` is not `live_connector`
- `live_execution_ready` is not true
- GitHub health probe fails
- repository allowlist is broader than the reviewed sandbox scope
- secrets appear in logs, terminal capture, or screenshots
- worker is unhealthy
- approval evidence is missing
- trace or audit evidence is missing

## Rollback And Cleanup

Before migrations, confirm a PostgreSQL backup or snapshot exists.

If the rehearsal fails:

1. stop write traffic
2. review migration compatibility
3. roll back application containers only if the schema is backward compatible
4. otherwise restore PostgreSQL and then roll back the app version

After a successful rehearsal:

- keep the evidence package
- decide whether to close the sandbox issue or keep it as proof
- rotate or revoke any temporary GitHub credential created just for the rehearsal
- keep the repo allowlist narrow until the company explicitly expands scope

## Demo-Safe Versus Live GitHub

Be explicit about this distinction:

- `demo_safe_mock` is for seeded demo workflows and browser evaluation only
- it is not valid evidence for a real company live-connector rehearsal
- live GitHub execution requires external credential injection and reviewed connector metadata
- the browser should display only safe reference names and readiness guidance, never raw credential material

## What To Do Next

After this single-VM Compose rehearsal succeeds:

1. complete one isolated restore drill
2. run `python scripts/check-recovery-readiness.py --env-file /etc/agentgate/pilot.env ...` before the drill window so backup, rollback, Redis, and checkpoint expectations are recorded explicitly
3. decide whether the pilot customer actually needs AWS packaging proof
4. if yes, run the ECS/Fargate rehearsal second using the already-shipped starter and validation workflow
