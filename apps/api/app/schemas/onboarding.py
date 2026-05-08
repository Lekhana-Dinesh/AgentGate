from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OnboardingChecklistItemResponse(BaseModel):
    key: Literal[
        "active_owner",
        "agent",
        "tool",
        "policy",
        "approval_workflow",
        "audit_integrity",
        "settings",
    ]
    label: str
    description: str
    complete: bool
    href: str


class OnboardingLinkResponse(BaseModel):
    label: str
    href: str
    description: str


class OnboardingStatusResponse(BaseModel):
    tenant_id: str
    tenant_exists: bool
    active_owner_exists: bool
    agent_count: int
    tool_count: int
    policy_count: int
    has_agent: bool
    has_tool: bool
    has_policy: bool
    approval_workflow_available: bool
    audit_integrity_configured: bool
    audit_integrity_status: Literal["empty", "legacy_only", "anchored", "anchored_with_legacy"]
    settings_overview_available: bool
    dismissed: bool
    recommended_next_step: str
    recommended_next_step_href: str
    checklist: list[OnboardingChecklistItemResponse] = Field(default_factory=list)
    links: list[OnboardingLinkResponse] = Field(default_factory=list)


class OnboardingActionResponse(BaseModel):
    ok: bool = True
    action: Literal["dismiss", "reset", "create_demo_policy"]
    message: str
    dismissed: bool | None = None
    created: bool | None = None
    policy_id: str | None = None
