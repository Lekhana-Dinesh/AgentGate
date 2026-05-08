# Roadmap Context

## 1. Purpose

This file gives future Codex sessions a narrow summary of what AgentGate has not shipped yet, so planning work stays honest.

## 2. Main files/directories

- `docs/ROADMAP.md`
- `docs/SECURITY.md`
- `docs/ARCHITECTURE.md`
- `docs/AGENTGATE_CODEX_HANDOFF.md`

## 3. Current capabilities

- Near-term product direction around richer connectors, UI improvements, better audit filtering, pagination, and policy UX
- Security hardening direction around broader identity, secrets, and stronger immutable evidence options
- Platform direction around orchestration, observability, scale, and background automation
- Decision-intelligence direction around hybrid intent analysis, simulation, and feedback loops

## 4. Critical invariants / must-not-break rules

- Do not describe roadmap items as shipped capabilities.
- Do not quietly remove known limitations from docs without actually closing them in code and tests.
- Keep security and enterprise claims honest.
- When a roadmap item lands, update both the domain context docs and the broader product and security docs.

## 5. Security boundaries

- Future plans such as SAML, broader SCIM coverage, Vault-style secret resolution, or stronger immutable evidence options are not current guarantees.
- Compliance, certification, or managed-platform claims remain out of bounds unless explicitly implemented and documented.

## 6. Known limitations

- The roadmap is a planning document and can drift as the repo evolves.
- Many roadmap items are cross-cutting and require coordinated changes across backend, frontend, docs, tests, and deployment surfaces.

## 7. Relevant tests

- No single test file owns the roadmap.
- Use the relevant domain tests once work moves from roadmap to implementation.

## 8. When future Codex sessions should read this file

Read this when scoping new features, answering "does this already exist," prioritizing follow-on enterprise work, or writing honest product-facing summaries.
