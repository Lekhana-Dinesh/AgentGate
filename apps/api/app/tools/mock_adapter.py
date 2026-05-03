from __future__ import annotations

from datetime import datetime, timezone

from app.core.errors import AppError
from app.tools.base import ToolExecutionAdapter, ToolExecutionRequest


class MockToolAdapter(ToolExecutionAdapter):
    adapter_name = "mock"

    def supports(self, request: ToolExecutionRequest) -> bool:
        if request.tool_type == "mock":
            return True
        return bool((request.config or {}).get("mock"))

    def execute(self, request: ToolExecutionRequest) -> dict:
        normalized_tool = request.tool_name.lower()
        normalized_action = request.action_name.lower()
        arguments = request.arguments

        if normalized_tool == "salesforce" and "read" in normalized_action:
            return {
                "account_id": arguments.get("account_id", "acc_demo_001"),
                "account_name": arguments.get("account_name", "Acme Corp"),
                "renewal_date": "2026-07-31",
                "owner": "sarah@acme.internal",
                "status": "active",
            }

        if normalized_tool == "pricingdb" and "read" in normalized_action:
            return {
                "sku": arguments.get("sku", "renewal-pro"),
                "list_price": 125000,
                "approved_discount_floor": 15,
                "currency": "USD",
            }

        if normalized_tool == "pricingdb" and "discount" in normalized_action:
            discount_percent = float(arguments.get("discount_percent", 0))
            return {
                "sku": arguments.get("sku", "renewal-pro"),
                "discount_percent": discount_percent,
                "status": "simulated",
                "approval_required_above": 20,
            }

        if normalized_tool == "email" and "send" in normalized_action:
            return {
                "message_id": "mock-msg-001",
                "delivery": "suppressed_mock",
                "recipient": arguments.get("recipient"),
                "subject": arguments.get("subject", "Renewal proposal"),
                "queued_at": datetime.now(timezone.utc).isoformat(),
            }

        if normalized_tool == "jira" and "create" in normalized_action:
            return {
                "ticket_key": "AG-101",
                "status": "created",
                "summary": arguments.get("summary", "AgentGate generated ticket"),
            }

        if normalized_tool == "postgres" and ("query" in normalized_action or "export" in normalized_action):
            row_count = int(arguments.get("row_count", 50))
            return {
                "query": arguments.get("query", "SELECT * FROM pricing LIMIT 50"),
                "row_count": row_count,
                "execution_mode": "mock",
                "truncated": row_count > 1000,
            }

        raise AppError(
            f"Mock adapter does not support {request.tool_name}.{request.action_name}.",
            status_code=400,
            code="unsupported_mock_action",
        )
