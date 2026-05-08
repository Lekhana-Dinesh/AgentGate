# AgentGate Codex Handoff

This is the short global handoff for future Codex sessions.

Read this file first. Then read only the relevant `docs/context/*.md` files for the task before inspecting source and tests.

## What AgentGate Is

AgentGate is an agent runtime control plane for enterprise AI agents.

It intercepts tool calls, applies tenant-aware identity and governance controls, and then allows, blocks, requires approval, audits, traces, exports, and optionally executes through governed adapters.

## Repo Guardrails

- Preserve the existing architecture and naming. Do not rewrite the project.
- All business data is tenant-scoped.
- Do not bypass gateway governance for tool execution.
- Do not weaken tenant isolation in queries, APIs, jobs, traces, approvals, exports, or UI views.
- Do not expose decrypted payloads, raw secrets, tokens, private keys, or unsafe config bodies.
- Browser auth now supports both local JWT token mode and an optional HttpOnly cookie session mode with CSRF enforcement. Preserve machine-client bearer/API-key auth separation.
- Audit integrity is tamper-evident. External checkpoints are stronger evidence preservation, not a valid immutability claim unless the destination enforces WORM or Object Lock semantics.
- Keep local development simple and fail closed in production-like environments.

## Read Order

1. Read this file.
2. Read [`docs/context/README.md`](context/README.md).
3. Read only the relevant domain files from `docs/context/`.
4. Inspect the owning source files and tests before editing.

## Domain Context Index

- [`docs/context/gateway.md`](context/gateway.md)
- [`docs/context/auth-identity.md`](context/auth-identity.md)
- [`docs/context/connectors.md`](context/connectors.md)
- [`docs/context/jobs-scheduler.md`](context/jobs-scheduler.md)
- [`docs/context/audit-integrity.md`](context/audit-integrity.md)
- [`docs/context/payload-secrets-kms.md`](context/payload-secrets-kms.md)
- [`docs/context/observability-ops.md`](context/observability-ops.md)
- [`docs/context/frontend.md`](context/frontend.md)
- [`docs/context/testing-ci.md`](context/testing-ci.md)
- [`docs/context/deployment.md`](context/deployment.md)
- [`docs/context/roadmap.md`](context/roadmap.md)

## Broad Reference Docs

- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/SECURITY.md`
- `docs/ROADMAP.md`

Read these broader docs only if the domain context file is not enough for the task.

## Verification Guidance

- Run targeted tests for the domains you change.
- If you change docs, examples, workflows, or config surfaces, run `python scripts/check-no-live-secrets.py`.
- Use the CI and verification guidance in `docs/context/testing-ci.md` when choosing broader checks.
