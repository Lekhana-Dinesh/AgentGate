# Retention And Purge

## Overview

AgentGate protects sensitive execution arguments before persistence and now enforces retention by redacting expired protected payloads after their retention window. Purge is designed to preserve compliance evidence and operator visibility without preserving replayable secrets.

## Retention classes

- `standard`: default non-sensitive or lightly sensitive retention window. Current default is 30 days.
- `short_lived`: protected payloads that primarily exist to support near-term execution replay. Current default is 7 days.
- `extended`: protected payloads tied to higher-sensitivity content controls such as internal pricing or confidential content. Current default is 90 days.
- `legal_hold`: never purged automatically.

Legacy `restricted` values are treated as `extended` for purge eligibility.

## What gets purged

- `ToolCall.request_payload.execution_arguments`
- Only the protected execution payload is redacted
- Purge replaces the stored protected payload with a non-sensitive tombstone marker and updates `payload_redaction_status` to `purged`

## What remains for audit

- `ToolCall.request_payload.arguments` sanitized operator-facing summary
- `ToolCall.status`
- `ToolCall.risk_score`
- `ToolCall.decision_reason`
- `ToolCall.payload_protection_version`
- `ToolCall.payload_retention_class`
- `ToolCall.payload_expires_at`
- Trace references and trace content
- Audit event references and historical sanitized metadata

## Execution safety

- Retention purge never decrypts protected payloads.
- Approved execution decrypts only inside the trusted execution path.
- If a reviewer approves `execute_now=true` after the payload has already been purged, the approved-execution job fails closed with `protected_payload_purged`.
- GitHub write actions still run single-attempt only. Retention does not change connector write retry rules.

## Dry-run mode

- `POST /v1/retention/purge` defaults to `dry_run=true`
- Dry-run writes a durable retention job but does not mutate `ToolCall` records
- The result reports how many matching protected payloads are eligible, already purged, legal hold, or still not expired

## Legal hold

- `legal_hold` payloads are excluded from automatic purge even if `payload_expires_at` is in the past
- The current build expects legal hold to be set through trusted backend workflows or operational administration, not through a dedicated end-user UI

## Job model

- Purge runs through the durable jobs system using the `retention_purge.placeholder` wire value
- The wire value is retained for compatibility, but the handler is real
- Purge jobs can retry safely because the operation is idempotent and never replays protected values
- Already-purged tool calls are skipped on later runs

## Production recommendations

- Run worker mode for production-like deployments and schedule recurring purge through an external scheduler or automation platform
- Monitor retention job failures and `payload_redaction_status="purge_failed"`
- Align retention class defaults with your internal records-management and privacy requirements
- Prefer a KMS-backed encryption provider and explicit key-rotation process before storing highly sensitive production data
- Keep audit retention longer than payload retention where policy requires after-the-fact investigation

## Current limitations

- There is no built-in recurring purge scheduler yet
- There is no dedicated legal-hold workflow UI yet
- Purge operates at the `ToolCall` execution payload level, not at a broader evidence lifecycle or external archive lifecycle
- There is no cryptographic erasure or multi-key version retirement workflow yet
