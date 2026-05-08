from __future__ import annotations

from sqlalchemy import select

from app.core.enums import (
    AgentEnvironment,
    AgentStatus,
    PolicyDecision,
    PolicySeverity,
    RiskBand,
    ToolType,
    UserRole,
)
from app.core.security import hash_password
from app.models import Agent, AuditEvent, Policy, Tenant, Tool, User
from app.services.onboarding_service import (
    ONBOARDING_DEMO_POLICY_CREATED_EVENT,
    ONBOARDING_DEMO_POLICY_NAME,
    ONBOARDING_DISMISSED_EVENT,
    ONBOARDING_RESET_EVENT,
)
from app.tests.conftest import make_token


def test_onboarding_status_rbac_and_safe_response(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    approver_token = make_token(seeded_tenants["approver_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])

    admin_response = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {admin_token}"})
    reviewer_response = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {reviewer_token}"})
    approver_response = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {approver_token}"})
    developer_response = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {developer_token}"})
    viewer_response = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {viewer_token}"})

    assert admin_response.status_code == 200
    assert reviewer_response.status_code == 200
    assert approver_response.status_code == 403
    assert developer_response.status_code == 403
    assert viewer_response.status_code == 403

    payload = admin_response.json()
    assert payload["tenant_id"] == seeded_tenants["tenant_a"].id
    assert payload["tenant_exists"] is True
    assert payload["active_owner_exists"] is False
    assert payload["agent_count"] == 1
    assert payload["tool_count"] == 7
    assert payload["policy_count"] >= 1
    assert payload["has_agent"] is True
    assert payload["has_tool"] is True
    assert payload["has_policy"] is True
    assert payload["approval_workflow_available"] is True
    assert payload["audit_integrity_configured"] is True
    assert payload["audit_integrity_status"] == "empty"
    assert payload["settings_overview_available"] is True
    assert payload["dismissed"] is False
    assert payload["recommended_next_step_href"].startswith("/")
    assert payload["checklist"]
    assert payload["links"]
    tool_check = next(item for item in payload["checklist"] if item["key"] == "tool")
    tools_link = next(item for item in payload["links"] if item["label"] == "Tools & Connectors")
    assert tool_check["href"] == "/tools"
    assert tools_link["href"] == "/tools"

    assert "AGENTGATE_GITHUB_TOKEN" not in admin_response.text
    assert "AGENTGATE_JIRA_TOKEN" not in admin_response.text
    assert "AGENTGATE_MCP_TOKEN" not in admin_response.text
    assert "https://api.github.com" not in admin_response.text
    assert "https://jira.example.test" not in admin_response.text
    assert "mcp.example.test" not in admin_response.text


def test_onboarding_status_is_tenant_scoped(client, seeded_tenants):
    tenant_b_token = make_token(seeded_tenants["admin_b"])

    response = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {tenant_b_token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == seeded_tenants["tenant_b"].id
    assert payload["agent_count"] == 1
    assert payload["tool_count"] == 1
    assert payload["policy_count"] == 0
    assert payload["has_agent"] is True
    assert payload["has_tool"] is True
    assert payload["has_policy"] is False
    assert payload["approval_workflow_available"] is True

    assert seeded_tenants["tenant_a"].id not in response.text
    assert "SalesProposalAgent" not in response.text
    assert "GitHub" not in response.text


def test_onboarding_status_changes_with_inventory(client, db_session):
    tenant = Tenant(name="Tenant C", slug="tenant-c", plan="enterprise")
    db_session.add(tenant)
    db_session.flush()
    admin = User(
        tenant_id=tenant.id,
        email="admin@tenant-c.example.com",
        full_name="Admin C",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()

    token = make_token(admin)
    initial = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {token}"})
    assert initial.status_code == 200
    initial_payload = initial.json()
    assert initial_payload["has_agent"] is False
    assert initial_payload["has_tool"] is False
    assert initial_payload["has_policy"] is False
    assert initial_payload["agent_count"] == 0
    assert initial_payload["tool_count"] == 0
    assert initial_payload["policy_count"] == 0

    db_session.add(
        Agent(
            tenant_id=tenant.id,
            name="TenantCAgent",
            description="Onboarding agent",
            owner_user_id=admin.id,
            environment=AgentEnvironment.STAGING,
            status=AgentStatus.ACTIVE,
            purpose="Run first governed workflow",
            allowed_tools=["SandboxTool"],
            allowed_data_classes=["internal"],
            risk_level=RiskBand.MEDIUM,
        )
    )
    db_session.add(
        Tool(
            tenant_id=tenant.id,
            name="SandboxTool",
            type=ToolType.MOCK,
            description="Safe demo tool",
            config={"mock": True},
            risk_level=RiskBand.MEDIUM,
            enabled=True,
        )
    )
    db_session.add(
        Policy(
            tenant_id=tenant.id,
            name="Tenant C approval policy",
            description="Approval starter",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [{"field": "risk_score", "operator": "greater_than", "value": 60}],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=admin.id,
        )
    )
    db_session.commit()

    updated = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {token}"})
    assert updated.status_code == 200
    updated_payload = updated.json()
    assert updated_payload["has_agent"] is True
    assert updated_payload["has_tool"] is True
    assert updated_payload["has_policy"] is True
    assert updated_payload["agent_count"] == 1
    assert updated_payload["tool_count"] == 1
    assert updated_payload["policy_count"] == 1


def test_onboarding_actions_are_narrow_and_audited(client, db_session, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])

    reviewer_dismiss = client.post("/v1/onboarding/dismiss", headers={"Authorization": f"Bearer {reviewer_token}"})
    reviewer_demo_policy = client.post(
        "/v1/onboarding/demo-policy",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    assert reviewer_dismiss.status_code == 403
    assert reviewer_demo_policy.status_code == 403

    dismiss_response = client.post("/v1/onboarding/dismiss", headers={"Authorization": f"Bearer {admin_token}"})
    assert dismiss_response.status_code == 200
    assert dismiss_response.json()["dismissed"] is True

    status_after_dismiss = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {admin_token}"})
    assert status_after_dismiss.status_code == 200
    assert status_after_dismiss.json()["dismissed"] is True

    create_demo_policy = client.post(
        "/v1/onboarding/demo-policy",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert create_demo_policy.status_code == 200
    create_payload = create_demo_policy.json()
    assert create_payload["created"] is True
    assert create_payload["policy_id"]

    duplicate_demo_policy = client.post(
        "/v1/onboarding/demo-policy",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert duplicate_demo_policy.status_code == 200
    assert duplicate_demo_policy.json()["created"] is False

    reset_response = client.post("/v1/onboarding/reset", headers={"Authorization": f"Bearer {admin_token}"})
    assert reset_response.status_code == 200
    assert reset_response.json()["dismissed"] is False

    status_after_reset = client.get("/v1/onboarding/status", headers={"Authorization": f"Bearer {admin_token}"})
    assert status_after_reset.status_code == 200
    assert status_after_reset.json()["dismissed"] is False

    stored_policy = db_session.scalar(
        select(Policy).where(
            Policy.tenant_id == seeded_tenants["tenant_a"].id,
            Policy.name == ONBOARDING_DEMO_POLICY_NAME,
        )
    )
    assert stored_policy is not None

    audit_events = list(
        db_session.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.tenant_id == seeded_tenants["tenant_a"].id,
                AuditEvent.event_type.in_(
                    [
                        ONBOARDING_DISMISSED_EVENT,
                        ONBOARDING_RESET_EVENT,
                        ONBOARDING_DEMO_POLICY_CREATED_EVENT,
                        "policy.created",
                    ]
                ),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    )
    event_types = [event.event_type for event in audit_events]
    assert ONBOARDING_DISMISSED_EVENT in event_types
    assert ONBOARDING_RESET_EVENT in event_types
    assert ONBOARDING_DEMO_POLICY_CREATED_EVENT in event_types
    assert "policy.created" in event_types
