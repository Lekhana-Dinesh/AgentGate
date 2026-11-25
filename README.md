# AgentGate

AgentGate is a runtime governance gateway for AI-agent tool calls. It checks who is calling, what the agent is trying to do, and which tenant policies apply before a tool action can execute. Operators can review risky requests, see what ran, and reconstruct each decision from a trace and audit trail.

**Project status:** Local MVP for technical evaluation. The seeded walkthrough uses synthetic data and mock execution. It requires no model provider, live connector credentials, or cloud account.

## Who it serves

Platform engineers can put a consistent policy check in front of agent integrations. Security reviewers can approve or reject sensitive actions with the relevant policy, risk, and intent in view. Developers can simulate a proposed tool call and inspect the decision before enabling a workflow.

## How it works

```text
Agent → FastAPI gateway → tenant identity → intent and risk → policy
                                                          ├─ allow / redact → adapter
                                                          ├─ block
                                                          └─ request approval → reviewer → job → worker → adapter

Next.js console → operator API → approvals, traces, policy simulation, audit
Scheduler → durable PostgreSQL jobs → Redis notifications → worker
```

Intent matching and risk scoring use deterministic rules. PostgreSQL stores tenant records, jobs, approvals, traces, and audit events. Redis wakes workers, while PostgreSQL remains the durable job ledger.

| Area | Available in the MVP |
| --- | --- |
| Governance | Tenant-scoped agent identities, role checks, allow/block/redact/approval decisions, and side-effect-free policy simulation |
| Operations | Approval and rejection, background execution, retries and worker visibility, scheduled tasks, and a browser console |
| Evidence | Step-by-step traces, sanitized operator views, protected payload handling, and tamper-evident audit chains |
| Integrations | Mock CRM, pricing, email, and database actions for the demo. GitHub, Jira, and MCP HTTP adapter code with mocked transport tests. |

**Stack:** Python 3.12, FastAPI, SQLAlchemy, Alembic, PostgreSQL 16, Redis 7, Next.js 15, React, TypeScript, Tailwind CSS, Docker Compose, pytest, and Playwright.

## Quickstart

Install Docker with Compose v2 and start its engine. The first build downloads base images and dependencies. Make ports 3000, 8000, 5432 and 6379 available locally. Run from the repository root:

```sh
docker compose --env-file .env.example -p agentgate-demo up --build -d --wait
docker compose --env-file .env.example -p agentgate-demo exec -T api python -m app.db.seed
docker compose --env-file .env.example -p agentgate-demo ps -a
```

The project name gives this instance its own network and PostgreSQL volume. The migration container should exit successfully. API readiness is at [localhost:8000/ready](http://localhost:8000/ready), API reference at [localhost:8000/docs](http://localhost:8000/docs), and the console at [localhost:3000](http://localhost:3000). Use `localhost` consistently so the browser origin matches the development configuration.

Sign in to tenant `demo-agentgate` as `admin@demo.agentgate.example.com` or `reviewer@demo.agentgate.example.com`. Both accounts use the local-only fixture password defined in the [seed script](apps/api/app/db/seed.py).

If another project uses the PostgreSQL or Redis host ports, set `AGENTGATE_LOCAL_POSTGRES_PORT` or `AGENTGATE_LOCAL_REDIS_PORT` to free ports in your shell before starting. To stop the demo while retaining its data:

```sh
docker compose --env-file .env.example -p agentgate-demo stop
```

Keep this stack local and use a fresh synthetic database. For configuration and a Docker-free SQLite path, see [Local development and demo](docs/operations/local-mvp.md).

## Demo walkthrough

1. Open **Demo → Governed GitHub workflow**. Run it to see policy simulation, a seeded reviewer decision, and mock execution. In worker mode the page may report a queued job. Open the trace to see the completed step once the worker finishes.
2. Open **Demo → Sales renewal scenario** and select **Run sales workflow**. The demonstration approves the discount automatically and leaves the synthetic email pending. In **Approvals**, open the `Email.send_external_email` request that links to this run’s trace. Add a comment and choose **Approve and execute**. Switch to **Approved requests** and refresh the queue to check the execution result.
3. Run the sales scenario again. Reject the new email request. Confirm it appears under **Rejected requests**, the trace is blocked, and **Audit** contains the rejection. The rejected email has no approved execution job.
4. Open **Policies → Policy Simulation**. Try an `apply_discount` action on `PricingDB` with a 30% discount to see a policy match without creating a job or approval.

## Verification

The verified local MVP baseline is **282 backend tests, 13 repository tests, and 14 Chromium browser tests**. The browser suite ran against the Docker Compose stack with synthetic data.

Python 3.12 and Node.js 22 are used by CI. Run the first block from the repository root, the second from `apps/api`, and the third from `apps/web`.

```sh
python -m pytest -q tests
python scripts/check-no-live-secrets.py
python scripts/validate-policy-pack.py --pack policy-packs/pilot-default/policies.json
docker compose --env-file .env.example config --quiet
```

```sh
python -m pip install -e ".[dev]"
python -m ruff check app
python -m pytest -q app/tests
python -m bandit -c bandit.yaml -r app -x app/tests -iii
```

```sh
npm ci
npm run lint
npm run typecheck
npm run build
npm audit --audit-level=high
```

For Playwright, keep the seeded stack running, install Chromium with `npm run e2e:install`, and set `AGENTGATE_E2E_BASE_URL=http://localhost:3000` and `AGENTGATE_E2E_API_BASE_URL=http://localhost:8000` before running `npm run e2e`. The tests modify the synthetic tenant and run serially.

## Scope and roadmap

- **Local verification:** PostgreSQL, Redis, the API, frontend, worker, and scheduler are covered by the local Compose walkthrough. The reviewer flow exercises synthetic approvals, rejections, execution, and evidence.
- **Deployment assets:** [Self-hosted Compose](docs/operations/self-hosted-deployment.md) and [AWS ECS Terraform](deploy/aws/ecs/) are configuration foundations for a future controlled pilot.
- **Limits:** Live provider validation, production deployment, load and recovery objectives, and customer adoption are outside the evidence for this MVP. Audit hashing provides tamper evidence. Durable external evidence also depends on independently controlled storage and retention.
- **Next milestones:** Rehearse recovery and queue failure handling, validate a least-privilege GitHub connector in an explicitly approved sandbox, and run an operator-led pilot rehearsal.

See the [architecture](docs/ARCHITECTURE.md), [API guide](docs/API.md), [security posture](docs/SECURITY.md), [roadmap](docs/ROADMAP.md), and [contribution guide](CONTRIBUTING.md) for details.

Security review resources include the [Threat Model](docs/security/THREAT_MODEL.md), [Security Review Checklist](docs/security/SECURITY_REVIEW_CHECKLIST.md), [Incident Response](docs/security/INCIDENT_RESPONSE.md), and [Audit Integrity](docs/security/audit-integrity.md).

**Development disclosure:** AI-assisted tooling, including Codex, was used to implement, review, and document parts of the repository. Verification claims refer to checks run against the code and local stack.

Licensed under [MIT](LICENSE).
