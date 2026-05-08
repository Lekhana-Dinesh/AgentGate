from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_scim_principal
from app.db.session import get_db
from app.schemas.scim import (
    SCIMListResponse,
    SCIMUserCreateRequest,
    SCIMUserPatchRequest,
    SCIMUserReplaceRequest,
    SCIMUserResponse,
)
from app.services.scim_service import SCIMService

router = APIRouter()
scim_service = SCIMService()


@router.get("/Users", response_model=SCIMListResponse)
def list_users(
    filter: str | None = Query(default=None),
    startIndex: int = Query(default=1, ge=1),
    count: int = Query(default=100, ge=1, le=500),
    principal=Depends(get_scim_principal),
    db: Session = Depends(get_db),
) -> SCIMListResponse:
    result = scim_service.list_users(
        db,
        tenant_id=principal.tenant_id,
        filter_text=filter,
        start_index=startIndex,
        count=count,
    )
    return scim_service.build_list_response(result)


@router.get("/Users/{user_id}", response_model=SCIMUserResponse)
def get_user(
    user_id: str,
    principal=Depends(get_scim_principal),
    db: Session = Depends(get_db),
) -> SCIMUserResponse:
    user = scim_service.user_service.get_user(db, tenant_id=principal.tenant_id, user_id=user_id)
    return scim_service.serialize_user(user)


@router.post("/Users", response_model=SCIMUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: SCIMUserCreateRequest,
    request: Request,
    principal=Depends(get_scim_principal),
    db: Session = Depends(get_db),
) -> SCIMUserResponse:
    user = scim_service.create_user(
        db,
        tenant_id=principal.tenant_id,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    return scim_service.serialize_user(user)


@router.put("/Users/{user_id}", response_model=SCIMUserResponse)
def replace_user(
    user_id: str,
    payload: SCIMUserReplaceRequest,
    request: Request,
    principal=Depends(get_scim_principal),
    db: Session = Depends(get_db),
) -> SCIMUserResponse:
    user = scim_service.replace_user(
        db,
        tenant_id=principal.tenant_id,
        user_id=user_id,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    return scim_service.serialize_user(user)


@router.patch("/Users/{user_id}", response_model=SCIMUserResponse)
def patch_user(
    user_id: str,
    payload: SCIMUserPatchRequest,
    request: Request,
    principal=Depends(get_scim_principal),
    db: Session = Depends(get_db),
) -> SCIMUserResponse:
    user = scim_service.patch_user(
        db,
        tenant_id=principal.tenant_id,
        user_id=user_id,
        payload=payload,
        ip_address=request.client.host if request.client else None,
    )
    return scim_service.serialize_user(user)
