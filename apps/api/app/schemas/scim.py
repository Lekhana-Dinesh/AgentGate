from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import User

SCIM_CORE_USER_SCHEMA = "urn:ietf:params:scim:schemas:core:2.0:User"
SCIM_LIST_RESPONSE_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
SCIM_PATCH_OP_SCHEMA = "urn:ietf:params:scim:api:messages:2.0:PatchOp"


class SCIMName(BaseModel):
    model_config = ConfigDict(extra="ignore")

    formatted: str | None = Field(default=None, min_length=1, max_length=255)
    givenName: str | None = Field(default=None, min_length=1, max_length=255)
    familyName: str | None = Field(default=None, min_length=1, max_length=255)


class SCIMEmail(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str = Field(min_length=3, max_length=320)
    primary: bool | None = None
    type: str | None = Field(default="work", max_length=50)

    @field_validator("value", mode="before")
    @classmethod
    def normalize_value(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized or "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("SCIM email values must contain a non-empty local part and domain.")
        return normalized


class SCIMRoleValue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str | None = Field(default=None, max_length=255)


class SCIMUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemas: list[str] = Field(default_factory=lambda: [SCIM_CORE_USER_SCHEMA])
    userName: str = Field(min_length=3, max_length=320)
    active: bool = True
    displayName: str | None = Field(default=None, min_length=1, max_length=255)
    externalId: str | None = Field(default=None, max_length=255)
    name: SCIMName | None = None
    emails: list[SCIMEmail] | None = None
    roles: list[SCIMRoleValue] | None = None

    @field_validator("userName", mode="before")
    @classmethod
    def normalize_user_name(cls, value: str) -> str:
        return SCIMEmail(value=value).value


class SCIMUserReplaceRequest(SCIMUserCreateRequest):
    pass


class SCIMPatchOperation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    op: str
    path: str | None = Field(default=None, max_length=255)
    value: Any = None

    @field_validator("op", mode="before")
    @classmethod
    def normalize_op(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"add", "replace", "remove"}:
            raise ValueError("Unsupported SCIM patch operation.")
        return normalized


class SCIMUserPatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schemas: list[str] = Field(default_factory=lambda: [SCIM_PATCH_OP_SCHEMA])
    Operations: list[SCIMPatchOperation] = Field(default_factory=list, min_length=1)


class SCIMMeta(BaseModel):
    resourceType: str = "User"
    created: datetime
    lastModified: datetime
    location: str


class SCIMUserResponse(BaseModel):
    schemas: list[str] = Field(default_factory=lambda: [SCIM_CORE_USER_SCHEMA])
    id: str
    externalId: str | None = None
    userName: str
    name: SCIMName
    displayName: str
    active: bool
    emails: list[SCIMEmail]
    meta: SCIMMeta


class SCIMListResponse(BaseModel):
    schemas: list[str] = Field(default_factory=lambda: [SCIM_LIST_RESPONSE_SCHEMA])
    totalResults: int
    startIndex: int
    itemsPerPage: int
    Resources: list[SCIMUserResponse]


def resolve_scim_full_name(
    *,
    user_name: str,
    display_name: str | None,
    name: SCIMName | None,
) -> str:
    if name and name.formatted:
        return name.formatted.strip()
    if name:
        combined = " ".join(part.strip() for part in [name.givenName or "", name.familyName or ""] if part.strip())
        if combined:
            return combined
    if display_name and display_name.strip():
        return display_name.strip()
    return str(user_name).strip()


def resolve_scim_email(*, user_name: str, emails: list[SCIMEmail] | None) -> str:
    if emails:
        primary = next((item for item in emails if item.primary), None)
        if primary is not None:
            return primary.value.lower()
        return emails[0].value.lower()
    return str(user_name).strip().lower()


def serialize_scim_user(user: User, *, location: str) -> SCIMUserResponse:
    given_name, family_name = _split_name(user.full_name)
    return SCIMUserResponse(
        id=user.id,
        userName=user.email,
        name=SCIMName(
            formatted=user.full_name,
            givenName=given_name,
            familyName=family_name,
        ),
        displayName=user.full_name,
        active=user.is_active,
        emails=[SCIMEmail(value=user.email, primary=True, type="work")],
        meta=SCIMMeta(
            created=user.created_at,
            lastModified=user.updated_at,
            location=location,
        ),
    )


def _split_name(full_name: str) -> tuple[str | None, str | None]:
    normalized = str(full_name or "").strip()
    if not normalized:
        return None, None
    parts = normalized.split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])
