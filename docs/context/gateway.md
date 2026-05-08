# Gateway Context

## 1. Purpose

This file summarizes AgentGate's runtime decision path for tool calls.

Read it before changing gateway execution, policy evaluation, approval routing, payload persistence, or trace behavior.

## 2. Main files/directories

- `apps/api/app/services/gateway_service.py`: core runtime decision flow
- `apps/api/app/api/routes/gateway.py`: gateway HTTP surface
- `apps/api/app/services/intent_service.py`: deterministic intent analysis
- `apps/api/app/services/risk_service.py`: baseline risk scoring
- `apps/api/app/services/policy_engine.py`: policy evaluation
- `apps/api/app/services/approval_service.py`: approval creation and resolution
- `apps/api/app/services/trace_service.py`: trace creation and updates
- `apps/api/app/services/payload_service.py`: sanitized and protected payload views
- `apps/api/app/models/tool_call.py`, `approval_request.py`, `execution_trace.py`, `trace_step.py`
- `apps/api/app/tools/base.py`, `registry.py`: adapter boundary

## 3. Current capabilities

- Tenant-aware `POST /v1/gateway/tool-call` flow with JWT or agent API key authentication
- Deterministic intent analysis, baseline risk scoring, and policy evaluation
- Conservative repo-shipped pilot policy pack under `policy-packs/pilot-default/` that maps existing gateway signals into approval-heavy starter policies
- Policy management APIs plus a narrow browser review and starter-template surface for owner/admin operators without changing gateway policy semantics
- Built-in fail-closed guardrails for uncertain high-risk behavior
- Trace creation and pending-approval trace locking
- Sensitive execution arguments protected before persistence
- Sanitized `ToolCall`, `AuditEvent`, and trace persistence
- Approval creation, optional Slack notification job creation, and immediate or queued execution depending on decision and mode

## 4. Critical invariants / must-not-break rules

- Never bypass the normal gateway flow for convenience.
- Keep every business read and write tenant-scoped.
- Do not execute a connector directly from a route without going through gateway governance.
- Do not rewrite policy evaluation semantics to fit the browser UX. The UI must adapt to the deterministic engine, not the other way around.
- `request_payload.arguments` stays sanitized. `execution_arguments` stays protected and backend-only.
- Approval-required actions must not silently execute.
- Pending traces must remain locked against hidden extra steps.

## 5. Security boundaries

- The gateway is the control point between callers and external tools.
- Tool adapters are downstream of identity, tenant, policy, risk, approval, audit, and trace checks.
- Protected payload decryption only happens on trusted execution paths.
- Audit writes and trace data must not leak secrets or decrypted payloads.
- Policy packs and browser templates can help operators author rules, but they do not replace connector allowlists, trust hints, or reviewer coverage.

## 6. Known limitations

- Intent and risk are deterministic heuristics today, not model-assisted evaluation.
- The current connector set is still small: GitHub is the strongest first live connector, Jira is better as a constrained optional second phase, and MCP should stay disabled by default unless it is internal and tightly allowlisted.
- Rate limiting is fixed-window and not yet proxy-trust-aware.
- Some write paths still depend on inline execution in local mode rather than always using a separate worker.
- The browser policy UX is intentionally narrow: guided starter templates plus enable or disable review, while deeper pack customization and exact policy surgery remain API or script driven.

## 7. Relevant tests

- `apps/api/app/tests/test_gateway.py`
- `apps/api/app/tests/test_api_keys.py`
- `apps/api/app/tests/test_slack_notifications.py`
- `load-tests/k6/gateway.js`

## 8. When future Codex sessions should read this file

Read this before editing gateway routes, tool-call persistence, approval creation, trace semantics, policy hooks, pilot policy packs, intent or risk evaluation, or adapter invocation boundaries.
