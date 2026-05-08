from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import AuditActorType, PolicyDecision, PolicySeverity, UserRole
from app.core.errors import AppError
from app.models import Agent, AuditEvent, Policy, Tenant, Tool, User
from app.schemas.onboarding import (
    OnboardingActionResponse,
    OnboardingChecklistItemResponse,
    OnboardingLinkResponse,
    OnboardingStatusResponse,
)
from app.services.audit_integrity_service import AuditIntegrityService
from app.services.audit_service import AuditService

ONBOARDING_DISMISSED_EVENT = "onboarding.dismissed"
ONBOARDING_RESET_EVENT = "onboarding.reset"
ONBOARDING_DEMO_POLICY_CREATED_EVENT = "onboarding.demo_policy.created"
ONBOARDING_DEMO_POLICY_NAME = "Onboarding Demo - Require Approval For High-Risk Actions"

APPROVAL_ROLES = (
    UserRole.OWNER,
    UserRole.ADMIN,
    UserRole.SECURITY_REVIEWER,
    UserRole.APPROVER,
)


class OnboardingService:
    def __init__(self) -> None:
        self.audit_integrity_service = AuditIntegrityService()
        self.audit_service = AuditService()

    def get_status(self, db: Session, *, tenant_id: str) -> OnboardingStatusResponse:
        tenant = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
        if tenant is None:
            raise AppError("Tenant not found.", status_code=404, code="tenant_not_found")

        owner_count = self._count_rows(
            db,
            User,
            User.tenant_id == tenant_id,
            User.role == UserRole.OWNER,
            User.is_active.is_(True),
        )
        agent_count = self._count_rows(db, Agent, Agent.tenant_id == tenant_id)
        tool_count = self._count_rows(db, Tool, Tool.tenant_id == tenant_id)
        policy_count = self._count_rows(db, Policy, Policy.tenant_id == tenant_id)
        approval_workflow_available = bool(
            self._count_rows(
                db,
                User,
                User.tenant_id == tenant_id,
                User.role.in_(APPROVAL_ROLES),
                User.is_active.is_(True),
            )
        )
        audit_integrity = self.audit_integrity_service.get_status(db, tenant_id=tenant_id)
        dismissed = self._is_dismissed(db, tenant_id=tenant_id)

        active_owner_exists = owner_count > 0
        has_agent = agent_count > 0
        has_tool = tool_count > 0
        has_policy = policy_count > 0
        recommendation, recommendation_href = self._recommended_next_step(
            active_owner_exists=active_owner_exists,
            has_agent=has_agent,
            has_tool=has_tool,
            has_policy=has_policy,
            approval_workflow_available=approval_workflow_available,
            audit_integrity_status=audit_integrity.status,
        )

        return OnboardingStatusResponse(
            tenant_id=tenant_id,
            tenant_exists=True,
            active_owner_exists=active_owner_exists,
            agent_count=agent_count,
            tool_count=tool_count,
            policy_count=policy_count,
            has_agent=has_agent,
            has_tool=has_tool,
            has_policy=has_policy,
            approval_workflow_available=approval_workflow_available,
            audit_integrity_configured=True,
            audit_integrity_status=audit_integrity.status,
            settings_overview_available=True,
            dismissed=dismissed,
            recommended_next_step=recommendation,
            recommended_next_step_href=recommendation_href,
            checklist=self._build_checklist(
                active_owner_exists=active_owner_exists,
                has_agent=has_agent,
                has_tool=has_tool,
                has_policy=has_policy,
                approval_workflow_available=approval_workflow_available,
                audit_integrity_status=audit_integrity.status,
            ),
            links=self._build_links(),
        )

    def dismiss(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_id: str,
        ip_address: str | None,
    ) -> OnboardingActionResponse:
        if self._is_dismissed(db, tenant_id=tenant_id):
            return OnboardingActionResponse(
                action="dismiss",
                message="Onboarding was already dismissed for this tenant.",
                dismissed=True,
            )

        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            event_type=ONBOARDING_DISMISSED_EVENT,
            resource_type="tenant",
            resource_id=tenant_id,
            metadata={"dismissed": True},
            ip_address=ip_address,
        )
        db.commit()
        return OnboardingActionResponse(
            action="dismiss",
            message="Onboarding checklist dismissed for this tenant.",
            dismissed=True,
        )

    def reset(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_id: str,
        ip_address: str | None,
    ) -> OnboardingActionResponse:
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            event_type=ONBOARDING_RESET_EVENT,
            resource_type="tenant",
            resource_id=tenant_id,
            metadata={"dismissed": False},
            ip_address=ip_address,
        )
        db.commit()
        return OnboardingActionResponse(
            action="reset",
            message="Onboarding walkthrough state reset for this tenant.",
            dismissed=False,
        )

    def create_demo_policy(
        self,
        db: Session,
        *,
        tenant_id: str,
        actor_id: str,
        ip_address: str | None,
    ) -> OnboardingActionResponse:
        existing = db.scalar(
            select(Policy).where(
                Policy.tenant_id == tenant_id,
                Policy.name == ONBOARDING_DEMO_POLICY_NAME,
            )
        )
        if existing is not None:
            return OnboardingActionResponse(
                action="create_demo_policy",
                message="The onboarding demo policy already exists for this tenant.",
                created=False,
                policy_id=existing.id,
            )

        policy = Policy(
            tenant_id=tenant_id,
            name=ONBOARDING_DEMO_POLICY_NAME,
            description="Starter policy for first-run evaluations that routes high-risk actions to human approval.",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {
                        "field": "risk_score",
                        "operator": "greater_than",
                        "value": 70,
                    }
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=actor_id,
        )
        db.add(policy)
        db.flush()

        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            event_type="policy.created",
            resource_type="policy",
            resource_id=policy.id,
            metadata={"severity": policy.severity.value, "decision": policy.decision.value},
            ip_address=ip_address,
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor_id,
            event_type=ONBOARDING_DEMO_POLICY_CREATED_EVENT,
            resource_type="policy",
            resource_id=policy.id,
            metadata={"name": policy.name},
            ip_address=ip_address,
        )
        db.commit()
        return OnboardingActionResponse(
            action="create_demo_policy",
            message="Created the onboarding demo policy for this tenant.",
            created=True,
            policy_id=policy.id,
        )

    def _is_dismissed(self, db: Session, *, tenant_id: str) -> bool:
        latest_dismiss = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == ONBOARDING_DISMISSED_EVENT,
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1)
        )
        if latest_dismiss is None:
            return False

        latest_reset = db.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.event_type == ONBOARDING_RESET_EVENT,
            )
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1)
        )
        if latest_reset is None:
            return True

        if latest_dismiss.created_at > latest_reset.created_at:
            return True
        if latest_dismiss.created_at < latest_reset.created_at:
            return False
        return latest_dismiss.id > latest_reset.id

    def _recommended_next_step(
        self,
        *,
        active_owner_exists: bool,
        has_agent: bool,
        has_tool: bool,
        has_policy: bool,
        approval_workflow_available: bool,
        audit_integrity_status: str,
    ) -> tuple[str, str]:
        if not has_agent:
            return (
                "Create at least one agent so governed tool calls have an explicit runtime identity.",
                "/agents",
            )
        if not has_tool:
            return (
                "Configure at least one governed tool or connector before attempting a first workflow.",
                "/tools",
            )
        if not has_policy:
            return (
                "Add a starter policy or create the onboarding demo policy before running a first governed action.",
                "/policies",
            )
        if not approval_workflow_available:
            return (
                "Ensure an owner, admin, approver, or security reviewer can handle human approval steps.",
                "/users",
            )
        if audit_integrity_status == "legacy_only":
            return (
                "Backfill or re-anchor audit history before treating audit verification as complete evidence.",
                "/audit-integrity",
            )
        if not active_owner_exists:
            return (
                "Add an active owner account for recovery, governance continuity, and owner lockout protection.",
                "/users",
            )
        return (
            "Run the demo scenario or send a governed tool call through the gateway to validate the full workflow.",
            "/demo",
        )

    def _build_checklist(
        self,
        *,
        active_owner_exists: bool,
        has_agent: bool,
        has_tool: bool,
        has_policy: bool,
        approval_workflow_available: bool,
        audit_integrity_status: str,
    ) -> list[OnboardingChecklistItemResponse]:
        return [
            OnboardingChecklistItemResponse(
                key="active_owner",
                label="Active owner account",
                description="At least one active owner should exist for recovery and governance continuity.",
                complete=active_owner_exists,
                href="/users",
            ),
            OnboardingChecklistItemResponse(
                key="agent",
                label="Governed agent",
                description="Agents define which runtime identities can invoke governed tools.",
                complete=has_agent,
                href="/agents",
            ),
            OnboardingChecklistItemResponse(
                key="tool",
                label="Tool or connector",
                description="Configure at least one governed tool or connector before running a workflow.",
                complete=has_tool,
                href="/tools",
            ),
            OnboardingChecklistItemResponse(
                key="policy",
                label="Policy coverage",
                description="At least one enabled policy should exist before a design-partner evaluation.",
                complete=has_policy,
                href="/policies",
            ),
            OnboardingChecklistItemResponse(
                key="approval_workflow",
                label="Approval workflow",
                description="A reviewer-capable user should be available for human approval decisions.",
                complete=approval_workflow_available,
                href="/approvals",
            ),
            OnboardingChecklistItemResponse(
                key="audit_integrity",
                label="Audit integrity",
                description="Audit verification is available. Backfill legacy history before treating older evidence as anchored.",
                complete=audit_integrity_status != "legacy_only",
                href="/audit-integrity",
            ),
            OnboardingChecklistItemResponse(
                key="settings",
                label="Settings overview",
                description="Read-only operational status is available without exposing secrets or raw config.",
                complete=True,
                href="/settings",
            ),
        ]

    def _build_links(self) -> list[OnboardingLinkResponse]:
        return [
            OnboardingLinkResponse(
                label="Agents",
                href="/agents",
                description="Create or review governed runtime identities.",
            ),
            OnboardingLinkResponse(
                label="Tools & Connectors",
                href="/tools",
                description="Review connector posture, health status, and safe tool metadata.",
            ),
            OnboardingLinkResponse(
                label="Policies",
                href="/policies",
                description="Review or add runtime guardrails before the first live workflow.",
            ),
            OnboardingLinkResponse(
                label="Settings",
                href="/settings",
                description="Check OIDC, connectors, retention, keys, tasks, and rate limiting.",
            ),
            OnboardingLinkResponse(
                label="Audit Integrity",
                href="/audit-integrity",
                description="Verify hash-chain status and external checkpoint readiness.",
            ),
            OnboardingLinkResponse(
                label="Demo Walkthrough",
                href="/demo",
                description="Run the seeded governed scenario from the dashboard experience.",
            ),
        ]

    def _count_rows(self, db: Session, model, *filters) -> int:
        statement = select(func.count()).select_from(model)
        if filters:
            statement = statement.where(*filters)
        return int(db.scalar(statement) or 0)
