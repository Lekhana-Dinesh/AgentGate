from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.enums import (
    AgentEnvironment,
    AgentStatus,
    PolicyDecision,
    PolicySeverity,
    RiskBand,
    ToolType,
    UserRole,
)
from app.core.metrics import get_metrics_registry
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.main import app
from app.models import Agent, Policy, Tenant, Tool, User
from app.security.key_management import get_key_provider
from app.services.rate_limit_service import get_rate_limiter
from app.tools.github_auth import GitHubAppAuthProvider


@pytest.fixture(autouse=True)
def reset_runtime_state():
    get_settings.cache_clear()
    get_key_provider.cache_clear()
    GitHubAppAuthProvider.clear_cache()
    get_rate_limiter().reset()
    get_metrics_registry().reset()
    yield
    get_settings.cache_clear()
    get_key_provider.cache_clear()
    GitHubAppAuthProvider.clear_cache()
    get_rate_limiter().reset()
    get_metrics_registry().reset()


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def seeded_tenants(db_session):
    tenant_a = Tenant(name="Tenant A", slug="tenant-a", plan="enterprise")
    tenant_b = Tenant(name="Tenant B", slug="tenant-b", plan="enterprise")
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    admin_a = User(
        tenant_id=tenant_a.id,
        email="admin@tenant-a.example.com",
        full_name="Admin A",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    reviewer_a = User(
        tenant_id=tenant_a.id,
        email="reviewer@tenant-a.example.com",
        full_name="Reviewer A",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.SECURITY_REVIEWER,
        is_active=True,
    )
    approver_a = User(
        tenant_id=tenant_a.id,
        email="approver@tenant-a.example.com",
        full_name="Approver A",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.APPROVER,
        is_active=True,
    )
    developer_a = User(
        tenant_id=tenant_a.id,
        email="developer@tenant-a.example.com",
        full_name="Developer A",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.DEVELOPER,
        is_active=True,
    )
    viewer_a = User(
        tenant_id=tenant_a.id,
        email="viewer@tenant-a.example.com",
        full_name="Viewer A",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.VIEWER,
        is_active=True,
    )
    admin_b = User(
        tenant_id=tenant_b.id,
        email="admin@tenant-b.example.com",
        full_name="Admin B",
        hashed_password=hash_password("AgentGate123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add_all([admin_a, reviewer_a, approver_a, developer_a, viewer_a, admin_b])
    db_session.flush()

    agent_a = Agent(
        tenant_id=tenant_a.id,
        name="SalesProposalAgent",
        description="Tenant A sales agent",
        owner_user_id=admin_a.id,
        environment=AgentEnvironment.PRODUCTION,
        status=AgentStatus.ACTIVE,
        purpose="Prepare proposals",
        allowed_tools=["Salesforce", "PricingDB", "Email", "Postgres", "GitHub", "Jira", "MCP"],
        allowed_data_classes=["customer_data", "internal_pricing", "confidential", "financial", "customer_visible", "external_project"],
        risk_level=RiskBand.HIGH,
    )
    agent_b = Agent(
        tenant_id=tenant_b.id,
        name="TenantBAgent",
        description="Tenant B agent",
        owner_user_id=admin_b.id,
        environment=AgentEnvironment.DEVELOPMENT,
        status=AgentStatus.ACTIVE,
        purpose="Tenant B agent",
        allowed_tools=["Salesforce"],
        allowed_data_classes=["customer_data"],
        risk_level=RiskBand.MEDIUM,
    )
    db_session.add_all([agent_a, agent_b])

    tools = [
        Tool(tenant_id=tenant_a.id, name="Salesforce", type=ToolType.CRM, description="CRM", config={"mock": True}, risk_level=RiskBand.MEDIUM, enabled=True),
        Tool(tenant_id=tenant_a.id, name="PricingDB", type=ToolType.MOCK, description="Pricing", config={"mock": True}, risk_level=RiskBand.HIGH, enabled=True),
        Tool(tenant_id=tenant_a.id, name="Email", type=ToolType.MOCK, description="Email", config={"mock": True}, risk_level=RiskBand.HIGH, enabled=True),
        Tool(tenant_id=tenant_a.id, name="Postgres", type=ToolType.MOCK, description="Postgres", config={"mock": True}, risk_level=RiskBand.CRITICAL, enabled=True),
        Tool(
            tenant_id=tenant_a.id,
            name="GitHub",
            type=ToolType.GITHUB,
            description="GitHub connector",
            base_url="https://api.github.com",
            config={
                "auth_mode": "env_pat",
                "token_env_var": "AGENTGATE_GITHUB_TOKEN",
                "internal_repositories": ["agentgate-labs/internal-agentgate"],
                "internal_owners": ["agentgate-labs"],
                "public_repositories": ["octocat/hello-world"],
                "repository_allowlist": ["agentgate-labs/internal-agentgate", "octocat/hello-world"],
                "max_read_retries": 2,
                "retry_backoff_seconds": 0.0,
            },
            risk_level=RiskBand.HIGH,
            enabled=True,
        ),
        Tool(
            tenant_id=tenant_a.id,
            name="Jira",
            type=ToolType.JIRA,
            description="Jira connector",
            base_url="https://jira.example.test",
            config={
                "auth_mode": "env_token",
                "token_env_var": "AGENTGATE_JIRA_TOKEN",
                "project_allowlist": ["OPS", "SUPPORT"],
                "issue_type_allowlist": ["task", "bug", "incident"],
                "external_project_keys": ["SUPPORT"],
                "transition_allowlist": ["done", "31"],
                "assignee_allowlist": ["acct-support-1", "acct-oncall-1"],
                "max_read_retries": 1,
                "retry_backoff_seconds": 0.0,
            },
            risk_level=RiskBand.HIGH,
            enabled=True,
        ),
        Tool(
            tenant_id=tenant_a.id,
            name="MCP",
            type=ToolType.MCP,
            description="Governed MCP connector",
            base_url="https://mcp.example.test",
            config={
                "transport": "http",
                "auth_mode": "bearer_env",
                "token_env_var": "AGENTGATE_MCP_TOKEN",
                "allowed_tool_names": ["knowledge_search", "ticket_comment", "shell_execute"],
                "blocked_tool_names": ["delete_records"],
                "max_request_bytes": 16384,
                "max_response_bytes": 65536,
                "timeout_ms": 5000,
                "trust_domain": "internal",
                "max_read_retries": 1,
                "retry_backoff_seconds": 0.0,
            },
            risk_level=RiskBand.HIGH,
            enabled=True,
        ),
        Tool(tenant_id=tenant_b.id, name="Salesforce", type=ToolType.CRM, description="CRM", config={"mock": True}, risk_level=RiskBand.MEDIUM, enabled=True),
    ]
    db_session.add_all(tools)
    db_session.flush()

    policies = [
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for discount above 20 percent",
            description="Discount control",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "action_name", "operator": "contains", "value": "discount"},
                    {"field": "discount_percent", "operator": "greater_than", "value": 20},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Block production database export above 1000 rows",
            description="Export control",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "Postgres"},
                    {"field": "action_name", "operator": "contains", "value": "export"},
                    {"field": "environment", "operator": "equals", "value": "production"},
                    {"field": "row_count", "operator": "greater_than", "value": 1000},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for intent mismatch on external action",
            description="Externalization control",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "recipient_domain", "operator": "equals", "value": "external"},
                    {"field": "intent_mismatch", "operator": "equals", "value": True},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for GitHub public comments",
            description="Public comment control",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                    {"field": "action_name", "operator": "contains", "value": "comment"},
                    {"field": "repo_trust", "operator": "equals", "value": "public"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Block confidential GitHub public comments",
            description="Blocks confidential content in public GitHub comment bodies",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                    {"field": "action_name", "operator": "contains", "value": "comment"},
                    {"field": "repo_trust", "operator": "equals", "value": "public"},
                    {"field": "data_classification", "operator": "contains", "value": "confidential"},
                    {"field": "data_classification", "operator": "contains", "value": "public_comment_body"},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Block GitHub destructive actions",
            description="Destructive GitHub control",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                    {"field": "action_name", "operator": "contains", "value": "delete"},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for Jira production transitions",
            description="Production Jira transition control",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "Jira"},
                    {"field": "action_name", "operator": "contains", "value": "transition"},
                    {"field": "environment", "operator": "equals", "value": "production"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for Jira customer visible comments",
            description="Customer-visible Jira comment control",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "Jira"},
                    {"field": "action_name", "operator": "contains", "value": "comment"},
                    {"field": "data_classification", "operator": "contains", "value": "customer_visible"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Block confidential Jira comments",
            description="Blocks confidential data in Jira comments",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "Jira"},
                    {"field": "action_name", "operator": "contains", "value": "comment"},
                    {"field": "data_classification", "operator": "contains", "value": "confidential"},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Block Jira destructive actions",
            description="Destructive Jira control",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "Jira"},
                    {"field": "action_name", "operator": "contains", "value": "delete"},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for GitHub issues in production",
            description="Production GitHub issue control",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "GitHub"},
                    {"field": "action_name", "operator": "equals", "value": "create_issue"},
                    {"field": "environment", "operator": "equals", "value": "production"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for external MCP tools",
            description="External MCP calls require human review.",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "MCP"},
                    {"field": "action_name", "operator": "equals", "value": "call_tool"},
                    {"field": "recipient_domain", "operator": "equals", "value": "external"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Require approval for side-effecting MCP tools",
            description="Write-capable MCP tools require approval before execution.",
            enabled=True,
            severity=PolicySeverity.HIGH,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "MCP"},
                    {"field": "action_name", "operator": "equals", "value": "call_tool"},
                    {"field": "data_classification", "operator": "contains", "value": "remote_tool_side_effect"},
                ],
            },
            decision=PolicyDecision.REQUIRE_APPROVAL,
            created_by=reviewer_a.id,
        ),
        Policy(
            tenant_id=tenant_a.id,
            name="Block dangerous MCP tool names",
            description="Dangerous MCP tool names are blocked until explicitly reviewed and modeled.",
            enabled=True,
            severity=PolicySeverity.CRITICAL,
            conditions={
                "match": "all",
                "rules": [
                    {"field": "tool_name", "operator": "equals", "value": "MCP"},
                    {"field": "data_classification", "operator": "contains", "value": "dangerous_remote_tool_name"},
                ],
            },
            decision=PolicyDecision.BLOCK,
            created_by=reviewer_a.id,
        ),
    ]
    db_session.add_all(policies)
    db_session.commit()

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "admin_a": admin_a,
        "reviewer_a": reviewer_a,
        "approver_a": approver_a,
        "developer_a": developer_a,
        "viewer_a": viewer_a,
        "admin_b": admin_b,
        "agent_a": agent_a,
        "agent_b": agent_b,
    }


def make_token(user: User) -> str:
    return create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role.value)
