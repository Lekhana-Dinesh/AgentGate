from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    SECURITY_REVIEWER = "security_reviewer"
    DEVELOPER = "developer"
    APPROVER = "approver"
    VIEWER = "viewer"


class AgentEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class AgentStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ToolType(StrEnum):
    MCP = "mcp"
    REST = "rest"
    MOCK = "mock"
    DATABASE = "database"
    EMAIL = "email"
    CRM = "crm"
    GITHUB = "github"
    CUSTOM = "custom"


class PolicySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"
    REDACT = "redact"


class ToolCallStatus(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"
    EXECUTED = "executed"
    FAILED = "failed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class PayloadRetentionClass(StrEnum):
    STANDARD = "standard"
    SHORT_LIVED = "short_lived"
    EXTENDED = "extended"
    LEGAL_HOLD = "legal_hold"


class AuditEventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditExportDestinationType(StrEnum):
    WEBHOOK = "webhook"
    SPLUNK_HEC = "splunk_hec"
    DATADOG = "datadog"
    HTTP_JSON = "http_json"
    CUSTOM_PLACEHOLDER = "custom_placeholder"


class JobType(StrEnum):
    APPROVAL_NOTIFICATION_SLACK = "approval_notification.slack"
    APPROVAL_EXECUTION_TOOL_CALL = "approval_execution.tool_call"
    AUDIT_EXPORT_PLACEHOLDER = "audit_export.placeholder"
    RETENTION_PURGE_PLACEHOLDER = "retention_purge.placeholder"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRY_EXHAUSTED = "retry_exhausted"
    CANCELLED = "cancelled"


class AuditActorType(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"


class TraceStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PENDING_APPROVAL = "pending_approval"


class TraceStepType(StrEnum):
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    POLICY_DECISION = "policy_decision"
    APPROVAL = "approval"
    FINAL = "final"
    ERROR = "error"


class RiskBand(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
