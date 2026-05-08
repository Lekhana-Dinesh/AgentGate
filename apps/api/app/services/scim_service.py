from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import User
from app.schemas.scim import (
    SCIMEmail,
    SCIMName,
    SCIMUserCreateRequest,
    SCIMUserPatchRequest,
    SCIMUserReplaceRequest,
    SCIMListResponse,
    resolve_scim_email,
    resolve_scim_full_name,
    serialize_scim_user,
)
from app.services.user_service import UserService

_SUPPORTED_FILTER_RE = re.compile(r'^\s*(userName|id)\s+eq\s+"([^"]+)"\s*$', re.IGNORECASE)


@dataclass(slots=True)
class SCIMListResult:
    users: list[User]
    total_results: int
    start_index: int
    items_per_page: int


class SCIMService:
    def __init__(self) -> None:
        self.user_service = UserService()

    def list_users(
        self,
        db: Session,
        *,
        tenant_id: str,
        filter_text: str | None,
        start_index: int,
        count: int,
    ) -> SCIMListResult:
        query = select(User).where(User.tenant_id == tenant_id)
        if filter_text:
            field_name, field_value = self._parse_filter(filter_text)
            if field_name == "username":
                query = query.where(User.email == field_value.lower())
            else:
                query = query.where(User.id == field_value)

        users = list(db.scalars(query.order_by(User.created_at.asc(), User.email.asc())))
        normalized_start = max(1, start_index)
        normalized_count = max(1, count)
        start_offset = normalized_start - 1
        return SCIMListResult(
            users=users[start_offset : start_offset + normalized_count],
            total_results=len(users),
            start_index=normalized_start,
            items_per_page=min(normalized_count, max(0, len(users) - start_offset)),
        )

    def create_user(
        self,
        db: Session,
        *,
        tenant_id: str,
        payload: SCIMUserCreateRequest,
        ip_address: str | None,
    ) -> User:
        self._reject_role_management(payload.roles)
        email = resolve_scim_email(user_name=payload.userName, emails=payload.emails)
        full_name = resolve_scim_full_name(
            user_name=email,
            display_name=payload.displayName,
            name=payload.name,
        )
        return self.user_service.create_scim_user(
            db,
            tenant_id=tenant_id,
            email=email,
            full_name=full_name,
            active=payload.active,
            ip_address=ip_address,
        )

    def replace_user(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        payload: SCIMUserReplaceRequest,
        ip_address: str | None,
    ) -> User:
        self._reject_role_management(payload.roles)
        email = resolve_scim_email(user_name=payload.userName, emails=payload.emails)
        full_name = resolve_scim_full_name(
            user_name=email,
            display_name=payload.displayName,
            name=payload.name,
        )
        return self.user_service.sync_user_from_scim(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            email=email,
            full_name=full_name,
            active=payload.active,
            ip_address=ip_address,
        )

    def patch_user(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        payload: SCIMUserPatchRequest,
        ip_address: str | None,
    ) -> User:
        user = self.user_service.get_user(db, tenant_id=tenant_id, user_id=user_id)
        current_name = self._current_name(user)
        state = {
            "userName": user.email,
            "displayName": user.full_name,
            "active": user.is_active,
            "name": {
                "formatted": current_name.formatted,
                "givenName": current_name.givenName,
                "familyName": current_name.familyName,
            },
        }

        for operation in payload.Operations:
            self._apply_patch_operation(state=state, operation=operation)

        name_value = SCIMName.model_validate(state["name"])
        email = resolve_scim_email(user_name=state["userName"], emails=None)
        full_name = resolve_scim_full_name(
            user_name=email,
            display_name=state["displayName"],
            name=name_value,
        )
        return self.user_service.sync_user_from_scim(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            email=email,
            full_name=full_name,
            active=bool(state["active"]),
            ip_address=ip_address,
        )

    def build_list_response(self, result: SCIMListResult) -> SCIMListResponse:
        return SCIMListResponse(
            totalResults=result.total_results,
            startIndex=result.start_index,
            itemsPerPage=result.items_per_page,
            Resources=[self.serialize_user(user) for user in result.users],
        )

    def serialize_user(self, user: User):
        return serialize_scim_user(
            user,
            location=f"{get_settings().public_api_url}/v1/scim/v2/Users/{user.id}",
        )

    def _parse_filter(self, filter_text: str) -> tuple[str, str]:
        match = _SUPPORTED_FILTER_RE.match(filter_text)
        if not match:
            raise AppError(
                "Only simple userName or id equality filters are supported.",
                status_code=400,
                code="scim_filter_unsupported",
            )
        field_name = match.group(1).strip().lower()
        field_value = match.group(2).strip()
        return field_name, field_value

    def _reject_role_management(self, roles) -> None:
        if roles:
            raise AppError(
                "SCIM role management is not supported in this build.",
                status_code=400,
                code="scim_role_management_unsupported",
            )

    def _current_name(self, user: User) -> SCIMName:
        serialized = self.serialize_user(user)
        return serialized.name

    def _apply_patch_operation(self, *, state: dict[str, object], operation) -> None:
        path = str(operation.path or "").strip()
        if path.lower().startswith("roles"):
            raise AppError(
                "SCIM role management is not supported in this build.",
                status_code=400,
                code="scim_role_management_unsupported",
            )
        if path:
            self._apply_patch_path(state=state, op=operation.op, path=path, value=operation.value)
            return

        if not isinstance(operation.value, dict):
            raise AppError(
                "SCIM patch requests without a path must provide an object value.",
                status_code=400,
                code="scim_patch_invalid",
            )
        if operation.value.get("roles"):
            self._reject_role_management(operation.value.get("roles"))
        for key, value in operation.value.items():
            self._apply_patch_path(state=state, op=operation.op, path=key, value=value)

    def _apply_patch_path(self, *, state: dict[str, object], op: str, path: str, value) -> None:
        normalized_path = path.strip()
        lowered_path = normalized_path.lower()
        if lowered_path == "username":
            if op == "remove":
                raise AppError("SCIM userName cannot be removed.", status_code=400, code="scim_patch_invalid")
            state["userName"] = self._normalize_email(str(value or "").strip())
            return
        if lowered_path == "displayname":
            state["displayName"] = None if op == "remove" else str(value or "").strip() or None
            return
        if lowered_path == "active":
            if op == "remove":
                raise AppError("SCIM active cannot be removed.", status_code=400, code="scim_patch_invalid")
            if not isinstance(value, bool):
                raise AppError("SCIM active must be a boolean.", status_code=400, code="scim_patch_invalid")
            state["active"] = value
            return
        if lowered_path == "name":
            if op == "remove":
                state["name"] = {"formatted": None, "givenName": None, "familyName": None}
                return
            if not isinstance(value, dict):
                raise AppError("SCIM name must be an object.", status_code=400, code="scim_patch_invalid")
            current_name = dict(state["name"])
            current_name.update(value)
            state["name"] = current_name
            return
        if lowered_path in {"name.formatted", "name.givenname", "name.familyname"}:
            field_name = {
                "name.formatted": "formatted",
                "name.givenname": "givenName",
                "name.familyname": "familyName",
            }[lowered_path]
            current_name = dict(state["name"])
            current_name[field_name] = None if op == "remove" else str(value or "").strip() or None
            state["name"] = current_name
            return
        if lowered_path == "emails":
            if op == "remove":
                raise AppError("SCIM emails cannot be removed.", status_code=400, code="scim_patch_invalid")
            if not isinstance(value, list):
                raise AppError("SCIM emails must be a list.", status_code=400, code="scim_patch_invalid")
            emails = [SCIMEmail.model_validate(item) for item in value]
            state["userName"] = resolve_scim_email(user_name=str(state["userName"]), emails=emails)
            return
        raise AppError(
            "The requested SCIM patch path is not supported in this build.",
            status_code=400,
            code="scim_patch_unsupported",
        )

    def _normalize_email(self, value: str) -> str:
        return SCIMEmail(value=value).value.lower()
