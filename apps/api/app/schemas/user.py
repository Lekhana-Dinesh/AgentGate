from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import UserProvisionedSource, UserRole
from app.schemas.common import ORMModel


class UserResponse(ORMModel):
    id: str
    tenant_id: str
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    status: str
    provisioned_source: UserProvisionedSource
    deactivated_at: datetime | None
    deactivation_reason: str | None
    created_at: datetime
    updated_at: datetime


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    role: UserRole | None = None

    @model_validator(mode="after")
    def validate_updates_present(self) -> "UserUpdateRequest":
        if self.full_name is None and self.role is None:
            raise ValueError("At least one safe user field must be provided.")
        return self


class UserDeactivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, min_length=3, max_length=500)
