# Screenshot Checklist

Use this checklist when preparing a leave-behind deck, design-partner review packet, or investor follow-up.

- Dashboard: capture `/` with runtime stats and reviewer workload visible. This is the best first screenshot for non-technical buyers.
- Gateway and Tool Calls: capture `/tool-calls` with decisions, statuses, and sanitized payload summaries visible.
- Approvals: capture `/approvals` with at least one risky action in review.
- Jobs: capture `/jobs` showing durable governance work such as notifications, approved execution, exports, retention, or checkpointing.
- Scheduled Tasks: capture `/scheduled-tasks` if you want to show recurring controls without external cron.
- Audit Integrity and Checkpoint: capture `/audit-integrity` with chain status, latest checkpoint, and verify or create actions.
- Audit Exports: capture `/audit-exports` showing non-sensitive destination status and last-run state.
- Retention: capture `/retention` with dry-run status or eligible payload counts to show minimization of replayable sensitive state.
- Settings: capture `/settings` showing safe readiness and integration status without raw secrets.
- Users and Identity: capture `/users` showing role, status, and provisioning source to support the identity-lifecycle story.
- GitHub Connector Docs or Config: capture `docs/connectors/github.md` or a safe tool configuration view that shows supported auth modes without exposing secrets.
- Metrics and Readiness: capture `/ready` and `/metrics` only if the audience cares about operations, self-hosting, or deployment posture.

Recommended prep:

- Run the seeded demo scenario first so the pages contain meaningful data.
- Prefer screenshots that show sanitized operator visibility, not empty states.
- Avoid screenshots with local secrets, shell history, or environment variable dumps.
