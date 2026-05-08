from __future__ import annotations

from dataclasses import dataclass

from app.core.enums import PolicySeverity, RiskBand
from app.schemas.gateway import RiskAssessmentFactor, RiskAssessmentResult


ACTION_RISK_WEIGHTS = {
    "read": 5,
    "list": 5,
    "search": 5,
    "query": 10,
    "create": 15,
    "issue": 12,
    "comment": 18,
    "post": 15,
    "pull_request": 10,
    "assign": 12,
    "transition": 18,
    "write": 18,
    "update": 20,
    "send": 25,
    "transfer": 30,
    "execute": 30,
    "shell": 35,
    "admin": 20,
    "delete": 35,
    "export": 40,
    "refund": 30,
    "discount": 25,
}

TOOL_RISK_WEIGHTS = {
    RiskBand.LOW: 5,
    RiskBand.MEDIUM: 15,
    RiskBand.HIGH: 30,
    RiskBand.CRITICAL: 40,
}

POLICY_SEVERITY_WEIGHTS = {
    PolicySeverity.LOW: 5,
    PolicySeverity.MEDIUM: 10,
    PolicySeverity.HIGH: 15,
    PolicySeverity.CRITICAL: 20,
}


@dataclass(slots=True)
class RiskInput:
    tool_risk: RiskBand
    action_name: str
    data_classifications: list[str]
    recipient_domain: str | None
    environment: str
    amount: float | None = None
    discount_percent: float | None = None
    monetary_amount: float | None = None
    row_count: int | None = None
    irreversible: bool = False
    intent_mismatch: bool = False
    max_policy_severity: PolicySeverity | None = None


