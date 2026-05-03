from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

import httpx

from app.core.redaction import redact_sensitive_data, redact_sensitive_string
from app.security.secret_references import (
    SecretResolutionError,
    build_env_secret_reference,
    get_secret_resolver,
)

SLACK_API_BASE_URL = "https://slack.com/api"
DEFAULT_SLACK_TOKEN_ENV_VAR = "AGENTGATE_SLACK_BOT_TOKEN"
MAX_FIELD_LENGTH = 280
MAX_ARGUMENT_SUMMARY_LENGTH = 500


@dataclass(slots=True)
class SlackApprovalSummary:
    approval_id: str
    tenant_id: str
    agent_name: str
    agent_id: str
    tool_name: str
    action_name: str
    risk_score: float
    risk_band: str
    policy_names: list[str]
    original_intent: str
    sanitized_arguments: dict
    dashboard_url: str | None
    trace_id: str | None
    request_id: str | None
    channel: str | None = None


@dataclass(slots=True)
class SlackNotificationResult:
    status: str
    code: str
    detail: str
    request_id: str | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == "sent"


@dataclass(slots=True)
class SlackHealthResult:
    status: str
    enabled: bool
    configured: bool
    token_env_var: str
    default_channel: str | None
    probe_performed: bool
    can_connect: bool | None
    details: dict = field(default_factory=dict)


