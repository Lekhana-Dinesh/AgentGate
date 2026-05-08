# Context Pack

## 1. Purpose

This directory gives future Codex sessions a narrow, domain-specific entrypoint into AgentGate.

Use it to avoid rereading broad repo docs or scanning the whole codebase when a task only touches one area.

## 2. Main files/directories

- `docs/AGENTGATE_CODEX_HANDOFF.md`: short global index and repo guardrails
- `docs/context/*.md`: focused domain summaries
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/SECURITY.md`: broader source docs behind these summaries

## 3. Current capabilities

- Focused context files for gateway, auth and identity, connectors, jobs and scheduler, audit integrity, payload and secret handling, observability and ops, frontend, testing and CI, deployment, and roadmap work
- A read path that lets future sessions load only the relevant context before inspecting source and tests

## 4. Critical invariants / must-not-break rules

- Read `docs/AGENTGATE_CODEX_HANDOFF.md` first.
- Then read only the relevant `docs/context/*.md` files for the task.
- After that, inspect the owning source files and tests before editing.
- Do not treat these summaries as a substitute for source-level verification.
- Preserve the existing architecture, tenant isolation, gateway governance flow, and safety model.

## 5. Security boundaries

- These files summarize security boundaries but do not replace the real enforcement in code.
- If a summary conflicts with code or tests, the code and tests win until the docs are corrected.
- Secret-handling, payload protection, audit integrity, and RBAC changes still require direct source inspection.

## 6. Known limitations

- These pages can lag behind the code if future changes are not documented.
- Some features span multiple domains. For example, audit checkpointing touches jobs, security, deployment, and frontend surfaces.
- Cross-cutting tasks may require reading more than one context file.

## 7. Relevant tests

- Run `python scripts/check-no-live-secrets.py` when changing docs, examples, workflows, or config surfaces.
- Run the tests owned by the domains you touch after reading the relevant context file.

## 8. When future Codex sessions should read this file

Read this file immediately after the global handoff when you need help choosing which narrower context files to load.

Suggested starting points:

- Gateway or policy changes: `gateway.md`
- Login, OIDC, users, or API keys: `auth-identity.md`
- GitHub or Slack integration work: `connectors.md`
- Jobs, worker, retry, or scheduler work: `jobs-scheduler.md`
- Audit export, verification, or external checkpoints: `audit-integrity.md`
- Payload encryption, secret refs, or AWS KMS: `payload-secrets-kms.md`
- Readiness, metrics, rate limiting, or operator settings: `observability-ops.md`
- Web UI work: `frontend.md`
- Test, workflow, or verification changes: `testing-ci.md`
- Compose, env vars, or production posture: `deployment.md`
- Scoping future work: `roadmap.md`
