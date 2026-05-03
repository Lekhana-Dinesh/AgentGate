from __future__ import annotations

from app.core.enums import PolicySeverity, RiskBand
from app.services.risk_service import RiskInput, RiskService


def test_risk_scoring_marks_high_risk_external_sensitive_export_as_critical():
    result = RiskService().assess(
        RiskInput(
            tool_risk=RiskBand.CRITICAL,
            action_name="export_rows",
            data_classifications=["confidential", "financial"],
            recipient_domain="external",
            environment="production",
            amount=10000,
            irreversible=True,
            intent_mismatch=True,
            max_policy_severity=PolicySeverity.CRITICAL,
        )
    )

    assert result.band == RiskBand.CRITICAL
    assert result.score >= 85
    assert result.summary.startswith("Risk is critical")
    assert any(factor.key == "intent:mismatch" for factor in result.factors)


def test_risk_scoring_keeps_basic_read_low_or_medium():
    result = RiskService().assess(
        RiskInput(
            tool_risk=RiskBand.LOW,
            action_name="read_account",
            data_classifications=["customer_data"],
            recipient_domain="internal",
            environment="development",
            amount=None,
            irreversible=False,
            intent_mismatch=False,
        )
    )

    assert result.band in {RiskBand.LOW, RiskBand.MEDIUM}
    assert result.factors[0].key.startswith("tool_risk:")
