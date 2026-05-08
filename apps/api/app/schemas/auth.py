from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from app.core.enums import UserRole
from app.schemas.user import UserResponse


class BootstrapOwnerRequest(BaseModel):
    tenant_name: str = Field(min_length=2, max_length=255)
    tenant_slug: str = Field(min_length=2, max_length=255)
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_slug: str | None = None


class TokenResponse(BaseModel):
    access_token: str | None = None
    token_type: str = "bearer"
    session_mode: str = "token"
    csrf_token: str | None = None


class CSRFTokenResponse(BaseModel):
    csrf_token: str | None = None
    header_name: str = "X-CSRF-Token"
    session_mode: str = "token"


class LogoutResponse(BaseModel):
    logged_out: bool = True


class OIDCExchangeRequest(BaseModel):
    ticket: str = Field(min_length=32, max_length=4000)


class OIDCConfigStatusResponse(BaseModel):
    configured: bool
    enabled: bool
    local_auth_enabled: bool = True
    provider_name: str | None = None
    login_url: str | None = None
    reason: str | None = None


class CurrentUserResponse(UserResponse):
    pass


class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str
    password: str = Field(min_length=12, max_length=128)
    role: UserRole
