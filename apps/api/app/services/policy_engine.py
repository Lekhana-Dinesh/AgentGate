from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import PolicyDecision, PolicySeverity
from app.models import Policy
from app.schemas.common import PolicyConditionSet
from app.schemas.gateway import PolicyEvaluationResult, PolicyMatch

DECISION_PRECEDENCE = {
    PolicyDecision.BLOCK: 4,
    PolicyDecision.REQUIRE_APPROVAL: 3,
    PolicyDecision.REDACT: 2,
    PolicyDecision.ALLOW: 1,
}

SEVERITY_PRECEDENCE = {
    PolicySeverity.CRITICAL: 4,
    PolicySeverity.HIGH: 3,
    PolicySeverity.MEDIUM: 2,
    PolicySeverity.LOW: 1,
}


@dataclass(slots=True)
class PolicyContext:
    tool_name: str
    action_name: str
    recipient_domain: str
    data_classifications: list[str]
    risk_score: float
    environment: str
    amount: float | None
    discount_percent: float | None
    row_count: int | None
    intent_mismatch: bool
    repo_trust: str = "unknown"


class PolicyEngine:
    def evaluate(self, policies: list[Policy], ctx: PolicyContext) -> PolicyEvaluationResult:
        matches: list[PolicyMatch] = []
        reasons: list[str] = []
        best_policy: Policy | None = None

        for policy in policies:
            if not policy.enabled:
                continue

            try:
                document = PolicyConditionSet.model_validate(policy.conditions or {})
            except Exception:
                if ctx.risk_score >= 80 or ctx.environment == "production":
                    return PolicyEvaluationResult(
                        decision=PolicyDecision.BLOCK,
                        matched_policies=[],
                        reasons=["Policy parsing failed under high-risk conditions, so AgentGate failed closed."],
                    )
                reasons.append(f"Skipped malformed policy {policy.name}.")
                continue

            evaluations = [self._evaluate_rule(rule.field, rule.operator, rule.value, ctx) for rule in document.rules]
            matched = all(evaluations) if document.match == "all" else any(evaluations)
            if not matched:
                continue

            matches.append(
                PolicyMatch(
                    policy_id=policy.id,
                    name=policy.name,
                    severity=policy.severity.value,
                    decision=policy.decision.value,
                )
            )
            reasons.append(f"Policy {policy.name} matched.")
            if self._policy_priority(policy) > self._policy_priority(best_policy):
                best_policy = policy

        return PolicyEvaluationResult(
            decision=best_policy.decision if best_policy else PolicyDecision.ALLOW,
            matched_policies=matches,
            reasons=reasons,
        )

    def _evaluate_rule(self, field: str, operator: str, value, ctx: PolicyContext) -> bool:
        candidate = {
            "tool_name": ctx.tool_name,
            "action_name": ctx.action_name,
            "recipient_domain": ctx.recipient_domain,
            "repo_trust": ctx.repo_trust,
            "data_classification": ctx.data_classifications,
            "risk_score": ctx.risk_score,
            "environment": ctx.environment,
            "amount": ctx.amount or 0,
            "discount_percent": ctx.discount_percent or 0,
            "row_count": ctx.row_count or 0,
            "intent_mismatch": ctx.intent_mismatch,
        }[field]

        if operator == "equals":
            return self._equals(candidate, value)
        if operator == "contains":
            if isinstance(candidate, list):
                return any(str(item).lower() == str(value).lower() for item in candidate)
            return str(value).lower() in str(candidate).lower()
        if operator == "greater_than":
            try:
                return float(candidate) > float(value)
            except (TypeError, ValueError):
                return False
        return False

    def _equals(self, candidate, value) -> bool:
        if isinstance(candidate, list):
            return any(str(item).lower() == str(value).lower() for item in candidate)
        if isinstance(candidate, str):
            return candidate.lower() == str(value).lower()
        return candidate == value

    def _policy_priority(self, policy: Policy | None) -> tuple[int, int, str]:
        if not policy:
            return (0, 0, "")
        return (
            DECISION_PRECEDENCE[policy.decision],
            SEVERITY_PRECEDENCE[policy.severity],
            policy.name,
        )
