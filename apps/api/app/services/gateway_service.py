from __future__ import annotations

from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal
from app.core.enums import (
    AgentStatus,
    ApprovalStatus,
    AuditActorType,
    PolicyDecision,
    PolicySeverity,
    RiskBand,
    ToolCallStatus,
    ToolType,
    TraceStatus,
    TraceStepType,
    UserRole,
)
from app.core.errors import AppError
from app.core.metrics import get_metrics_registry
from app.models import Agent, ApprovalRequest, Policy, Tool, ToolCall, User
from app.schemas.gateway import GatewayDecisionResponse, PolicyEvaluationResult, ToolCallRequest
from app.services.audit_service import AuditService
from app.services.intent_service import IntentContext, IntentService
from app.services.notification_service import NotificationService
from app.services.payload_service import PayloadProtectionContext, PayloadService
from app.services.policy_engine import PolicyContext, PolicyEngine
from app.services.risk_service import RiskInput, RiskService
from app.services.tool_executor import ToolExecutor
from app.services.trace_service import TraceService


class GatewayService:
    def __init__(self) -> None:
        self.intent_service = IntentService()
        self.risk_service = RiskService()
        self.policy_engine = PolicyEngine()
        self.audit_service = AuditService()
        self.notification_service = NotificationService()
        self.payload_service = PayloadService()
        self.trace_service = TraceService()
        self.tool_executor = ToolExecutor()
        self.metrics = get_metrics_registry()

    def process_tool_call(
        self,
        db: Session,
        *,
        principal: Principal,
        payload: ToolCallRequest,
        ip_address: str | None = None,
        request_id: str | None = None,
    ) -> GatewayDecisionResponse:
        tenant_id = principal.tenant_id
        agent = self._get_agent(db, tenant_id=tenant_id, agent_id=payload.agent_id)
        tool = self._get_tool(db, tenant_id=tenant_id, tool_name=payload.tool_name)
        user_id = self._resolve_user_id(db, tenant_id=tenant_id, principal=principal, payload=payload)

        if principal.api_key and principal.agent_id != agent.id:
            self._audit_preflight_denial(
                db,
                principal=principal,
                tenant_id=tenant_id,
                event_type="gateway.tool_call.denied_preflight",
                resource_type="agent",
                resource_id=agent.id,
                metadata={"reason": "agent_key_mismatch", "requested_agent_id": payload.agent_id},
                ip_address=ip_address,
            )
            raise AppError("API key is not valid for this agent.", status_code=403, code="agent_key_mismatch")
        if agent.status != AgentStatus.ACTIVE:
            self._audit_preflight_denial(
                db,
                principal=principal,
                tenant_id=tenant_id,
                event_type="gateway.tool_call.denied_preflight",
                resource_type="agent",
                resource_id=agent.id,
                metadata={"reason": "agent_inactive", "agent_status": agent.status.value},
                ip_address=ip_address,
            )
            raise AppError("Agent is not active.", status_code=403, code="agent_inactive")
        if not tool.enabled:
            self._audit_preflight_denial(
                db,
                principal=principal,
                tenant_id=tenant_id,
                event_type="gateway.tool_call.denied_preflight",
                resource_type="tool",
                resource_id=tool.id,
                metadata={"reason": "tool_disabled", "tool_name": tool.name},
                ip_address=ip_address,
            )
            raise AppError("Tool is disabled.", status_code=403, code="tool_disabled")
        if agent.allowed_tools and tool.name not in agent.allowed_tools:
            self._audit_preflight_denial(
                db,
                principal=principal,
                tenant_id=tenant_id,
                event_type="gateway.tool_call.denied_preflight",
                resource_type="tool",
                resource_id=tool.id,
                metadata={"reason": "tool_not_allowed", "tool_name": tool.name, "agent_id": agent.id},
                ip_address=ip_address,
            )
            raise AppError("Agent is not allowed to use this tool.", status_code=403, code="tool_not_allowed")
        if agent.allowed_data_classes:
            invalid_data_classes = sorted(set(payload.data_classifications) - set(agent.allowed_data_classes))
            if invalid_data_classes:
                self._audit_preflight_denial(
                    db,
                    principal=principal,
                    tenant_id=tenant_id,
                    event_type="gateway.tool_call.denied_preflight",
                    resource_type="agent",
                    resource_id=agent.id,
                    metadata={
                        "reason": "data_class_not_allowed",
                        "data_classes": invalid_data_classes,
                        "tool_name": tool.name,
                    },
                    ip_address=ip_address,
                )
                raise AppError(
                    "Agent requested data classes that are not allowed.",
                    status_code=403,
                    code="data_class_not_allowed",
                    extra={"data_classes": invalid_data_classes},
                )

        trace = self.trace_service.ensure_trace(
            db,
            trace_id=payload.trace_id,
            tenant_id=tenant_id,
            agent_id=agent.id,
            user_id=user_id,
            original_intent=payload.original_intent,
            metadata=payload.metadata,
        )
        self.trace_service.append_step(
            db,
            trace_id=trace.id,
            type=TraceStepType.THOUGHT,
            content=f"Intent received: {payload.original_intent}",
            metadata={"tool_name": payload.tool_name, "action_name": payload.action_name},
        )

        repo_trust = self._resolve_repository_trust(tool, payload.arguments, payload.metadata)
        recipient_domain = self._resolve_recipient_domain(
            tool,
            payload.action_name,
            payload.arguments,
            payload.metadata,
            repo_trust=repo_trust,
        )
        effective_data_classifications = self._augment_data_classifications(
            tool,
            payload.action_name,
            payload.arguments,
            payload.data_classifications,
            repo_trust,
        )
        connector_context = self._build_connector_context(
            tool,
            payload.arguments,
            payload.metadata,
            repo_trust,
            recipient_domain,
        )
        amount = self._extract_amount(payload.arguments)
        discount_percent = self._extract_numeric_argument(payload.arguments, "discount_percent")
        monetary_amount = self._extract_numeric_argument(payload.arguments, "amount", "refund_amount")
        row_count = self._extract_integer_argument(payload.arguments, "row_count")
        irreversible = bool(payload.arguments.get("irreversible", False))

        intent_result = self.intent_service.evaluate(
            IntentContext(
                original_intent=payload.original_intent,
                tool_name=payload.tool_name,
                action_name=payload.action_name,
                arguments=payload.arguments,
                data_classifications=effective_data_classifications,
            )
        )
        self.trace_service.append_step(
            db,
            trace_id=trace.id,
            type=TraceStepType.THOUGHT,
            content=intent_result.explanation,
            metadata=intent_result.model_dump(),
        )

        risk_input = RiskInput(
            tool_risk=tool.risk_level,
            action_name=payload.action_name,
            data_classifications=effective_data_classifications,
            recipient_domain=recipient_domain,
            environment=agent.environment.value,
            amount=amount,
            discount_percent=discount_percent,
            monetary_amount=monetary_amount,
            row_count=row_count,
            irreversible=irreversible,
            intent_mismatch=not intent_result.intent_match,
        )
        preliminary_risk = self.risk_service.assess(risk_input)

        policy_context = PolicyContext(
            tool_name=payload.tool_name,
            action_name=payload.action_name,
            recipient_domain=recipient_domain,
            repo_trust=repo_trust,
            data_classifications=effective_data_classifications,
            risk_score=preliminary_risk.score,
            environment=agent.environment.value,
            amount=amount,
            discount_percent=discount_percent,
            row_count=row_count,
            intent_mismatch=not intent_result.intent_match,
        )
        policies = list(
            db.scalars(
                select(Policy).where(
                    Policy.tenant_id == tenant_id,
                    Policy.enabled.is_(True),
                )
            )
        )
        policy_result = self.policy_engine.evaluate(policies, policy_context)
        max_policy_severity = self._max_policy_severity(policies, policy_result)
        final_risk = self.risk_service.assess(
            replace(risk_input, max_policy_severity=max_policy_severity)
        )
        self.trace_service.append_step(
            db,
            trace_id=trace.id,
            type=TraceStepType.POLICY_DECISION,
            content=f"Risk score {final_risk.score} ({final_risk.band.value}).",
            metadata=final_risk.model_dump(),
        )

        decision_result = self._apply_guardrails(
            payload=payload,
            recipient_domain=recipient_domain,
            risk_band=final_risk.band,
            intent_match=intent_result.intent_match,
            policy_result=policy_result,
        )
        self.trace_service.append_step(
            db,
            trace_id=trace.id,
            type=TraceStepType.POLICY_DECISION,
            content=f"Decision: {decision_result.decision.value}",
            metadata=decision_result.model_dump(),
        )

        protection_bundle = self.payload_service.protect_payload(
            payload.arguments,
            context=PayloadProtectionContext(
                tool_name=payload.tool_name,
                action_name=payload.action_name,
                data_classifications=effective_data_classifications,
            ),
        )
        sanitized_arguments = protection_bundle.sanitized_payload
        execution_arguments = payload.arguments
        executed = False
        tool_output: dict | None = None
        created_approval: ApprovalRequest | None = None
        response_payload = {
            "trace_id": trace.id,
            "connector_context": connector_context,
            "intent": intent_result.model_dump(),
            "risk": final_risk.model_dump(),
            "policies": decision_result.model_dump(),
        }

        if decision_result.decision == PolicyDecision.REDACT:
            execution_arguments = self.payload_service.sanitize_payload(payload.arguments)
            response_payload["redacted_arguments"] = execution_arguments

        status = self._tool_call_status_for_decision(decision_result.decision)
        decision_reason = "; ".join(decision_result.reasons or final_risk.reasons[:3])
        stored_request_payload = {
            "trace_id": trace.id,
            "tool_type": tool.type.value,
            "original_intent": payload.original_intent,
            "arguments": sanitized_arguments,
            "execution_arguments": protection_bundle.protected_payload,
            "arguments_redacted": sanitized_arguments,
            "requested_data_classifications": payload.data_classifications,
            "data_classifications": effective_data_classifications,
            "metadata": self.payload_service.sanitize_payload(payload.metadata),
            "connector_context": connector_context,
            "delegated_user_id": payload.delegated_user_id,
        }

        tool_call = ToolCall(
            tenant_id=tenant_id,
            agent_id=agent.id,
            user_id=user_id,
            trace_id=trace.id,
            tool_name=tool.name,
            action_name=payload.action_name,
            request_payload=stored_request_payload,
            response_payload=response_payload,
            payload_protection_version=protection_bundle.protection_version,
            payload_retention_class=protection_bundle.retention_class,
            payload_expires_at=protection_bundle.expires_at,
            payload_redaction_status=protection_bundle.redaction_status,
            status=status,
            risk_score=final_risk.score,
            decision_reason=decision_reason,
        )
        db.add(tool_call)
        db.flush()

        if decision_result.decision == PolicyDecision.REQUIRE_APPROVAL:
            created_approval = ApprovalRequest(
                tenant_id=tenant_id,
                tool_call_id=tool_call.id,
                requested_by_agent_id=agent.id,
                status=ApprovalStatus.PENDING,
                reason=decision_reason,
            )
            db.add(created_approval)
            db.flush()
            tool_call.response_payload = {
                **response_payload,
                "approval_request_id": created_approval.id,
            }
            self.trace_service.append_step(
                db,
                trace_id=trace.id,
                type=TraceStepType.APPROVAL,
                content="Approval required before tool execution.",
                metadata={"tool_call_id": tool_call.id},
            )
            self.trace_service.set_status(
                db,
                trace_id=trace.id,
                status=TraceStatus.PENDING_APPROVAL,
                summary="Execution paused pending approval.",
            )
            self.trace_service.append_step(
                db,
                trace_id=trace.id,
                type=TraceStepType.FINAL,
                content="Execution paused until a reviewer approves the request.",
                metadata={"approval_request_id": created_approval.id},
            )
            self.audit_service.create_event(
                db,
                tenant_id=tenant_id,
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                event_type="approval_request.created",
                resource_type="approval_request",
                resource_id=created_approval.id,
                metadata={"tool_call_id": tool_call.id, "trace_id": trace.id},
                ip_address=ip_address,
            )
            self.metrics.increment("agentgate_approvals_total", status="created")
        elif decision_result.decision in {PolicyDecision.ALLOW, PolicyDecision.REDACT} and self.tool_executor.supports(
            tool.name,
            payload.action_name,
            execution_arguments,
            tool_type=tool.type.value,
            base_url=tool.base_url,
            config=tool.config or {},
        ):
            try:
                tool_output = self.tool_executor.execute(
                    tool.name,
                    payload.action_name,
                    execution_arguments,
                    tool_type=tool.type.value,
                    base_url=tool.base_url,
                    config=tool.config or {},
                )
                sanitized_output = self.payload_service.sanitize_payload(tool_output)
                executed = True
                tool_call.status = ToolCallStatus.EXECUTED
                tool_call.response_payload = {**response_payload, "tool_output": sanitized_output}
                self.trace_service.append_step(
                    db,
                    trace_id=trace.id,
                    type=TraceStepType.TOOL_CALL,
                    content=f"Executed {tool.type.value} tool {tool.name}.{payload.action_name}.",
                    metadata={"tool_output": sanitized_output},
                )
                self._update_trace_after_success(
                    db,
                    trace_id=trace.id,
                    tool_call_id=tool_call.id,
                    tool_name=tool.name,
                    action_name=payload.action_name,
                    finalize=bool(payload.metadata.get("trace_finalize")),
                    executed=True,
                )
            except Exception as exc:  # pragma: no cover - covered by behavior tests
                self._record_execution_failure(
                    db,
                    principal=principal,
                    tenant_id=tenant_id,
                    tool_call=tool_call,
                    trace_id=trace.id,
                    tool_name=tool.name,
                    action_name=payload.action_name,
                    ip_address=ip_address,
                )
                if isinstance(exc, AppError):
                    raise
                raise AppError(
                    "Tool execution failed unexpectedly.",
                    status_code=500,
                    code="tool_execution_failed",
                ) from exc
        elif decision_result.decision in {PolicyDecision.ALLOW, PolicyDecision.REDACT}:
            self.trace_service.append_step(
                db,
                trace_id=trace.id,
                type=TraceStepType.TOOL_CALL,
                content=(
                    f"Authorized {tool.name}.{payload.action_name}. Execution was not performed because "
                    "no registered adapter supports this tool in the current build."
                ),
                metadata={"tool_call_id": tool_call.id, "tool_name": tool.name},
            )
            self._update_trace_after_success(
                db,
                trace_id=trace.id,
                tool_call_id=tool_call.id,
                tool_name=tool.name,
                action_name=payload.action_name,
                finalize=bool(payload.metadata.get("trace_finalize")),
                executed=False,
            )
        elif decision_result.decision == PolicyDecision.BLOCK:
            self.trace_service.set_status(
                db,
                trace_id=trace.id,
                status=TraceStatus.BLOCKED,
                summary="Execution blocked by policy.",
                completed=True,
            )
            self.trace_service.append_step(
                db,
                trace_id=trace.id,
                type=TraceStepType.FINAL,
                content="Execution blocked before tool dispatch.",
                metadata={"tool_call_id": tool_call.id},
            )

        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=principal.actor_type,
            actor_id=principal.actor_id,
            event_type=f"gateway.tool_call.{decision_result.decision.value}",
            resource_type="tool_call",
            resource_id=tool_call.id,
            metadata={
                "agent_id": agent.id,
                "tool_name": tool.name,
                "action_name": payload.action_name,
                "trace_id": trace.id,
                "risk_score": final_risk.score,
                "decision": decision_result.decision.value,
                "repo_trust": repo_trust,
            },
            ip_address=ip_address,
        )
        self.metrics.increment(
            "agentgate_gateway_decisions_total",
            decision=decision_result.decision.value,
            status=tool_call.status.value,
        )
        db.commit()
        if created_approval is not None:
            self.notification_service.notify_approval_request_created(
                db,
                approval=created_approval,
                tool_call=tool_call,
                agent=agent,
                request_id=request_id,
                ip_address=ip_address,
            )

        return GatewayDecisionResponse(
            tool_call_id=tool_call.id,
            trace_id=trace.id,
            decision=decision_result.decision,
            status=tool_call.status,
            intent=intent_result,
            risk=final_risk,
            policies=decision_result,
            executed=executed,
            output=self.payload_service.sanitize_payload(tool_output) if tool_output else None,
        )

    def _get_agent(self, db: Session, *, tenant_id: str, agent_id: str) -> Agent:
        agent = db.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
        if not agent:
            raise AppError("Agent not found.", status_code=404, code="agent_not_found")
        return agent

    def _get_tool(self, db: Session, *, tenant_id: str, tool_name: str) -> Tool:
        tool = db.scalar(select(Tool).where(Tool.tenant_id == tenant_id, Tool.name == tool_name))
        if not tool:
            raise AppError("Tool not found.", status_code=404, code="tool_not_found")
        return tool

    def _resolve_user_id(
        self,
        db: Session,
        *,
        tenant_id: str,
        principal: Principal,
        payload: ToolCallRequest,
    ) -> str | None:
        if payload.user_id and payload.delegated_user_id and payload.user_id != payload.delegated_user_id:
            raise AppError(
                "user_id and delegated_user_id must not conflict.",
                status_code=422,
                code="conflicting_user_context",
            )

        if principal.api_key and not (payload.delegated_user_id or payload.user_id):
            return None

        candidate_id = payload.delegated_user_id or payload.user_id or principal.actor_id
        if not candidate_id:
            return None

        if principal.user:
            requested_user_id = payload.delegated_user_id or payload.user_id or principal.user.id
            if requested_user_id != principal.user.id and principal.user.role not in {
                UserRole.OWNER,
                UserRole.ADMIN,
            }:
                raise AppError(
                    "Only owners and admins can delegate gateway execution to another user.",
                    status_code=403,
                    code="delegation_forbidden",
                )

        user = db.scalar(select(User).where(User.id == candidate_id, User.tenant_id == tenant_id))
        if not user:
            raise AppError("Delegated user not found in tenant.", status_code=404, code="user_not_found")
        if not user.is_active:
            raise AppError("Delegated user is inactive.", status_code=403, code="inactive_user")
        return user.id

    def _resolve_recipient_domain(
        self,
        tool: Tool,
        action_name: str,
        arguments: dict,
        metadata: dict,
        repo_trust: str,
    ) -> str:
        recipient = str(arguments.get("recipient") or arguments.get("email_to") or "")
        if "@" not in recipient:
            if tool.type == ToolType.GITHUB:
                return "internal" if repo_trust == "internal" else "external"
            return "internal"
        domain = recipient.split("@")[-1].lower()
        internal_domains = {
            value.lower()
            for value in metadata.get("internal_domains", ["agentgate.local", "acme.internal"])
        }
        return "internal" if domain in internal_domains else "external"

    def _resolve_repository_trust(
        self,
        tool: Tool,
        arguments: dict,
        metadata: dict,
    ) -> str:
        if tool.type != ToolType.GITHUB:
            return "unknown"

        repository = str(arguments.get("repository") or "").strip().lower()
        if not repository:
            owner = str(arguments.get("owner") or "").strip().lower()
            repo = str(arguments.get("repo") or "").strip().lower()
            repository = f"{owner}/{repo}" if owner and repo else ""
        if not repository:
            return "unknown"

        visibility = str(
            arguments.get("repository_visibility")
            or arguments.get("visibility")
            or metadata.get("repository_visibility")
            or ""
        ).strip().lower()
        internal_repositories = {
            str(item).strip().lower()
            for item in ((tool.config or {}).get("internal_repositories") or [])
            if str(item).strip()
        }
        internal_owners = {
            str(item).strip().lower()
            for item in ((tool.config or {}).get("internal_owners") or metadata.get("internal_github_owners") or [])
            if str(item).strip()
        }
        public_repositories = {
            str(item).strip().lower()
            for item in ((tool.config or {}).get("public_repositories") or metadata.get("public_repositories") or [])
            if str(item).strip()
        }
        owner = repository.split("/", 1)[0]

        if visibility == "public" or repository in public_repositories:
            return "public"
        if repository in internal_repositories:
            return "internal"
        if internal_owners and owner in internal_owners:
            return "internal"
        if internal_owners and owner not in internal_owners:
            return "external"
        if visibility == "private":
            return "external"
        return "unknown"

    def _augment_data_classifications(
        self,
        tool: Tool,
        action_name: str,
        arguments: dict,
        data_classifications: list[str],
        repo_trust: str,
    ) -> list[str]:
        augmented = list(dict.fromkeys(data_classifications))
        if tool.type != ToolType.GITHUB:
            return augmented

        trust_tags = {
            "public": "public_repository",
            "external": "external_repository",
            "unknown": "unknown_repository_trust",
        }
        trust_tag = trust_tags.get(repo_trust)
        if trust_tag and trust_tag not in augmented:
            augmented.append(trust_tag)

        action_lower = action_name.lower()
        if "comment" in action_lower and str(arguments.get("body", "")).strip():
            for tag in ("github_comment_body", "public_comment_body" if repo_trust == "public" else None):
                if tag and tag not in augmented:
                    augmented.append(tag)
        if "issue" in action_lower and str(arguments.get("body", "")).strip():
            for tag in ("github_issue_body", "public_issue_body" if repo_trust == "public" else None):
                if tag and tag not in augmented:
                    augmented.append(tag)
        return augmented

    def _build_connector_context(
        self,
        tool: Tool,
        arguments: dict,
        metadata: dict,
        repo_trust: str,
        recipient_domain: str,
    ) -> dict:
        if tool.type != ToolType.GITHUB:
            return {}

        repository = str(arguments.get("repository") or "").strip()
        if not repository and arguments.get("owner") and arguments.get("repo"):
            repository = f"{arguments['owner']}/{arguments['repo']}"
        visibility = str(
            arguments.get("repository_visibility")
            or arguments.get("visibility")
            or metadata.get("repository_visibility")
            or "unknown"
        ).strip().lower()
        return {
            "repository": repository or None,
            "repo_trust": repo_trust,
            "repository_visibility": visibility or "unknown",
            "recipient_domain": recipient_domain,
        }

    def _extract_amount(self, arguments: dict) -> float | None:
        for key in ("discount_percent", "amount", "refund_amount", "row_count"):
            if key in arguments:
                try:
                    return float(arguments[key])
                except (TypeError, ValueError):
                    return None
        return None

    def _extract_numeric_argument(self, arguments: dict, *keys: str) -> float | None:
        for key in keys:
            if key in arguments:
                try:
                    return float(arguments[key])
                except (TypeError, ValueError):
                    return None
        return None

    def _extract_integer_argument(self, arguments: dict, *keys: str) -> int | None:
        for key in keys:
            if key in arguments:
                try:
                    return int(arguments[key])
                except (TypeError, ValueError):
                    return None
        return None

    def _max_policy_severity(
        self, policies: list[Policy], result: PolicyEvaluationResult
    ) -> PolicySeverity | None:
        if not result.matched_policies:
            return None
        severity_rank = {
            PolicySeverity.LOW: 1,
            PolicySeverity.MEDIUM: 2,
            PolicySeverity.HIGH: 3,
            PolicySeverity.CRITICAL: 4,
        }
        matched_by_id = {match.policy_id for match in result.matched_policies}
        severities = [policy.severity for policy in policies if policy.id in matched_by_id]
        return max(severities, key=lambda item: severity_rank[item]) if severities else None

    def _apply_guardrails(
        self,
        *,
        payload: ToolCallRequest,
        recipient_domain: str,
        risk_band: RiskBand,
        intent_match: bool,
        policy_result: PolicyEvaluationResult,
    ) -> PolicyEvaluationResult:
        reasons = list(policy_result.reasons)
        decision = policy_result.decision
        action_lower = payload.action_name.lower()

        if decision == PolicyDecision.ALLOW and risk_band == RiskBand.CRITICAL:
            decision = (
                PolicyDecision.BLOCK
                if any(keyword in action_lower for keyword in ("delete", "export"))
                else PolicyDecision.REQUIRE_APPROVAL
            )
            reasons.append("Built-in critical risk guardrail activated.")

        if (
            decision == PolicyDecision.ALLOW
            and not intent_match
            and recipient_domain == "external"
            and risk_band in {RiskBand.HIGH, RiskBand.CRITICAL}
        ):
            decision = PolicyDecision.REQUIRE_APPROVAL
            reasons.append("Built-in externalization guardrail activated for intent mismatch.")

        return PolicyEvaluationResult(
            decision=decision,
            matched_policies=policy_result.matched_policies,
            reasons=reasons,
        )

    def _update_trace_after_success(
        self,
        db: Session,
        *,
        trace_id: str,
        tool_call_id: str,
        tool_name: str,
        action_name: str,
        finalize: bool,
        executed: bool,
    ) -> None:
        if finalize:
            self.trace_service.set_status(
                db,
                trace_id=trace_id,
                status=TraceStatus.COMPLETED,
                summary=f"Execution completed for {tool_name}.{action_name}.",
                completed=True,
            )
            self.trace_service.append_step(
                db,
                trace_id=trace_id,
                type=TraceStepType.FINAL,
                content=f"Execution completed for {tool_name}.{action_name}.",
                metadata={"tool_call_id": tool_call_id, "executed": executed},
            )
            return

        self.trace_service.set_status(
            db,
            trace_id=trace_id,
            status=TraceStatus.RUNNING,
            summary=f"Step completed for {tool_name}.{action_name}.",
        )

    def _record_execution_failure(
        self,
        db: Session,
        *,
        principal: Principal,
        tenant_id: str,
        tool_call: ToolCall,
        trace_id: str,
        tool_name: str,
        action_name: str,
        ip_address: str | None,
    ) -> None:
        tool_call.status = ToolCallStatus.FAILED
        tool_call.response_payload = {
            **(tool_call.response_payload or {}),
            "execution_error": {
                "tool_name": tool_name,
                "action_name": action_name,
            },
        }
        self.trace_service.append_step(
            db,
            trace_id=trace_id,
            type=TraceStepType.ERROR,
            content="Tool execution failed.",
            metadata={"tool_name": tool_name, "action_name": action_name},
        )
        self.trace_service.append_step(
            db,
            trace_id=trace_id,
            type=TraceStepType.FINAL,
            content="Execution failed during tool dispatch.",
            metadata={"tool_call_id": tool_call.id},
        )
        self.trace_service.set_status(
            db,
            trace_id=trace_id,
            status=TraceStatus.FAILED,
            summary="Execution failed during tool processing.",
            completed=True,
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=principal.actor_type,
            actor_id=principal.actor_id,
            event_type="gateway.tool_call.failed",
            resource_type="tool_call",
            resource_id=tool_call.id,
            metadata={"tool_name": tool_name, "action_name": action_name, "trace_id": trace_id},
            ip_address=ip_address,
        )
        db.commit()

    def _audit_preflight_denial(
        self,
        db: Session,
        *,
        principal: Principal,
        tenant_id: str,
        event_type: str,
        resource_type: str,
        resource_id: str | None,
        metadata: dict,
        ip_address: str | None,
    ) -> None:
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=principal.actor_type,
            actor_id=principal.actor_id,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata,
            ip_address=ip_address,
        )
        db.commit()

    def _tool_call_status_for_decision(self, decision: PolicyDecision) -> ToolCallStatus:
        if decision == PolicyDecision.BLOCK:
            return ToolCallStatus.BLOCKED
        if decision == PolicyDecision.REQUIRE_APPROVAL:
            return ToolCallStatus.PENDING_APPROVAL
        return ToolCallStatus.ALLOWED
