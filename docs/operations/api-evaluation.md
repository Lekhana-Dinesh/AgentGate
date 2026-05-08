# API Evaluation

AgentGate now includes a repo-friendly API evaluation package under `api-collections/http/AgentGate/`.

This package is for technical reviewers, design partners, and solutions engineers who want to exercise the core control-plane APIs without hand-writing every request.

It is intentionally an evaluation aid:

- no real tokens or cookies are committed
- no external GitHub, Jira, MCP, Slack, or AWS services are required
- destructive or risky flows are excluded or clearly marked manual-only
- it does not replace `scripts/validate-deployment.py`, backend tests, or browser E2E

## Included Files

- `api-collections/http/AgentGate/http-client.env.json.example`
- `api-collections/http/AgentGate/operator-evaluation-token.http`
- `api-collections/http/AgentGate/operator-evaluation-cookie.http`

The collection uses plain `.http` request files so it stays easy to review in git and easy to adapt to JetBrains HTTP Client, VS Code REST Client, Bruno, curl, or another request runner.

## Required Variables

Required:

- `AGENTGATE_API_URL`
- `AGENTGATE_WEB_URL`
- `AGENTGATE_TENANT_SLUG`
- `AGENTGATE_EMAIL`
- `AGENTGATE_PASSWORD`

Required only for token-mode follow-up requests:

- `AGENTGATE_ACCESS_TOKEN`

Useful optional placeholders for manual follow-up requests:

- `AGENTGATE_CSRF_TOKEN`
- `AGENTGATE_AGENT_ID`
- `AGENTGATE_USER_ID`
- `AGENTGATE_JOB_ID`
- `AGENTGATE_TASK_ID`
- `AGENTGATE_CHECKPOINT_ID`

Do not commit real values for tokens, cookies, or CSRF state.

## Safe Request Order

Recommended order:

1. `GET /health`
2. `GET /ready`
3. `GET /login` on the web app
4. `POST /v1/auth/login`
5. `GET /v1/auth/me`
6. `GET /v1/settings/overview`
7. `GET /v1/onboarding/status`
8. `GET /v1/tools/summary`
9. Optional: `POST /v1/demo/run-sales-agent-risk-scenario`
10. `GET /v1/approvals`
11. `GET /v1/jobs`
12. `GET /v1/scheduled-tasks`
13. `GET /v1/audit-integrity/status`
14. Optional safe operator actions:
    - `POST /v1/audit-integrity/verify`
    - `POST /v1/audit-integrity/checkpoints`
    - `POST /v1/retention/purge` with `dry_run=true`
15. `GET /v1/audit-exports`
16. `GET /v1/users`

The token-mode file also includes:

- `GET /v1/agents`
- a manual `POST /v1/gateway/tool-call` example using the seeded mock email path
- a manual `POST /v1/scheduled-tasks/{task_id}/run-now`
- manual `GET /v1/jobs/{job_id}` and checkpoint follow-up requests
- a SCIM disabled or unauthorized example

## Token Mode Vs Cookie Mode

Use `operator-evaluation-token.http` when:

- `AGENTGATE_AUTH_SESSION_MODE=token`
- you want the easiest copy-paste evaluator flow
- you are using the local demo stack or another deployment that still returns `access_token` on login

Token-mode flow:

1. Run login.
2. Copy `access_token` from the response into `AGENTGATE_ACCESS_TOKEN`.
3. Run the remaining bearer-authenticated requests.

Use `operator-evaluation-cookie.http` when:

- `AGENTGATE_AUTH_SESSION_MODE=cookie`
- your HTTP client preserves cookies between requests

Cookie-mode flow:

1. Run login in the same client session.
2. Run `GET /v1/auth/csrf-token`.
3. Copy `csrf_token` into `AGENTGATE_CSRF_TOKEN` if your client does not auto-chain it.
4. Run the read-only requests normally.
5. For unsafe requests like verify, checkpoint creation, or retention dry-run, send `X-CSRF-Token`.

Bearer-token and cookie-session auth stay intentionally separate. Do not treat the collection as a reason to weaken production cookie settings or CSRF enforcement.

## Local And Self-Hosted Use

Fastest local path:

1. `docker compose up --build`
2. `docker compose exec api python -m app.db.seed`
3. use the `local-demo-token` or `local-demo-cookie` environment values from `http-client.env.json.example`

Self-hosted path:

1. stand up the deployment using `compose.prod.example.yml` or your own packaging
2. create a real operator account
3. copy `self-hosted-template` to your private client environment file and fill in real URLs and credentials
4. run `scripts/validate-deployment.py` first
5. then use the API collection for reviewer-driven exploration

## What Is Intentionally Excluded

The collection intentionally does not include by default:

- approval approve or reject actions
- user deactivate or reactivate actions
- tool create or update actions
- retention non-dry-run purges
- destructive connector operations
- live GitHub, Jira, MCP, Slack, OIDC, SCIM, or AWS validation flows
- raw secret references, env-var token names, or cookies

Some requests are marked manual-only because they need a real object ID or because they can enqueue operational work. Review the comments in the `.http` files before sending them.

## Limitations

- This is an evaluation collection, not a production API test harness.
- Token mode is the easiest evaluator path, but some deployments will intentionally prefer cookie mode.
- The manual gateway example still needs a real agent ID and user ID from the current tenant.
- Checkpoint creation and scheduled-task run-now can enqueue real durable jobs, so use them deliberately.
- The collection does not prove external connector health, worker throughput, scheduler liveness, or backup integrity by itself.
