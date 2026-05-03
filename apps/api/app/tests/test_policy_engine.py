from __future__ import annotations

from app.core.enums import PolicyDecision, PolicySeverity
from app.models import Policy
from app.services.policy_engine import PolicyContext, PolicyEngine


def test_policy_engine_prefers_block_over_lower_priority_decisions():
    policies = [
        Policy(
            id="p1",
            tenant_id="t1",
            name="Allow Salesforce Reads",
            description="",
            enabled=True,
            severity=PolicySeverity.LOW,
            conditions={"match": "all", "rules": [{"field": "tool_name", "operator": "equals", "value": "Postgres"}]},
            decision=PolicyDecision.ALLOW,
            created_by=None,
        ),
        Policy(
            id="p2",
            tenant_id="t1",
            name="Block Large Export",
            description="",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "Postgres"},
                    {"field": "row_count", "operator": "greater_than", "value": 1000},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=None,
        ),
    ]

    result = PolicyEngine().evaluate(
        policies,
        PolicyContext(
            tool_name="Postgres",
            action_name="export_rows",
            recipient_domain="internal",
            data_classifications=["customer_data"],
            risk_score=92,
            environment="production",
            amount=10000,
            discount_percent=None,
            row_count=10000,
            intent_mismatch=False,
        ),
    )

    assert result.decision == PolicyDecision.BLOCK
    assert len(result.matched_policies) == 2


def test_policy_engine_fails_closed_on_malformed_policy_under_high_risk():
    policies = [
        Policy(
            id="p1",
            tenant_id="t1",
            name="Malformed",
            description="",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={"broken": True},
            decision=PolicyDecision.ALLOW,
            created_by=None,
        )
    ]

    result = PolicyEngine().evaluate(
        policies,
        PolicyContext(
            tool_name="Email",
            action_name="send_external_email",
            recipient_domain="external",
            data_classifications=["confidential"],
            risk_score=90,
            environment="production",
            amount=None,
            discount_percent=None,
            row_count=None,
            intent_mismatch=True,
        ),
    )

    assert result.decision == PolicyDecision.BLOCK


def test_policy_engine_matches_case_insensitively_for_text_fields():
    policies = [
        Policy(
            id="p3",
            tenant_id="t1",
            name="Email externalization",
            description="",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "email"},
                    {"field": "action_name", "operator": "contains", "value": "external"},
                    {"field": "data_classification", "operator": "contains", "value": "Internal_Pricing"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=None,
        )
    ]

    result = PolicyEngine().evaluate(
        policies,
        PolicyContext(
            tool_name="Email",
            action_name="send_external_email",
            recipient_domain="external",
            data_classifications=["internal_pricing"],
            risk_score=76,
            environment="production",
            amount=None,
            discount_percent=None,
            row_count=None,
            intent_mismatch=False,
        ),
    )

    assert result.decision == PolicyDecision.REQUIRE_APPROVAL