class RiskService:
    def assess(self, data: RiskInput) -> RiskAssessmentResult:
        score = TOOL_RISK_WEIGHTS[data.tool_risk]
        reasons = [f"Tool risk baseline is {data.tool_risk.value}."]
        factors = [
            RiskAssessmentFactor(
                key=f"tool_risk:{data.tool_risk.value}",
                label="Tool risk baseline",
                category="baseline",
                weight=float(TOOL_RISK_WEIGHTS[data.tool_risk]),
                explanation=f"The configured tool risk level is {data.tool_risk.value}.",
            )
        ]
        action_lower = data.action_name.lower()

        for keyword, weight in ACTION_RISK_WEIGHTS.items():
            if keyword in action_lower:
                score += weight
                reasons.append(f"Action contains {keyword}, increasing operational risk.")
                factors.append(
                    RiskAssessmentFactor(
                        key=f"action:{keyword}",
                        label=f"Action keyword: {keyword}",
                        category="action",
                        weight=float(weight),
                        explanation=f"The action name contains {keyword}.",
                    )
                )

        if data.environment == "production":
            score += 10
            reasons.append("Production environment raises the blast radius.")
            factors.append(
                RiskAssessmentFactor(
                    key="environment:production",
                    label="Production environment",
                    category="environment",
                    weight=10.0,
                    explanation="Production activity has a higher blast radius than lower environments.",
                )
            )

        if data.recipient_domain == "external":
            score += 15
            reasons.append("External recipient increases data exposure risk.")
            factors.append(
                RiskAssessmentFactor(
                    key="recipient:external",
                    label="External recipient",
                    category="recipient",
                    weight=15.0,
                    explanation="External recipients increase the chance of unintended data disclosure.",
                )
            )
        elif data.recipient_domain == "unknown":
            score += 8
            reasons.append("Unknown recipient or trust domain increases governance uncertainty.")
            factors.append(
                RiskAssessmentFactor(
                    key="recipient:unknown",
                    label="Unknown recipient or trust domain",
                    category="recipient",
                    weight=8.0,
                    explanation="Unknown trust boundaries increase the chance of mis-scoped external execution.",
                )
            )

        if any(item in {"internal_pricing", "confidential", "pii", "financial"} for item in data.data_classifications):
            score += 15
            reasons.append("Sensitive data classifications are present.")
            factors.append(
                RiskAssessmentFactor(
                    key="data:sensitive_classification",
                    label="Sensitive data classification",
                    category="data",
                    weight=15.0,
                    explanation="The request includes internal or regulated data classes.",
                )
            )

        if any(item in {"customer_visible", "external_project"} for item in data.data_classifications):
            score += 10
            reasons.append("Customer-visible or external workflow context increases change-management risk.")
            factors.append(
                RiskAssessmentFactor(
                    key="data:customer_visible",
                    label="Customer-visible workflow",
                    category="data",
                    weight=10.0,
                    explanation="The request targets a customer-visible or external project workflow.",
                )
            )

        if "dangerous_remote_tool_name" in data.data_classifications:
            score += 20
            reasons.append("Remote tool name includes dangerous execution semantics.")
            factors.append(
                RiskAssessmentFactor(
                    key="data:dangerous_remote_tool_name",
                    label="Dangerous remote tool name",
                    category="data",
                    weight=20.0,
                    explanation="The nested remote tool name suggests execution, deletion, transfer, or admin behavior.",
                )
            )

        if any(item in {"remote_tool_side_effect", "blocked_remote_tool_name"} for item in data.data_classifications):
            score += 15
            reasons.append("Remote tool appears to perform side effects and needs stronger change control.")
            factors.append(
                RiskAssessmentFactor(
                    key="data:remote_tool_side_effect",
                    label="Remote tool side effect",
                    category="data",
                    weight=15.0,
                    explanation="The nested remote tool is likely to create, update, send, or execute actions.",
                )
            )

        if "unknown_remote_tool_name" in data.data_classifications:
            score += 10
            reasons.append("Requested remote tool is outside the expected allowlisted semantics.")
            factors.append(
                RiskAssessmentFactor(
                    key="data:unknown_remote_tool_name",
                    label="Unknown remote tool",
                    category="data",
                    weight=10.0,
                    explanation="The nested remote tool name is not recognized within the configured tool scope.",
                )
            )

        if any(item in {"large_request_payload", "large_response_budget"} for item in data.data_classifications):
            score += 10
            reasons.append("Large request or response budgets increase exposure if data handling is wrong.")
            factors.append(
                RiskAssessmentFactor(
                    key="data:large_payload_budget",
                    label="Large request or response budget",
                    category="data",
                    weight=10.0,
                    explanation="Large payloads increase the blast radius for leakage, replay, or operator error.",
                )
            )

        if data.discount_percent and data.discount_percent > 20:
            score += 10
            reasons.append("Large pricing discount requires extra scrutiny.")
            factors.append(
                RiskAssessmentFactor(
                    key="amount:discount_percent",
                    label="High discount percentage",
                    category="amount",
                    weight=10.0,
                    explanation=f"Requested discount {data.discount_percent:.0f}% is above the 20% review threshold.",
                )
            )

        if data.monetary_amount and data.monetary_amount > 1000:
            score += 10
            reasons.append("Large monetary amount crosses an elevated threshold.")
            factors.append(
                RiskAssessmentFactor(
                    key="amount:monetary_amount",
                    label="Large monetary amount",
                    category="amount",
                    weight=10.0,
                    explanation=f"Monetary amount {data.monetary_amount:.2f} is above the elevated threshold.",
                )
            )

        if data.row_count and data.row_count > 1000:
            score += 15
            reasons.append("Large data export volume materially increases data-loss risk.")
            factors.append(
                RiskAssessmentFactor(
                    key="amount:row_count_critical",
                    label="Large export volume",
                    category="amount",
                    weight=15.0,
                    explanation=f"Export volume {data.row_count} rows exceeds the critical volume threshold.",
                )
            )
        elif data.row_count and data.row_count > 100:
            score += 5
            reasons.append("Elevated data volume increases exposure if mishandled.")
            factors.append(
                RiskAssessmentFactor(
                    key="amount:row_count_elevated",
                    label="Elevated export volume",
                    category="amount",
                    weight=5.0,
                    explanation=f"Export volume {data.row_count} rows is materially above a routine read size.",
                )
            )

        if data.irreversible:
            score += 10
            reasons.append("Irreversible action flag is set.")
            factors.append(
                RiskAssessmentFactor(
                    key="action:irreversible",
                    label="Irreversible action",
                    category="action",
                    weight=10.0,
                    explanation="The action is marked irreversible by the caller.",
                )
            )

        if data.intent_mismatch:
            score += 20
            reasons.append("Intent mismatch materially increases risk.")
            factors.append(
                RiskAssessmentFactor(
                    key="intent:mismatch",
                    label="Intent mismatch",
                    category="intent",
                    weight=20.0,
                    explanation="The requested action diverges from the original user intent.",
                )
            )

        if data.max_policy_severity:
            score += POLICY_SEVERITY_WEIGHTS[data.max_policy_severity]
            reasons.append(
                f"Matched policy severity {data.max_policy_severity.value} increases governance risk."
            )
            factors.append(
                RiskAssessmentFactor(
                    key=f"policy:{data.max_policy_severity.value}",
                    label="Matched policy severity",
                    category="policy",
                    weight=float(POLICY_SEVERITY_WEIGHTS[data.max_policy_severity]),
                    explanation=f"A {data.max_policy_severity.value} severity policy matched this request.",
                )
            )

        score = float(min(score, 100))
        band = self._band_for_score(score)
        return RiskAssessmentResult(
            score=score,
            band=band,
            reasons=reasons,
            factors=factors,
            summary=f"Risk is {band.value} at score {score:.0f} based on {len(factors)} contributing factors.",
        )

    def _band_for_score(self, score: float) -> RiskBand:
        if score >= 85:
            return RiskBand.CRITICAL
        if score >= 65:
            return RiskBand.HIGH
        if score >= 35:
            return RiskBand.MEDIUM
        return RiskBand.LOW
