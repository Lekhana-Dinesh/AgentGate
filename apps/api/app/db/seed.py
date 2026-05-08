from __future__ import annotations

from sqlalchemy import select

from app.core.config import get_settings
from app.core.networking import is_production_like_environment
from app.core.enums import (
    AgentEnvironment,
    AgentStatus,
    AuditActorType,
    PolicyDecision,
    PolicySeverity,
    RiskBand,
    ToolType,
    TraceStatus,
    TraceStepType,
    UserRole,
)
from app.core.security import hash_password
from app.db.init_db import init_db
from app.db.session import SessionLocal
from app.models import Agent, AuditEvent, ExecutionTrace, Policy, Tenant, Tool, TraceStep, User


def _policy_conditions(*, match: str = "all", rules: list[dict]) -> dict:
    return {"match": match, "rules": rules}


def seed() -> None:
    settings = get_settings()
    if is_production_like_environment(settings.environment) and not settings.allow_demo_credentials:
        raise RuntimeError(
            "Demo seed credentials are disabled outside development/test unless AGENTGATE_ALLOW_DEMO_CREDENTIALS=true."
        )
    init_db()
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "demo-agentgate"))
        if not tenant:
            tenant = Tenant(name="AgentGate Demo", slug="demo-agentgate", plan="enterprise-trial")
            db.add(tenant)
            db.flush()

        users = {
            "admin@demo.agentgate.example.com": ("Demo Admin", UserRole.ADMIN),
            "reviewer@demo.agentgate.example.com": ("Demo Reviewer", UserRole.SECURITY_REVIEWER),
        }
        created_users: dict[str, User] = {}
        for email, (full_name, role) in users.items():
            user = db.scalar(select(User).where(User.tenant_id == tenant.id, User.email == email))
            if not user:
                user = User(
                    tenant_id=tenant.id,
                    email=email,
                    full_name=full_name,
                    hashed_password=hash_password("AgentGate123!"),
                    role=role,
                    is_active=True,
                )
                db.add(user)
                db.flush()
            created_users[email] = user

        agent = db.scalar(select(Agent).where(Agent.tenant_id == tenant.id, Agent.name == "SalesProposalAgent"))
        if not agent:
            agent = Agent(
                tenant_id=tenant.id,
                name="SalesProposalAgent",
                description="Prepares renewal proposals using CRM, pricing, and outbound comms tools.",
                owner_user_id=created_users["admin@demo.agentgate.example.com"].id,
                environment=AgentEnvironment.PRODUCTION,
                status=AgentStatus.ACTIVE,
                purpose="Prepare and coordinate customer renewal proposals under runtime policy control.",
                allowed_tools=["Salesforce", "PricingDB", "Email", "Jira", "MCP", "Postgres", "GitHub"],
                allowed_data_classes=["customer_data", "internal_pricing", "financial", "confidential", "customer_visible", "external_project"],
                risk_level=RiskBand.HIGH,
            )
            db.add(agent)
            db.flush()
        else:
            agent.allowed_tools = sorted({*(agent.allowed_tools or []), "GitHub", "MCP", "Jira"})

        tools = [
            ("Salesforce", ToolType.CRM, "Mock CRM account reader.", None, {"mock": True}, RiskBand.MEDIUM),
            ("PricingDB", ToolType.DATABASE, "Mock pricing database reader and discount simulator.", None, {"mock": True}, RiskBand.HIGH),
            ("Email", ToolType.EMAIL, "Mock outbound email sender.", None, {"mock": True}, RiskBand.HIGH),
            ("Jira", ToolType.JIRA, "Mock Jira ticket creation adapter.", "https://jira.example.test", {"mock": True}, RiskBand.LOW),
            ("MCP", ToolType.MCP, "Mock governed MCP adapter.", "https://mcp.example.test", {"mock": True}, RiskBand.HIGH),
            ("Postgres", ToolType.DATABASE, "Mock production database query and export adapter.", None, {"mock": True}, RiskBand.CRITICAL),
            (
                "GitHub",
                ToolType.GITHUB,
                "GitHub repository metadata, issue, and pull request adapter.",
                "https://api.github.com",
                {
                    "auth_mode": "env_pat",
                    "token_env_var": "AGENTGATE_GITHUB_TOKEN",
                    "internal_repositories": ["agentgate-labs/internal-agentgate"],
                    "internal_owners": ["agentgate-labs"],
                    "public_repositories": ["octocat/hello-world"],
                    "repository_allowlist": ["agentgate-labs/internal-agentgate", "octocat/hello-world"],
                    "max_read_retries": 2,
                    "retry_backoff_seconds": 0.2,
                },
                RiskBand.HIGH,
            ),
        ]
        for name, tool_type, description, base_url, config, risk_level in tools:
            tool = db.scalar(select(Tool).where(Tool.tenant_id == tenant.id, Tool.name == name))
            if not tool:
                db.add(
                    Tool(
                        tenant_id=tenant.id,
                        name=name,
                        type=tool_type,
                        description=description,
                        base_url=base_url,
                        config=config,
                        risk_level=risk_level,
                        enabled=True,
                    )
                )
            else:
                tool.type = tool_type
                tool.description = description
                tool.base_url = base_url
                tool.config = config
                tool.risk_level = risk_level
                tool.enabled = True

        policies = [
            (
                "Block confidential data to external recipients",
                "Blocks sending confidential data classes to external recipient domains.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "recipient_domain", "operator": "equals", "value": "external"},
                        {"field": "data_classification", "operator": "contains", "value": "confidential"},
                    ]
                ),
            ),
            (
                "Require approval for discount above 20 percent",
                "Routes large discounts for human review before the agent can proceed.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "action_name", "operator": "contains", "value": "discount"},
                        {"field": "discount_percent", "operator": "greater_than", "value": 20},
                    ]
                ),
            ),
            (
                "Block production database export above 1000 rows",
                "Blocks large production exports from the mock Postgres adapter.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "Postgres"},
                        {"field": "action_name", "operator": "contains", "value": "export"},
                        {"field": "environment", "operator": "equals", "value": "production"},
                        {"field": "row_count", "operator": "greater_than", "value": 1000},
                    ]
                ),
            ),
            (
                "Require approval for intent mismatch on external action",
                "Routes external actions to review when the deterministic intent checker sees a mismatch.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "recipient_domain", "operator": "equals", "value": "external"},
                        {"field": "intent_mismatch", "operator": "equals", "value": True},
                    ]
                ),
            ),
            (
                "Require approval for GitHub public comments",
                "Routes GitHub comments to review when they target a public or external repository.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                        {"field": "action_name", "operator": "contains", "value": "comment"},
                        {"field": "repo_trust", "operator": "equals", "value": "public"},
                    ]
                ),
            ),
            (
                "Block confidential GitHub public comments",
                "Blocks public GitHub comments that contain confidential data classifications.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                        {"field": "action_name", "operator": "contains", "value": "comment"},
                        {"field": "repo_trust", "operator": "equals", "value": "public"},
                        {"field": "data_classification", "operator": "contains", "value": "confidential"},
                        {"field": "data_classification", "operator": "contains", "value": "public_comment_body"},
                    ]
                ),
            ),
            (
                "Block GitHub destructive actions",
                "Blocks destructive repository actions until the platform adds explicit support and review paths.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                        {"field": "action_name", "operator": "contains", "value": "delete"},
                    ]
                ),
            ),
            (
                "Require approval for GitHub issues in production",
                "Routes GitHub issue creation for production agents through human review.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                        {"field": "action_name", "operator": "equals", "value": "create_issue"},
                        {"field": "environment", "operator": "equals", "value": "production"},
                    ]
                ),
            ),
            (
                "Require approval for Jira production transitions",
                "Routes Jira workflow transitions for production agents through human review.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "Jira"},
                        {"field": "action_name", "operator": "contains", "value": "transition"},
                        {"field": "environment", "operator": "equals", "value": "production"},
                    ]
                ),
            ),
            (
                "Require approval for Jira customer visible comments",
                "Routes customer-visible Jira comments through human review.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "Jira"},
                        {"field": "action_name", "operator": "contains", "value": "comment"},
                        {"field": "data_classification", "operator": "contains", "value": "customer_visible"},
                    ]
                ),
            ),
            (
                "Block confidential Jira comments",
                "Blocks confidential data classes from being posted into Jira comments.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "Jira"},
                        {"field": "action_name", "operator": "contains", "value": "comment"},
                        {"field": "data_classification", "operator": "contains", "value": "confidential"},
                    ]
                ),
            ),
            (
                "Block Jira destructive actions",
                "Blocks destructive Jira actions until the platform adds explicit support and review paths.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "Jira"},
                        {"field": "action_name", "operator": "contains", "value": "delete"},
                    ]
                ),
            ),
            (
                "Require approval for external MCP tools",
                "Routes external MCP tool calls through human review.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "MCP"},
                        {"field": "action_name", "operator": "equals", "value": "call_tool"},
                        {"field": "recipient_domain", "operator": "equals", "value": "external"},
                    ]
                ),
            ),
            (
                "Require approval for side-effecting MCP tools",
                "Routes write-capable MCP tool calls through human review.",
                PolicySeverity.HIGH,
                PolicyDecision.REQUIRE_APPROVAL,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "MCP"},
                        {"field": "action_name", "operator": "equals", "value": "call_tool"},
                        {"field": "data_classification", "operator": "contains", "value": "remote_tool_side_effect"},
                    ]
                ),
            ),
            (
                "Block dangerous MCP tool names",
                "Blocks dangerous MCP tool names until explicitly modeled and approved.",
                PolicySeverity.CRITICAL,
                PolicyDecision.BLOCK,
                _policy_conditions(
                    rules=[
                        {"field": "tool_name", "operator": "equals", "value": "MCP"},
                        {"field": "data_classification", "operator": "contains", "value": "dangerous_remote_tool_name"},
                    ]
                ),
            ),
        ]
        for name, description, severity, decision, conditions in policies:
            policy = db.scalar(select(Policy).where(Policy.tenant_id == tenant.id, Policy.name == name))
            if not policy:
                db.add(
                    Policy(
                        tenant_id=tenant.id,
                        name=name,
                        description=description,
                        enabled=True,
                        severity=severity,
                        conditions=conditions,
                        decision=decision,
                        created_by=created_users["reviewer@demo.agentgate.example.com"].id,
                    )
                )

        trace = db.scalar(
            select(ExecutionTrace).where(
                ExecutionTrace.tenant_id == tenant.id,
                ExecutionTrace.summary == "Seeded demo trace",
            )
        )
        if not trace:
            trace = ExecutionTrace(
                tenant_id=tenant.id,
                agent_id=agent.id,
                user_id=created_users["admin@demo.agentgate.example.com"].id,
                original_intent="Prepare and send a renewal proposal to Acme Corp.",
                status=TraceStatus.COMPLETED,
                summary="Seeded demo trace",
                metadata_json={"seeded": True},
            )
            db.add(trace)
            db.flush()
            db.add(
                TraceStep(
                    trace_id=trace.id,
                    step_number=1,
                    type=TraceStepType.THOUGHT,
                    content="Seeded trace created for the dashboard replay page.",
                    metadata_json={"seeded": True},
                )
            )
            db.add(
                AuditEvent(
                    tenant_id=tenant.id,
                    actor_type=AuditActorType.SYSTEM,
                    actor_id=None,
                    event_type="seed.completed",
                    resource_type="tenant",
                    resource_id=tenant.id,
                    metadata_json={"seeded": True},
                    ip_address=None,
                )
            )

        db.commit()
        print("Seed complete.")
        print("Tenant slug: demo-agentgate")
        print("Admin login: admin@demo.agentgate.example.com / AgentGate123!")
        print("Reviewer login: reviewer@demo.agentgate.example.com / AgentGate123!")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
