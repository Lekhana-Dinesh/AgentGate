# Slack Approval Notifications

## What This Integration Does

AgentGate can send a best-effort Slack notification when a high-risk `ApprovalRequest` is created.

The Slack alert is an outbound reviewer notification only. It does not approve, reject, or execute actions from Slack in this version.

## What Gets Sent

When enabled, AgentGate sends a redacted approval summary that can include:

- Approval ID
- Agent name and ID
- Tool name
- Action name
- Risk score and risk band
- Triggered policy names, when available
- Original intent
- Sanitized arguments summary
- Request ID and trace ID, when available
- AgentGate dashboard links, when `AGENTGATE_PUBLIC_APP_URL` is configured

## What Does Not Get Sent

- Raw Slack bot tokens
- Raw authorization headers
- Raw tool execution arguments
- Full tool payloads
- Secrets or token-like strings that match the built-in redaction rules

## Configuration

Set these environment variables for the API process:

```bash
AGENTGATE_SLACK_NOTIFICATIONS_ENABLED=true
AGENTGATE_SLACK_BOT_TOKEN_ENV_VAR=AGENTGATE_SLACK_BOT_TOKEN
AGENTGATE_SLACK_BOT_TOKEN=xoxb-your-bot-token
AGENTGATE_SLACK_DEFAULT_CHANNEL=C0123456789
AGENTGATE_PUBLIC_APP_URL=http://localhost:3000
```

Notes:

- `AGENTGATE_SLACK_DEFAULT_CHANNEL` may be a channel ID or a user/DM destination your Slack app can message.
- The default demo does not require Slack and works with notifications disabled.
- Do not store raw Slack bot tokens in database config or tool config.
- `AGENTGATE_SLACK_BOT_TOKEN_ENV_VAR` is resolved through the shared secret-reference layer, so the current build stays env-backed while keeping the resolver pattern consistent with future secret-manager integrations.

## Local Testing

1. Export the Slack environment variables above.
2. Start AgentGate.
3. Trigger an approval-producing flow such as the demo sales scenario or a risky external email tool call.
4. Confirm the approval remains pending inside AgentGate.
5. Confirm a Slack message is delivered to the configured destination.
6. Use `GET /v1/integrations/slack/health` to confirm configuration status.
7. Use `GET /v1/integrations/slack/health?probe=true` for a safe `auth.test` connectivity check.

## API Surface

- `GET /v1/integrations/slack/health`
- `GET /v1/approvals/{approval_id}/notification-status`

Approval list responses may also include:

```json
{
  "notification_status": {
    "provider": "slack",
    "status": "sent"
  }
}
```

## Security Model

- Slack notifications are optional and disabled by default.
- Slack failures are non-fatal and never change the approval decision.
- Notification success and failure are written as audit events.
- Slack messages are built from sanitized data only.
- Slack delivery is already queue-backed through the durable jobs foundation when `AGENTGATE_JOB_DISPATCH_MODE=worker`.
- AgentGate uses environment-based token injection in this build for development convenience.

Production guidance:

- Inject Slack credentials from a cloud secret manager or KMS-backed platform secret store.
- Restrict the Slack app to the smallest viable scopes and destinations.
- Review message retention and workspace export posture for your Slack environment.

## Production Hardening Checklist

- Move bot token storage to a managed secret store.
- Add tenant-managed Slack integration records with per-tenant routing.
- Add dead-letter handling and stronger worker orchestration for notification retries.
- Add metrics and alerts for notification failures and rate limiting.
- Add signed interactive Slack actions before supporting approve/reject from Slack.
- Add stronger reviewer routing such as team-based escalation or assignment rules.
- Review outbound message content against your internal data handling policy.

## Future Interactive Approval Path

Future versions can add Slack approve/reject actions only after implementing:

- Signed Slack request verification
- Replay protection
- Fine-grained approver authorization checks inside AgentGate
- Expiring action URLs or short-lived interaction tokens
- Full audit logging for Slack-originated decisions

Until then, reviewers must complete approvals in the AgentGate dashboard or API.
