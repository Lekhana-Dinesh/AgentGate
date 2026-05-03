# AgentGate

AgentGate is a runtime security and governance platform for enterprise AI agents. It intercepts agent tool calls, checks identity, intent, policy, data sensitivity, and risk, then allows, blocks, routes for approval, or records the action for audit and incident response.

This repository is a production-minded monorepo foundation for:

- Tenant-aware agent registry
- Runtime gateway for tool calls
- Deterministic intent checks and risk scoring
- Policy-based allow, block, redact, and approval decisions
- Approval inbox for human reviewers
- Audit logging and replayable execution traces
- Mock enterprise adapters for local demos and testing
- Real GitHub adapter support for safe repository and issue workflow actions
- Optional Slack approval notifications for high-risk approval requests
- Durable async job foundation for approval notifications and approved tool execution
- Retention purge enforcement for protected execution payloads with dry-run support
- Optional tenant-aware OIDC/SSO foundation with JIT provisioning and local auth preserved for development
- Env-backed key and secret management foundation with rotation metadata and secret-reference resolution
- Tenant-scoped audit export foundation for sanitized SIEM/webhook delivery through async jobs
- Production-minded config validation, structured request logging, readiness checks, security headers, and aggregate metrics
- Lightweight abuse-protection and rate limiting on auth, gateway, approval, audit-export, and retention control paths
- Next.js admin dashboard

## Monorepo Layout

```text
AgentGate/
  apps/
    api/        FastAPI control-plane API
    web/        Next.js admin console
  packages/
    shared/     Reserved space for shared schemas/contracts
  docs/
    ARCHITECTURE.md
    API.md
    PRODUCT.md
    ROADMAP.md
    SECURITY.md
    connectors/github.md
    integrations/slack.md
    demo-scenario.md
  docker-compose.yml
  Makefile
  .env.example
```

## What Is Implemented

- FastAPI backend with tenant-aware models, JWT auth, optional OIDC SSO, API key support, RBAC, audit events, traces, and seed data
- Local email/password login remains available and is still the default for development
- Runtime tool-call gateway at `POST /v1/gateway/tool-call`
- Deterministic policy engine, intent checker, and risk scoring service
- Approval workflow with reviewer actions and optional immediate adapter execution on approval
- Queue-backed jobs table with inline local fallback and worker mode for Slack notifications, approved execution, and retention purge
- Queue-backed audit export jobs with tenant-scoped cursors and sanitized destination adapters
- Structured request logs with request IDs, safe error codes, and tenant/user context when known
- Lightweight `/metrics`, deeper `/ready`, and stricter production startup validation
- Tenant-scoped OIDC config model, browser login initiation/callback flow, exchange ticket handoff, and role-mapping scaffolding
- Mock adapters for Salesforce, PricingDB, Email, Jira, and Postgres-style actions
- A production-style GitHub adapter for repository metadata, pull requests, issues, and comments
- Next.js dashboard pages for overview, agents, tool calls, approvals, jobs, retention, policies, traces, audit logs, and demo scenario execution
- Next.js dashboard pages for overview, agents, tool calls, approvals, jobs, audit exports, retention, policies, traces, audit logs, and demo scenario execution
- Field-level payload protection for sensitive execution arguments with sanitized API and UI views plus retention purge metadata
- Env-backed key provider, key-status endpoint, and shared secret-reference resolver for payload keys, GitHub, Slack, and OIDC
- Alembic initial migration, Dockerfiles, and local compose stack
- Backend unit and integration-style test coverage for core decision logic

## Quick Start

### Option 1: Docker Compose

1. Copy `.env.example` to `.env` and adjust secrets if needed.
2. Run `docker compose up --build`.
3. In another shell, seed demo data:

```bash
cd apps/api
python -m app.db.seed
```

4. Open:
   - API: `http://localhost:8000/docs`
   - Web: `http://localhost:3000`
   - Ready: `http://localhost:8000/ready`
   - Metrics: `http://localhost:8000/metrics`
5. Optional: set `AGENTGATE_GITHUB_TOKEN` before exercising the GitHub connector. The default sales demo still works without it.
6. Optional: enable Slack approval notifications with `AGENTGATE_SLACK_NOTIFICATIONS_ENABLED=true`, `AGENTGATE_SLACK_DEFAULT_CHANNEL=<channel-or-user-id>`, and `AGENTGATE_SLACK_BOT_TOKEN`.
7. Optional but recommended for local parity: set `AGENTGATE_PAYLOAD_ENCRYPTION_KEY` to a Fernet key. In `development` and `test`, AgentGate falls back to a deterministic local key if this is unset. Outside those environments, the key is required.
   - The current production-minded key provider is `AGENTGATE_KEY_PROVIDER=env`.
   - If you want explicit secret-reference wiring, set `AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY`.
   - For manual rotation scaffolding, add decrypt-only refs with `AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS`.