class SlackNotifier:
    provider_name = "slack"

    def __init__(self, client_factory: Callable[..., httpx.Client] | None = None) -> None:
        self.client_factory = client_factory

    def send_approval_notification(
        self,
        summary: SlackApprovalSummary,
        *,
        token_env_var: str = DEFAULT_SLACK_TOKEN_ENV_VAR,
        default_channel: str | None = None,
        timeout_seconds: float = 5.0,
    ) -> SlackNotificationResult:
        secret_reference = build_env_secret_reference(token_env_var)
        try:
            token = get_secret_resolver().resolve(secret_reference, allow_bare_env=False).value
        except SecretResolutionError:
            token = ""
        channel = (summary.channel or default_channel or "").strip()

        if not token:
            return SlackNotificationResult(
                status="failed",
                code="slack_token_missing",
                detail="Slack bot token is not configured for this environment.",
                metadata={"token_env_var": token_env_var, "secret_reference": secret_reference},
            )
        if not channel:
            return SlackNotificationResult(
                status="failed",
                code="slack_channel_missing",
                detail="Slack default channel is not configured.",
            )

        payload = self._build_message(summary, channel=channel)
        try:
            with self._build_client(token=token, timeout_seconds=timeout_seconds) as client:
                response = client.post("/chat.postMessage", json=payload)
        except httpx.TimeoutException:
            return SlackNotificationResult(
                status="failed",
                code="slack_timeout",
                detail="Slack did not respond before the notification timeout elapsed.",
            )
        except httpx.RequestError:
            return SlackNotificationResult(
                status="failed",
                code="slack_network_error",
                detail="Slack notification could not be delivered because the network request failed.",
            )

        return self._handle_message_response(response)

    def health_check(
        self,
        *,
        enabled: bool,
        token_env_var: str,
        default_channel: str | None,
        timeout_seconds: float,
        probe: bool,
    ) -> SlackHealthResult:
        secret_reference = build_env_secret_reference(token_env_var)
        try:
            token = get_secret_resolver().resolve(secret_reference, allow_bare_env=False).value
        except SecretResolutionError:
            token = ""
        configured = bool(token and (default_channel or "").strip())
        if not enabled:
            return SlackHealthResult(
                status="disabled",
                enabled=False,
                configured=configured,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=False,
                can_connect=None,
            )
        if not token:
            return SlackHealthResult(
                status="unconfigured",
                enabled=True,
                configured=False,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=False,
                can_connect=None,
                details={"error_code": "slack_token_missing", "secret_reference": secret_reference},
            )
        if not default_channel:
            return SlackHealthResult(
                status="unconfigured",
                enabled=True,
                configured=False,
                token_env_var=token_env_var,
                default_channel=None,
                probe_performed=False,
                can_connect=None,
                details={"error_code": "slack_channel_missing"},
            )
        if not probe:
            return SlackHealthResult(
                status="ready",
                enabled=True,
                configured=True,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=False,
                can_connect=None,
            )

        try:
            with self._build_client(token=token, timeout_seconds=timeout_seconds) as client:
                response = client.post("/auth.test")
        except httpx.TimeoutException:
            return SlackHealthResult(
                status="degraded",
                enabled=True,
                configured=True,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=True,
                can_connect=False,
                details={"error_code": "slack_timeout"},
            )
        except httpx.RequestError:
            return SlackHealthResult(
                status="degraded",
                enabled=True,
                configured=True,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=True,
                can_connect=False,
                details={"error_code": "slack_network_error"},
            )

        if response.status_code >= 500:
            return SlackHealthResult(
                status="degraded",
                enabled=True,
                configured=True,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=True,
                can_connect=False,
                details={"error_code": "slack_upstream_unavailable"},
            )

        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code == 429:
            return SlackHealthResult(
                status="degraded",
                enabled=True,
                configured=True,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=True,
                can_connect=False,
                details={"error_code": "slack_rate_limited"},
            )
        if payload.get("ok") is True:
            return SlackHealthResult(
                status="ready",
                enabled=True,
                configured=True,
                token_env_var=token_env_var,
                default_channel=default_channel,
                probe_performed=True,
                can_connect=True,
                details={"team": redact_sensitive_string(str(payload.get("team") or ""))},
            )

        return SlackHealthResult(
            status="degraded",
            enabled=True,
            configured=True,
            token_env_var=token_env_var,
            default_channel=default_channel,
            probe_performed=True,
            can_connect=False,
            details={"error_code": self._slack_error_code(payload.get("error"))},
        )

    def _build_client(self, *, token: str, timeout_seconds: float) -> httpx.Client:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        if self.client_factory:
            return self.client_factory(base_url=SLACK_API_BASE_URL, headers=headers, timeout=timeout_seconds)
        return httpx.Client(base_url=SLACK_API_BASE_URL, headers=headers, timeout=timeout_seconds, follow_redirects=True)

    def _build_message(self, summary: SlackApprovalSummary, *, channel: str) -> dict:
        policy_names = ", ".join(summary.policy_names[:5]) if summary.policy_names else "No explicit policy match"
        dashboard_bits = []
        if summary.dashboard_url:
            dashboard_bits.append(f"<{summary.dashboard_url.rstrip('/')}/approvals|Open AgentGate approval inbox>")
        if summary.trace_id and summary.dashboard_url:
            trace_url = f"{summary.dashboard_url.rstrip('/')}/traces/{summary.trace_id}"
            dashboard_bits.append(f"<{trace_url}|View trace>")
        context_bits = [f"Approval ID: {summary.approval_id}"]
        if summary.trace_id:
            context_bits.append(f"Trace ID: {summary.trace_id}")
        if summary.request_id:
            context_bits.append(f"Request ID: {summary.request_id}")

        arguments_summary = self._format_arguments(summary.sanitized_arguments)
        intent_text = self._truncate(summary.original_intent, MAX_FIELD_LENGTH)
        text = (
            f"AgentGate approval needed: {summary.agent_name} wants to run "
            f"{summary.tool_name}.{summary.action_name} with {summary.risk_band} risk."
        )

        return {
            "channel": channel,
            "text": text,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "AgentGate approval required", "emoji": True},
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Agent*\n{self._truncate(summary.agent_name, 80)}"},
                        {"type": "mrkdwn", "text": f"*Agent ID*\n{summary.agent_id}"},
                        {"type": "mrkdwn", "text": f"*Tool*\n{self._truncate(summary.tool_name, 80)}"},
                        {"type": "mrkdwn", "text": f"*Action*\n{self._truncate(summary.action_name, 80)}"},
                        {"type": "mrkdwn", "text": f"*Risk*\n{summary.risk_score:.0f} ({summary.risk_band})"},
                        {"type": "mrkdwn", "text": f"*Policies*\n{self._truncate(policy_names, MAX_FIELD_LENGTH)}"},
                    ],
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Original intent*\n{intent_text}"},
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Sanitized arguments*\n```{arguments_summary}```"},
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": " | ".join(context_bits)},
                    ],
                },
                *(
                    [
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": " | ".join(dashboard_bits)},
                        }
                    ]
                    if dashboard_bits
                    else []
                ),
            ],
        }

    def _handle_message_response(self, response: httpx.Response) -> SlackNotificationResult:
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        if response.status_code == 429:
            return SlackNotificationResult(
                status="failed",
                code="slack_rate_limited",
                detail="Slack rate limited the notification request.",
            )
        if response.status_code >= 500:
            return SlackNotificationResult(
                status="failed",
                code="slack_upstream_unavailable",
                detail="Slack is temporarily unavailable.",
            )
        if response.status_code in {401, 403}:
            return SlackNotificationResult(
                status="failed",
                code="slack_auth_failed",
                detail="Slack rejected the notification credentials.",
            )

        if payload.get("ok") is True:
            metadata = {"channel": payload.get("channel"), "ts": payload.get("ts")}
            return SlackNotificationResult(
                status="sent",
                code="slack_notification_sent",
                detail="Slack notification sent successfully.",
                metadata=redact_sensitive_data(metadata),
            )

        error_code = self._slack_error_code(payload.get("error"))
        return SlackNotificationResult(
            status="failed",
            code=error_code,
            detail=self._slack_error_detail(error_code),
        )

    def _slack_error_code(self, error: str | None) -> str:
        mapping = {
            "invalid_auth": "slack_auth_failed",
            "not_authed": "slack_auth_failed",
            "channel_not_found": "slack_channel_not_found",
            "is_archived": "slack_channel_not_found",
            "ratelimited": "slack_rate_limited",
        }
        return mapping.get(str(error or "").strip(), "slack_request_failed")

    def _slack_error_detail(self, error_code: str) -> str:
        details = {
            "slack_auth_failed": "Slack rejected the notification credentials.",
            "slack_channel_not_found": "Slack could not find the configured destination channel.",
            "slack_rate_limited": "Slack rate limited the notification request.",
            "slack_request_failed": "Slack rejected the notification request.",
        }
        return details.get(error_code, "Slack notification failed.")

    def _format_arguments(self, sanitized_arguments: dict) -> str:
        safe_arguments = redact_sensitive_data(sanitized_arguments)
        rendered = json.dumps(safe_arguments, sort_keys=True, ensure_ascii=True)
        return self._truncate(rendered, MAX_ARGUMENT_SUMMARY_LENGTH)

    def _truncate(self, value: str, limit: int) -> str:
        normalized = redact_sensitive_string(str(value).strip())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: max(0, limit - 3)]}..."
