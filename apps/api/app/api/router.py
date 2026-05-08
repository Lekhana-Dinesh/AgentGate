from fastapi import APIRouter

from app.api.routes import (
    agents,
    approvals,
    audit,
    audit_integrity,
    audit_exports,
    auth,
    dashboard,
    demo,
    gateway,
    health,
    integrations,
    jobs,
    metrics,
    onboarding,
    policies,
    retention,
    scim,
    scheduled_tasks,
    security,
    settings,
    tools,
    traces,
    users,
    workers,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(metrics.router, tags=["metrics"])
api_router.include_router(auth.router, prefix="/v1/auth", tags=["auth"])
api_router.include_router(dashboard.router, prefix="/v1/dashboard", tags=["dashboard"])
api_router.include_router(onboarding.router, prefix="/v1/onboarding", tags=["onboarding"])
api_router.include_router(agents.router, prefix="/v1/agents", tags=["agents"])
api_router.include_router(tools.router, prefix="/v1/tools", tags=["tools"])
api_router.include_router(policies.router, prefix="/v1/policies", tags=["policies"])
api_router.include_router(gateway.router, prefix="/v1/gateway", tags=["gateway"])
api_router.include_router(approvals.router, prefix="/v1/approvals", tags=["approvals"])
api_router.include_router(audit_integrity.router, prefix="/v1/audit-integrity", tags=["audit-integrity"])
api_router.include_router(audit_exports.router, prefix="/v1/audit-exports", tags=["audit-exports"])
api_router.include_router(jobs.router, prefix="/v1/jobs", tags=["jobs"])
api_router.include_router(workers.router, prefix="/v1/workers", tags=["workers"])
api_router.include_router(retention.router, prefix="/v1/retention", tags=["retention"])
api_router.include_router(scim.router, prefix="/v1/scim/v2", tags=["scim"])
api_router.include_router(scheduled_tasks.router, prefix="/v1/scheduled-tasks", tags=["scheduled-tasks"])
api_router.include_router(security.router, prefix="/v1/security", tags=["security"])
api_router.include_router(settings.router, prefix="/v1/settings", tags=["settings"])
api_router.include_router(users.router, prefix="/v1/users", tags=["users"])
api_router.include_router(traces.router, prefix="/v1/traces", tags=["traces"])
api_router.include_router(audit.router, prefix="/v1/audit", tags=["audit"])
api_router.include_router(integrations.router, prefix="/v1/integrations", tags=["integrations"])
api_router.include_router(demo.router, prefix="/v1/demo", tags=["demo"])
