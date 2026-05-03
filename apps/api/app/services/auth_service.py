from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import UserRole
from app.core.errors import AppError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Tenant, User
from app.schemas.auth import BootstrapOwnerRequest, CreateUserRequest, LoginRequest, TokenResponse


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "tenant"


class AuthService:
    def bootstrap_owner(self, db: Session, payload: BootstrapOwnerRequest) -> TokenResponse:
        user_count = db.scalar(select(func.count()).select_from(User)) or 0
        if user_count > 0:
            raise AppError(
                "Bootstrap is only available before the first user is created.",
                status_code=409,
                code="bootstrap_locked",
            )

        tenant = Tenant(
            name=payload.tenant_name,
            slug=slugify(payload.tenant_slug),
            plan=get_settings().default_tenant_plan,
        )
        db.add(tenant)
        db.flush()

        user = User(
            tenant_id=tenant.id,
            email=payload.email.lower(),
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=UserRole.OWNER,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        return TokenResponse(
            access_token=create_access_token(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role.value,
            )
        )

    def login(self, db: Session, payload: LoginRequest) -> TokenResponse:
        query = select(User).where(User.email == payload.email.lower())
        if payload.tenant_slug:
            tenant = db.scalar(select(Tenant).where(Tenant.slug == slugify(payload.tenant_slug)))
            if not tenant:
                raise AppError("Invalid credentials.", status_code=401, code="invalid_credentials")
            query = query.where(User.tenant_id == tenant.id)

        users = list(db.scalars(query))
        if not users:
            raise AppError("Invalid credentials.", status_code=401, code="invalid_credentials")
        if len(users) > 1 and not payload.tenant_slug:
            raise AppError(
                "Multiple tenant memberships found for this email. Provide tenant_slug.",
                status_code=400,
                code="tenant_slug_required",
            )
        user = users[0]
        if not user or not verify_password(payload.password, user.hashed_password):
            raise AppError("Invalid credentials.", status_code=401, code="invalid_credentials")
        if not user.is_active:
            raise AppError("User account is inactive.", status_code=403, code="inactive_user")
        return TokenResponse(
            access_token=create_access_token(
                user_id=user.id,
                tenant_id=user.tenant_id,
                role=user.role.value,
            )
        )

    def create_user(self, db: Session, tenant_id: str, payload: CreateUserRequest) -> User:
        existing = db.scalar(
            select(User).where(User.tenant_id == tenant_id, User.email == payload.email.lower())
        )
        if existing:
            raise AppError("User email already exists in this tenant.", status_code=409, code="duplicate_email")

        user = User(
            tenant_id=tenant_id,
            email=payload.email.lower(),
            full_name=payload.full_name,
            hashed_password=hash_password(payload.password),
            role=payload.role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
