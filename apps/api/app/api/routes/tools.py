from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.enums import AuditActorType, UserRole
from app.core.errors import AppError
from app.db.session import get_db
from app.models import Tool
from app.schemas.tool import (
    ToolCreate,
    ToolHealthResponse,
    ToolResponse,
    ToolSafeDetailResponse,
    ToolSafeMetadataCreate,
    ToolSafeMetadataUpdate,
    ToolSafeSummaryResponse,
    ToolUpdate,
)
from app.services.audit_service import AuditService
from app.services.tool_health_service import ToolHealthService
from app.services.tool_summary_service import ToolSummaryService
from app.tools.config_validation import (
    build_safe_tool_configuration,
    validate_browser_safe_tool_fields,
    validate_tool_configuration,
)

router = APIRouter()
audit_service = AuditService()
tool_health_service = ToolHealthService()
tool_summary_service = ToolSummaryService()


@router.get("/summary", response_model=list[ToolSafeSummaryResponse])
def list_tool_summaries(
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER)),
    db: Session = Depends(get_db),
) -> list[ToolSafeSummaryResponse]:
    return tool_summary_service.list_summaries(db, tenant_id=current_user.tenant_id)


@router.get("", response_model=list[ToolResponse])
def list_tools(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ToolResponse]:
    tools = list(
        db.scalars(
            select(Tool)
            .where(Tool.tenant_id == current_user.tenant_id)
            .order_by(Tool.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return [ToolResponse.model_validate(item) for item in tools]


@router.post("", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
def create_tool(
    payload: ToolCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> ToolResponse:
    base_url, config = validate_tool_configuration(
        payload.type,
        base_url=payload.base_url,
        config=payload.config,
    )
    tool = Tool(
        tenant_id=current_user.tenant_id,
        **payload.model_dump(exclude={"base_url", "config"}),
        base_url=base_url,
        config=config,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="tool.created",
        resource_type="tool",
        resource_id=tool.id,
        metadata={"tool_type": tool.type.value, "enabled": tool.enabled},
    )
    db.commit()
    return ToolResponse.model_validate(tool)


@router.post("/safe-metadata", response_model=ToolSafeDetailResponse, status_code=status.HTTP_201_CREATED)
def create_tool_safe_metadata(
    payload: ToolSafeMetadataCreate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ToolSafeDetailResponse:
    validate_browser_safe_tool_fields(payload.model_extra)
    metadata = payload.model_dump()
    base_url, config = build_safe_tool_configuration(
        payload.type,
        existing_base_url=None,
        existing_config=None,
        metadata=metadata,
    )
    tool = Tool(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        type=payload.type,
        description=payload.description,
        risk_level=payload.risk_level,
        enabled=payload.enabled,
        base_url=base_url,
        config=config,
    )
    db.add(tool)
    db.commit()
    db.refresh(tool)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="tool.created",
        resource_type="tool",
        resource_id=tool.id,
        metadata={"tool_type": tool.type.value, "enabled": tool.enabled, "mode": "safe_metadata"},
    )
    db.commit()
    return tool_summary_service.get_detail(db, tenant_id=current_user.tenant_id, tool_id=tool.id)


@router.get("/{tool_id}", response_model=ToolResponse)
def get_tool(tool_id: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)) -> ToolResponse:
    tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == current_user.tenant_id))
    if not tool:
        raise AppError("Tool not found.", status_code=404, code="tool_not_found")
    return ToolResponse.model_validate(tool)


@router.get("/{tool_id}/safe-detail", response_model=ToolSafeDetailResponse)
def get_tool_safe_detail(
    tool_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER)),
    db: Session = Depends(get_db),
) -> ToolSafeDetailResponse:
    return tool_summary_service.get_detail(db, tenant_id=current_user.tenant_id, tool_id=tool_id)


@router.get("/{tool_id}/health", response_model=ToolHealthResponse)
def get_tool_health(
    tool_id: str,
    probe: bool = Query(default=False),
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.SECURITY_REVIEWER, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> ToolHealthResponse:
    tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == current_user.tenant_id))
    if not tool:
        raise AppError("Tool not found.", status_code=404, code="tool_not_found")
    return tool_health_service.check(tool=tool, probe=probe)


@router.post("/{tool_id}/probe-health", response_model=ToolSafeSummaryResponse)
def probe_tool_health(
    tool_id: str,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ToolSafeSummaryResponse:
    return tool_summary_service.get_summary(
        db,
        tenant_id=current_user.tenant_id,
        tool_id=tool_id,
        probe=True,
    )


@router.put("/{tool_id}", response_model=ToolResponse)
def update_tool(
    tool_id: str,
    payload: ToolUpdate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN, UserRole.DEVELOPER)),
    db: Session = Depends(get_db),
) -> ToolResponse:
    tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == current_user.tenant_id))
    if not tool:
        raise AppError("Tool not found.", status_code=404, code="tool_not_found")
    updates = payload.model_dump(exclude_unset=True)
    effective_base_url = updates.get("base_url", tool.base_url)
    effective_config = updates.get("config", tool.config)
    base_url, config = validate_tool_configuration(
        tool.type,
        base_url=effective_base_url,
        config=effective_config,
    )
    if "base_url" in updates:
        updates["base_url"] = base_url
    if "config" in updates:
        updates["config"] = config
    for key, value in updates.items():
        setattr(tool, key, value)
    db.commit()
    db.refresh(tool)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="tool.updated",
        resource_type="tool",
        resource_id=tool.id,
        metadata={"updated_fields": sorted(updates.keys())},
    )
    db.commit()
    return ToolResponse.model_validate(tool)


@router.patch("/{tool_id}/safe-metadata", response_model=ToolSafeDetailResponse)
def update_tool_safe_metadata(
    tool_id: str,
    payload: ToolSafeMetadataUpdate,
    current_user=Depends(require_roles(UserRole.OWNER, UserRole.ADMIN)),
    db: Session = Depends(get_db),
) -> ToolSafeDetailResponse:
    validate_browser_safe_tool_fields(payload.model_extra)
    tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == current_user.tenant_id))
    if not tool:
        raise AppError("Tool not found.", status_code=404, code="tool_not_found")

    updates = payload.model_dump(exclude_unset=True)
    base_url, config = build_safe_tool_configuration(
        tool.type,
        existing_base_url=tool.base_url,
        existing_config=tool.config or {},
        metadata=updates,
    )

    updated_fields: list[str] = []
    for field in ("name", "description", "risk_level", "enabled"):
        if field in updates:
            setattr(tool, field, updates[field])
            updated_fields.append(field)

    if tool.base_url != base_url:
        tool.base_url = base_url
        updated_fields.append("base_url")
    if tool.config != config:
        tool.config = config
        updated_fields.append("config")

    db.commit()
    db.refresh(tool)
    audit_service.create_event(
        db,
        tenant_id=current_user.tenant_id,
        actor_type=AuditActorType.USER,
        actor_id=current_user.id,
        event_type="tool.updated",
        resource_type="tool",
        resource_id=tool.id,
        metadata={
            "updated_fields": sorted(set(updated_fields)),
            "mode": "safe_metadata",
        },
    )
    db.commit()
    return tool_summary_service.get_detail(db, tenant_id=current_user.tenant_id, tool_id=tool.id)