8. Compose now defaults `AGENTGATE_JOB_DISPATCH_MODE=worker` and starts a dedicated `worker` service. For purely local single-process development, keep `AGENTGATE_JOB_DISPATCH_MODE=inline`.
9. Retention dry-runs are available at `/retention`. Real purge remains a privileged API operation at `POST /v1/retention/purge`.
10. OIDC/SSO is optional and disabled by default. Local username/password login remains the default path for development.
11. Audit export destinations are tenant-scoped and configured through `POST /v1/audit-exports`. The dashboard page at `/audit-exports` shows non-sensitive status and manual run controls only.

### Option 2: Local Development

Backend:

```bash
cd apps/api
python -m pip install -e .[dev]
python -m alembic upgrade head
python -m app.db.seed
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Optional worker mode:

```bash
cd apps/api
AGENTGATE_JOB_DISPATCH_MODE=worker python -m app.worker
```

Frontend:

```bash
cd apps/web
npm install
npm run dev
```

## Demo Credentials

- Tenant slug: `demo-agentgate`
- Admin: `admin@demo.agentgate.local` / `AgentGate123!`
- Reviewer: `reviewer@demo.agentgate.local` / `AgentGate123!`

## Common Commands

- `make bootstrap`
- `make verify`
- `make api-dev`
- `make api-migrate`
- `make api-test`
- `make api-seed`
- `make web-dev`
- `make up`
- `make down`

## Key Docs

- [Architecture](docs/ARCHITECTURE.md)
- [API](docs/API.md)
- [Security](docs/SECURITY.md)
- [Payload Protection](docs/security/payload-protection.md)
- [Key And Secret Management](docs/security/key-and-secret-management.md)
- [SSO And OIDC](docs/security/sso-oidc.md)
- [Retention And Purge](docs/security/retention-and-purge.md)
- [Audit Export](docs/integrations/audit-export.md)
- [Product](docs/PRODUCT.md)
- [Roadmap](docs/ROADMAP.md)
- [Demo Scenario](docs/demo-scenario.md)
- [Jobs And Workers](docs/operations/jobs-and-workers.md)
- [Deployment Hardening](docs/operations/deployment-hardening.md)
- [Observability](docs/operations/observability.md)
- [Rate Limiting](docs/operations/rate-limiting.md)
- [GitHub Connector](docs/connectors/github.md)
- [Slack Notifications](docs/integrations/slack.md)
- [Contributing](CONTRIBUTING.md)

## Honest Limitations

This repo is a strong production-oriented foundation, not a completed enterprise platform. It now includes OIDC scaffolding, env-backed key management, tenant-scoped audit export, readiness and metrics foundations, and endpoint rate limiting, but it does not currently include SAML, SCIM, immutable external audit storage, a distributed rate limiter, full observability infrastructure, fully managed worker orchestration, cloud KMS/HSM providers, or certified compliance controls. Those are documented as next-step hardening work rather than claimed as complete.

## Recent Hardening Highlights

- Agent API keys now support explicit scopes, expirations, revocation, last-used tracking, and metadata-only listing.
- Gateway traces now pause hard when an approval is pending and only resume after an approval decision updates the trace.
- Tool calls now store a first-class `trace_id`, improving trace replay and future analytics joins.
- Structured risk factors and request IDs are returned to improve operator explainability and troubleshooting.
- GitHub is now the first real non-mock connector and still runs through the normal policy, risk, approval, audit, and trace path.
- Slack approval notifications are now available as a best-effort outbound integration with safe redaction, audit coverage, and a health check endpoint.
- Sensitive execution arguments are now stored with field-level encryption envelopes, while APIs, traces, approvals, audit feeds, and Slack use sanitized payload views only.
- Approval notifications and approved execution now share a durable async job layer with inline fallback for local development and a worker entrypoint for queue-backed operation.
- Protected execution payloads now honor retention classes, legal hold exclusions, and queue-backed purge enforcement without decrypting archived values.
- OIDC login now supports tenant-scoped config, signed state validation, JIT user provisioning, domain checks, and role mapping while keeping local auth intact.
- Payload encryption now records key metadata in each envelope and uses a shared secret-reference layer for payload keys, GitHub, Slack, and OIDC secret resolution.
- Audit events can now be exported to tenant-scoped webhook, Splunk HEC, or Datadog-compatible destinations through durable async jobs with sanitized payloads and per-destination cursors.
