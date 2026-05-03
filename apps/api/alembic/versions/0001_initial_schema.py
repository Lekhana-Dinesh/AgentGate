"""initial schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-01 00:00:00

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

user_role = sa.Enum(
    "owner",
    "admin",
    "security_reviewer",
    "developer",
    "approver",
    "viewer",
    name="userrole",
)
agent_environment = sa.Enum("development", "staging", "production", name="agentenvironment")
agent_status = sa.Enum("active", "suspended", "revoked", name="agentstatus")
tool_type = sa.Enum("mcp", "rest", "mock", "database", "email", "crm", "custom", name="tooltype")
policy_severity = sa.Enum("low", "medium", "high", "critical", name="policyseverity")
policy_decision = sa.Enum("allow", "block", "require_approval", "redact", name="policydecision")
tool_call_status = sa.Enum(
    "allowed", "blocked", "pending_approval", "executed", "failed", name="toolcallstatus"
)
approval_status = sa.Enum("pending", "approved", "rejected", "expired", name="approvalstatus")
audit_actor_type = sa.Enum("user", "agent", "system", name="auditactortype")
trace_status = sa.Enum(
    "running", "completed", "failed", "blocked", "pending_approval", name="tracestatus"
)
trace_step_type = sa.Enum(
    "thought", "tool_call", "policy_decision", "approval", "final", "error", name="tracesteptype"
)
risk_band = sa.Enum("low", "medium", "high", "critical", name="riskband")


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("plan", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=512), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])

    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("environment", agent_environment, nullable=False),
        sa.Column("status", agent_status, nullable=False),
        sa.Column("purpose", sa.String(length=1000), nullable=False),
        sa.Column("allowed_tools", sa.JSON(), nullable=False),
        sa.Column("allowed_data_classes", sa.JSON(), nullable=False),
        sa.Column("risk_level", risk_band, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_agents_tenant_name"),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])
    op.create_index("ix_agents_status", "agents", ["status"])

    op.create_table(
        "tools",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("type", tool_type, nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("base_url", sa.String(length=1000), nullable=True),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("risk_level", risk_band, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_tools_tenant_name"),
    )
    op.create_index("ix_tools_tenant_id", "tools", ["tenant_id"])

    op.create_table(
        "policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("severity", policy_severity, nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("decision", policy_decision, nullable=False),
        sa.Column("created_by", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_policies_tenant_name"),
    )
    op.create_index("ix_policies_tenant_id", "policies", ["tenant_id"])
    op.create_index("ix_policies_enabled", "policies", ["enabled"])

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tool_name", sa.String(length=255), nullable=False),
        sa.Column("action_name", sa.String(length=255), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=True),
        sa.Column("status", tool_call_status, nullable=False),
        sa.Column("risk_score", sa.Float(), nullable=False),
        sa.Column("decision_reason", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tool_calls_tenant_id", "tool_calls", ["tenant_id"])
    op.create_index("ix_tool_calls_agent_id", "tool_calls", ["agent_id"])
    op.create_index("ix_tool_calls_status", "tool_calls", ["status"])

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tool_call_id", sa.String(length=36), sa.ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("requested_by_agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_to_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", approval_status, nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("approver_comment", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approval_requests_tenant_id", "approval_requests", ["tenant_id"])
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_type", audit_actor_type, nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("resource_type", sa.String(length=255), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    op.create_table(
        "execution_traces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_intent", sa.String(length=2000), nullable=False),
        sa.Column("status", trace_status, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("summary", sa.String(length=2000), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )
    op.create_index("ix_execution_traces_tenant_id", "execution_traces", ["tenant_id"])
    op.create_index("ix_execution_traces_agent_id", "execution_traces", ["agent_id"])

    op.create_table(
        "trace_steps",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("trace_id", sa.String(length=36), sa.ForeignKey("execution_traces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("type", trace_step_type, nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("trace_id", "step_number", name="uq_trace_steps_trace_step"),
    )
    op.create_index("ix_trace_steps_trace_id", "trace_steps", ["trace_id"])

    op.create_table(
        "agent_api_keys",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(length=36), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("prefix", sa.String(length=64), nullable=False),
        sa.Column("hashed_key", sa.String(length=128), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_api_keys_tenant_id", "agent_api_keys", ["tenant_id"])
    op.create_index("ix_agent_api_keys_prefix", "agent_api_keys", ["prefix"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agent_api_keys_prefix", table_name="agent_api_keys")
    op.drop_index("ix_agent_api_keys_tenant_id", table_name="agent_api_keys")
    op.drop_table("agent_api_keys")
    op.drop_index("ix_trace_steps_trace_id", table_name="trace_steps")
    op.drop_table("trace_steps")
    op.drop_index("ix_execution_traces_agent_id", table_name="execution_traces")
    op.drop_index("ix_execution_traces_tenant_id", table_name="execution_traces")
    op.drop_table("execution_traces")
    op.drop_index("ix_audit_events_created_at", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_approval_requests_status", table_name="approval_requests")
    op.drop_index("ix_approval_requests_tenant_id", table_name="approval_requests")
    op.drop_table("approval_requests")
    op.drop_index("ix_tool_calls_status", table_name="tool_calls")
    op.drop_index("ix_tool_calls_agent_id", table_name="tool_calls")
    op.drop_index("ix_tool_calls_tenant_id", table_name="tool_calls")
    op.drop_table("tool_calls")
    op.drop_index("ix_policies_enabled", table_name="policies")
    op.drop_index("ix_policies_tenant_id", table_name="policies")
    op.drop_table("policies")
    op.drop_index("ix_tools_tenant_id", table_name="tools")
    op.drop_table("tools")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_tenant_id", table_name="agents")
    op.drop_table("agents")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")

    risk_band.drop(op.get_bind(), checkfirst=False)
    trace_step_type.drop(op.get_bind(), checkfirst=False)
    trace_status.drop(op.get_bind(), checkfirst=False)
    audit_actor_type.drop(op.get_bind(), checkfirst=False)
    approval_status.drop(op.get_bind(), checkfirst=False)
    tool_call_status.drop(op.get_bind(), checkfirst=False)
    policy_decision.drop(op.get_bind(), checkfirst=False)
    policy_severity.drop(op.get_bind(), checkfirst=False)
    tool_type.drop(op.get_bind(), checkfirst=False)
    agent_status.drop(op.get_bind(), checkfirst=False)
    agent_environment.drop(op.get_bind(), checkfirst=False)
    user_role.drop(op.get_bind(), checkfirst=False)
