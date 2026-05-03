from __future__ import annotations

from app.services.intent_service import IntentContext, IntentService


def test_intent_service_accepts_safe_read_for_renewal_prep():
    result = IntentService().evaluate(
        IntentContext(
            original_intent="Prepare and send a renewal proposal to Acme Corp.",
            tool_name="Salesforce",
            action_name="read_account",
            arguments={"account_id": "acc_001"},
            data_classifications=["customer_data"],
        )
    )

    assert result.intent_match is True


def test_intent_service_flags_external_sensitive_send():
    result = IntentService().evaluate(
        IntentContext(
            original_intent="Prepare a renewal proposal.",
            tool_name="Email",
            action_name="send_external_email",
            arguments={"recipient": "buyer@acme.com", "attachment": "pricing.xlsx"},
            data_classifications=["internal_pricing"],
        )
    )

    assert result.intent_match is False
    assert result.detected_mismatch_reasons

