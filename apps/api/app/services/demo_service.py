from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.enums import AuditActorType, UserRole
from app.core.errors import AppError
from app.models import Agent, ApprovalRequest, User
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.gateway import ToolCallRequest
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.gateway_service import GatewayService
from app.services.trace_service import TraceService


class DemoService:
    def __init__(self) -> None:
        self.approval_service = ApprovalService()
        self.audit_service = AuditService()
        self.gateway_service = GatewayService()
        self.trace_service = TraceService()

    def run_sales_agent_scenario(self, db: Session, *, principal: Principal) -> dict:
        agent = db.scalar(
            select(Agent).where(
                Agent.tenant_id == principal.tenant_id,
                Agent.name == "SalesProposalAgent",
            )
        )
        if not agent:
            raise AppError("Demo agent SalesProposalAgent was not found.", status_code=404, code="demo_agent_missing")
        reviewer = db.scalar(
            select(User).where(
                User.tenant_id == principal.tenant_id,
                User.role == UserRole.SECURITY_REVIEWER,
                User.is_active.is_(True),
            )
        )
        if not reviewer:
            raise AppError(
                "Demo security reviewer account is missing.",
                status_code=500,
                code="demo_reviewer_missing",
            )

        original_intent = "Prepare and send a renewal proposal to Acme Corp."
        trace = self.trace_service.create_trace(
            db,
            tenant_id=principal.tenant_id,
            agent_id=agent.id,
            user_id=principal.actor_id,
            original_intent=original_intent,
            metadata={"scenario": "sales_agent_risk"},
        )
        self.audit_service.create_event(
            db,
            tenant_id=principal.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=principal.actor_id,
            event_type="demo.scenario.started",
            resource_type="execution_trace",
            resource_id=trace.id,
            metadata={"scenario": "sales_agent_risk", "agent_id": agent.id},
        )
        scenario_principal = Principal(
            tenant_id=principal.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=principal.actor_id,
            role=principal.role or UserRole.ADMIN,
            user=principal.user,
        )

        steps = [
            ToolCallRequest(
                agent_id=agent.id,
                user_id=principal.actor_id,
                trace_id=trace.id,
                original_intent=original_intent,
                tool_name="Salesforce",
                action_name="read_account",
                arguments={"account_id": "acc_acme_001", "account_name": "Acme Corp"},
                data_classifications=["customer_data"],
                metadata={"scenario_step": 1},
            ),
            ToolCallRequest(
                agent_id=agent.id,
                user_id=principal.actor_id,
                trace_id=trace.id,
                original_intent=original_intent,
                tool_name="PricingDB",
                action_name="read_pricing",
                arguments={"sku": "renewal-pro"},
                data_classifications=["internal_pricing"],
                metadata={"scenario_step": 2},
            ),
            ToolCallRequest(
                agent_id=agent.id,
                user_id=principal.actor_id,
                trace_id=trace.id,
                original_intent=original_intent,
                tool_name="PricingDB",
                action_name="apply_discount",
                arguments={"discount_percent": 30, "sku": "renewal-pro"},
                data_classifications=["internal_pricing", "financial"],
                metadata={"scenario_step": 3},
            ),
            ToolCallRequest(
                agent_id=agent.id,
                user_id=principal.actor_id,
                trace_id=trace.id,
                original_intent=original_intent,
                tool_name="Email",
                action_name="send_external_email",
                arguments={
                    "recipient": "buyer@acme.com",
                    "subject": "Renewal proposal",
                    "body": "Attached is the proposed pricing package.",
                    "attachment": "internal_pricing_sheet.xlsx",
                },
                data_classifications=["internal_pricing", "customer_data"],
                metadata={"scenario_step": 4, "trace_finalize": True},
            ),
        ]

        results = []
        approval_actions = []
        for request in steps:
            decision = self.gateway_service.process_tool_call(
                db,
                principal=scenario_principal,
                payload=request,
            )
            results.append(decision.model_dump())

            if request.action_name == "apply_discount" and decision.status.value == "pending_approval":
                approval = db.scalar(
                    select(ApprovalRequest).where(
                        ApprovalRequest.tool_call_id == decision.tool_call_id,
                        ApprovalRequest.tenant_id == principal.tenant_id,
                    )
                )
                if not approval:
                    raise AppError(
                        "Discount approval was expected but not created.",
                        status_code=500,
                        code="demo_approval_missing",
                    )
                approval = self.approval_service.decide(
                    db,
                    approval_id=approval.id,
                    tenant_id=principal.tenant_id,
                    approver=reviewer,
                    approve=True,
                    payload=ApprovalDecisionRequest(
                        approver_comment="Demo reviewer approved discount to continue the scenario.",
                        execute_now=True,
                    ),
                )
                approval_actions.append(
                    {
                        "approval_id": approval.id,
                        "tool_call_id": decision.tool_call_id,
                        "status": approval.status.value,
                        "action_name": request.action_name,
                    }
                )
                continue

            if decision.status.value in {"blocked", "pending_approval", "failed"}:
                break

        trace = self.trace_service.get_trace(db, trace_id=trace.id, tenant_id=principal.tenant_id)
        self.audit_service.create_event(
            db,
            tenant_id=principal.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=principal.actor_id,
            event_type="demo.scenario.completed",
            resource_type="execution_trace",
            resource_id=trace.id,
            metadata={
                "scenario": "sales_agent_risk",
                "final_status": trace.status.value,
                "approval_actions": len(approval_actions),
            },
        )
        db.commit()

        return {
            "trace_id": trace.id,
            "trace_status": trace.status.value,
            "results": results,
            "approval_actions": approval_actions,
        }
