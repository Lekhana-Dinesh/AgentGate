from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.enums import AuditActorType, ToolCallStatus, ToolType, TraceStatus, UserRole
from app.core.errors import AppError
from app.models import Agent, ApprovalRequest, AuditEvent, Tool, ToolCall, User
from app.schemas.approval import ApprovalDecisionRequest
from app.schemas.audit import AuditEventResponse
from app.schemas.demo import GITHUB_DEMO_SCENARIO, DemoApprovalSummary, DemoEvidenceLinks, GitHubGovernedDemoResponse
from app.schemas.gateway import ToolCallRequest, serialize_tool_call
from app.schemas.policy import PolicySimulationRequest
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.gateway_service import GatewayService
from app.services.payload_service import PayloadService
from app.services.trace_service import TraceService


class DemoService:
    def __init__(self) -> None:
        self.approval_service = ApprovalService()
        self.audit_service = AuditService()
        self.gateway_service = GatewayService()
        self.payload_service = PayloadService()
        self.trace_service = TraceService()

    def run_sales_agent_scenario(self, db: Session, *, principal: Principal) -> dict:
        agent, reviewer = self._get_demo_agent_and_reviewer(db, principal=principal)

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

    def run_github_governed_scenario(
        self,
        db: Session,
        *,
        principal: Principal,
    ) -> GitHubGovernedDemoResponse:
        if not principal.user:
            raise AppError(
                "Interactive demo scenarios require an authenticated user session.",
                status_code=403,
                code="demo_user_required",
            )

        agent, reviewer = self._get_demo_agent_and_reviewer(db, principal=principal)
        original_intent = (
            "A customer-visible GitHub issue needs a safe public acknowledgement after policy review."
        )
        demo_tool = db.scalar(select(Tool).where(Tool.tenant_id == principal.tenant_id, Tool.name == "GitHub"))
        if not demo_tool or demo_tool.type != ToolType.GITHUB or (demo_tool.config or {}).get("demo_safe_mock") is not True:
            raise AppError(
                "The GitHub demo requires the seeded demo-safe connector.",
                status_code=409,
                code="demo_safe_connector_required",
            )
        arguments = {
            "repository": "octocat/hello-world",
            "repository_visibility": "public",
            "number": 14,
            "body": "Thanks for the report. We validated the issue, queued the fix, and will post the rollout window once release checks finish.",
        }
        metadata = {
            "scenario": GITHUB_DEMO_SCENARIO,
            "repository_visibility": "public",
            "trace_finalize": True,
        }

        simulation = self.gateway_service.simulate_policy_decision(
            db,
            current_user=principal.user,
            payload=PolicySimulationRequest(
                agent_id=agent.id,
                original_intent=original_intent,
                tool_name="GitHub",
                action_name="comment_on_issue_or_pr",
                arguments=arguments,
                data_classifications=["customer_visible"],
                metadata=metadata,
                dry_run=True,
            ),
        )

        governed_attempt = self.gateway_service.process_tool_call(
            db,
            principal=Principal(
                tenant_id=principal.tenant_id,
                actor_type=AuditActorType.USER,
                actor_id=principal.actor_id,
                role=principal.role or UserRole.ADMIN,
                user=principal.user,
            ),
            payload=ToolCallRequest(
                agent_id=agent.id,
                user_id=principal.actor_id,
                original_intent=original_intent,
                tool_name="GitHub",
                action_name="comment_on_issue_or_pr",
                arguments=arguments,
                data_classifications=["customer_visible"],
                metadata=metadata,
            ),
        )
        if governed_attempt.status.value != "pending_approval":
            raise AppError(
                "GitHub demo scenario expected an approval-required decision.",
                status_code=500,
                code="demo_expected_approval_required",
            )

        tool_call = db.scalar(
            select(ToolCall).where(
                ToolCall.id == governed_attempt.tool_call_id,
                ToolCall.tenant_id == principal.tenant_id,
            )
        )
        if not tool_call:
            raise AppError("GitHub demo tool call was not found.", status_code=500, code="demo_tool_call_missing")

        approval = db.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.tool_call_id == tool_call.id,
                ApprovalRequest.tenant_id == principal.tenant_id,
            )
        )
        if not approval:
            raise AppError("GitHub demo approval was not created.", status_code=500, code="demo_approval_missing")

        approval = self.approval_service.decide(
            db,
            approval_id=approval.id,
            tenant_id=principal.tenant_id,
            approver=reviewer,
            approve=True,
            payload=ApprovalDecisionRequest(
                approver_comment="Seeded reviewer approved the public GitHub comment after policy review.",
                execute_now=True,
            ),
        )

        tool_call = db.scalar(
            select(ToolCall).where(
                ToolCall.id == tool_call.id,
                ToolCall.tenant_id == principal.tenant_id,
            )
        )
        if not tool_call:
            raise AppError("GitHub demo tool call was not found.", status_code=500, code="demo_tool_call_missing")

        db.refresh(tool_call)
        trace = self.trace_service.get_trace(db, trace_id=governed_attempt.trace_id, tenant_id=principal.tenant_id)
        self.audit_service.create_event(
            db,
            tenant_id=principal.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=principal.actor_id,
            event_type="demo.scenario.submitted" if trace.status == TraceStatus.RUNNING else "demo.scenario.completed",
            resource_type="execution_trace",
            resource_id=trace.id,
            metadata={
                "scenario": GITHUB_DEMO_SCENARIO,
                "final_status": trace.status.value,
                "tool_call_id": tool_call.id,
                "approval_id": approval.id,
            },
        )
        db.commit()

        trace = self.trace_service.get_trace(db, trace_id=trace.id, tenant_id=principal.tenant_id)
        tool_output = (tool_call.response_payload or {}).get("tool_output") or {}
        execution_mode = (
            "demo_safe_mock"
            if tool_output.get("execution_mode") == "demo_safe_mock"
            else "queued"
            if tool_call.status == ToolCallStatus.ALLOWED
            else "unsupported"
        )

        audit_events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == principal.tenant_id,
                    or_(
                        (AuditEvent.resource_type == "execution_trace") & (AuditEvent.resource_id == trace.id),
                        (AuditEvent.resource_type == "tool_call") & (AuditEvent.resource_id == tool_call.id),
                        (AuditEvent.resource_type == "approval_request") & (AuditEvent.resource_id == approval.id),
                    ),
                )
                .order_by(AuditEvent.created_at.asc())
            )
        )

        return GitHubGovernedDemoResponse(
            scenario="github_governed_workflow",
            trace_id=trace.id,
            trace_status=trace.status,
            trace_summary=trace.summary,
            simulation=simulation,
            governed_attempt=governed_attempt,
            approval=DemoApprovalSummary(
                approval_id=approval.id,
                status=approval.status,
                reviewer_email=reviewer.email,
                approver_comment=approval.approver_comment,
                execute_now=True,
                decided_at=approval.decided_at,
            ),
            tool_call=serialize_tool_call(tool_call),
            audit_events=[self._serialize_audit_event(item) for item in audit_events],
            execution_mode=execution_mode,
            no_live_external_call=True,
            evidence_links=DemoEvidenceLinks(
                trace_path=f"/traces/{trace.id}",
                approvals_path="/approvals?status=approved",
                tool_calls_path="/tool-calls",
                audit_path="/audit",
            ),
        )

    def _get_demo_agent_and_reviewer(self, db: Session, *, principal: Principal) -> tuple[Agent, User]:
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
        return agent, reviewer

    def _serialize_audit_event(self, audit_event: AuditEvent) -> AuditEventResponse:
        return AuditEventResponse(
            id=audit_event.id,
            tenant_id=audit_event.tenant_id,
            actor_type=audit_event.actor_type,
            actor_id=audit_event.actor_id,
            event_type=audit_event.event_type,
            resource_type=audit_event.resource_type,
            resource_id=audit_event.resource_id,
            metadata_json=self.payload_service.sanitize_payload(audit_event.metadata_json),
            ip_address=audit_event.ip_address,
            event_hash=audit_event.event_hash,
            previous_event_hash=audit_event.previous_event_hash,
            hash_algorithm=audit_event.hash_algorithm,
            chain_scope=audit_event.chain_scope,
            sequence_number=audit_event.sequence_number,
            anchored_at=audit_event.anchored_at,
            created_at=audit_event.created_at,
        )
