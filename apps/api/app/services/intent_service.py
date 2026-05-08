from __future__ import annotations

from dataclasses import dataclass

from app.schemas.gateway import IntentCheckResult

SENSITIVE_DATA_CLASSES = {"internal_pricing", "confidential", "pii", "financial"}
SEND_KEYWORDS = {"send", "email", "share", "deliver"}
COMMENT_KEYWORDS = {"comment", "reply", "post"}
ISSUE_KEYWORDS = {"issue", "ticket"}
ASSIGN_KEYWORDS = {"assign", "owner"}
TRANSITION_KEYWORDS = {"transition", "move", "status"}
DELETE_KEYWORDS = {"delete", "remove", "purge"}
EXPORT_KEYWORDS = {"export", "dump", "download"}
REFUND_KEYWORDS = {"refund", "credit", "discount"}


@dataclass(slots=True)
class IntentContext:
    original_intent: str
    tool_name: str
    action_name: str
    arguments: dict
    data_classifications: list[str]


class IntentService:
    def evaluate(self, ctx: IntentContext) -> IntentCheckResult:
        intent_text = ctx.original_intent.lower()
        remote_tool_name = str(ctx.arguments.get("tool_name") or "").strip()
        action_text = f"{ctx.tool_name} {ctx.action_name} {remote_tool_name}".lower()
        reasons: list[str] = []

        if any(keyword in action_text for keyword in SEND_KEYWORDS) and not any(
            keyword in intent_text for keyword in SEND_KEYWORDS
        ):
            reasons.append("The action sends information, but the original intent did not authorize sending.")

        if any(keyword in action_text for keyword in COMMENT_KEYWORDS) and not any(
            keyword in intent_text for keyword in COMMENT_KEYWORDS | SEND_KEYWORDS
        ):
            reasons.append("The action posts a comment, but the original intent does not mention posting or replying.")

        if any(keyword in action_text for keyword in ISSUE_KEYWORDS) and not any(
            keyword in intent_text for keyword in ISSUE_KEYWORDS
        ):
            reasons.append("The action creates or changes work items, but the original intent does not mention that workflow.")

        if any(keyword in action_text for keyword in ASSIGN_KEYWORDS) and not any(
            keyword in intent_text for keyword in ASSIGN_KEYWORDS | ISSUE_KEYWORDS
        ):
            reasons.append("The action assigns work, but the original intent does not mention assignment authority.")

        if any(keyword in action_text for keyword in TRANSITION_KEYWORDS) and not any(
            keyword in intent_text for keyword in TRANSITION_KEYWORDS | ISSUE_KEYWORDS
        ):
            reasons.append("The action changes workflow state, but the original intent does not mention that transition.")

        if any(keyword in action_text for keyword in DELETE_KEYWORDS) and not any(
            keyword in intent_text for keyword in DELETE_KEYWORDS
        ):
            reasons.append(
                "The action deletes or removes data, but the original intent does not mention deletion."
            )

        if any(keyword in action_text for keyword in EXPORT_KEYWORDS) and not any(
            keyword in intent_text for keyword in EXPORT_KEYWORDS
        ):
            reasons.append(
                "The action exports data, but the original intent does not mention exporting or downloading."
            )

        if any(keyword in action_text for keyword in REFUND_KEYWORDS):
            amount = float(
                ctx.arguments.get("discount_percent")
                or ctx.arguments.get("amount")
                or ctx.arguments.get("refund_amount")
                or 0
            )
            if amount > 0 and not any(keyword in intent_text for keyword in REFUND_KEYWORDS):
                reasons.append(
                    "The action changes pricing or money movement, but the original intent does not mention that authority."
                )

        recipient = str(ctx.arguments.get("recipient") or ctx.arguments.get("email_to") or "")
        recipient_domain = recipient.split("@")[-1].lower() if "@" in recipient else ""
        internal_domains = {
            domain.lower()
            for domain in ctx.arguments.get("internal_domains", ["agentgate.local", "acme.internal"])
        }
        external_recipient = bool(recipient_domain and recipient_domain not in internal_domains)
        sensitive_externalization = external_recipient and any(
            item in SENSITIVE_DATA_CLASSES for item in ctx.data_classifications
        )
        if sensitive_externalization:
            reasons.append("Sensitive data is being routed to an external recipient.")

        repository_visibility = str(
            ctx.arguments.get("repository_visibility") or ctx.arguments.get("visibility") or ""
        ).lower()
        if (
            repository_visibility == "public"
            and any(item in SENSITIVE_DATA_CLASSES for item in ctx.data_classifications)
            and any(keyword in action_text for keyword in COMMENT_KEYWORDS | ISSUE_KEYWORDS)
        ):
            reasons.append("Sensitive data is being posted to a public repository workflow.")

        if ctx.arguments.get("irreversible") is True and "confirm" not in intent_text:
            reasons.append("The action is marked irreversible without an explicit confirmation signal in intent.")

        intent_match = not reasons
        confidence = 0.92 if intent_match else max(0.2, 0.85 - (0.15 * len(reasons)))
        explanation = (
            "The proposed action is consistent with the user's stated business intent."
            if intent_match
            else "The proposed action includes behaviors that were not clearly authorized by the original intent."
        )
        return IntentCheckResult(
            intent_match=intent_match,
            confidence=round(confidence, 2),
            explanation=explanation,
            detected_mismatch_reasons=reasons,
        )
