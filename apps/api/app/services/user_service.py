from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditActorType, UserProvisionedSource, UserRole
from app.core.errors import AppError
from app.models import AgentAPIKey, User
from app.models.base import utcnow
from app.core.security import hash_password
from app.schemas.user import UserDeactivationRequest, UserUpdateRequest
from app.services.audit_service import AuditService


class UserService:
    def __init__(self) -> None:
        self.audit_service = AuditService()

    def list_users(self, db: Session, *, tenant_id: str) -> list[User]:
        return list(
            db.scalars(
                select(User)
                .where(User.tenant_id == tenant_id)
                .order_by(User.created_at.asc(), User.email.asc())
            )
        )

    def get_user(self, db: Session, *, tenant_id: str, user_id: str) -> User:
        user = db.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
        if user is None:
            raise AppError("User not found.", status_code=404, code="user_not_found")
        return user

    def update_user(
        self,
        db: Session,
        *,
        actor: User,
        user_id: str,
        payload: UserUpdateRequest,
        ip_address: str | None,
    ) -> User:
        user = self.get_user(db, tenant_id=actor.tenant_id, user_id=user_id)
        self._assert_manage_access(actor=actor, target=user)

        updates = payload.model_dump(exclude_unset=True)
        changed_fields: list[str] = []
        previous_role = user.role

        if "full_name" in updates and updates["full_name"] != user.full_name:
            user.full_name = updates["full_name"]
            changed_fields.append("full_name")

        if "role" in updates and updates["role"] != user.role:
            self._assert_role_change_allowed(actor=actor, target=user, new_role=updates["role"], db=db)
            user.role = updates["role"]
            changed_fields.append("role")

        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=actor.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor.id,
            event_type="user.updated",
            resource_type="user",
            resource_id=user.id,
            metadata={
                "updated_fields": changed_fields or sorted(updates.keys()),
                "previous_role": previous_role.value,
                "current_role": user.role.value,
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(user)
        return user

    def deactivate_user(
        self,
        db: Session,
        *,
        actor: User,
        user_id: str,
        payload: UserDeactivationRequest,
        ip_address: str | None,
    ) -> User:
        user = self.get_user(db, tenant_id=actor.tenant_id, user_id=user_id)
        self._assert_manage_access(actor=actor, target=user)
        if not user.is_active:
            raise AppError("User is already deactivated.", status_code=409, code="user_already_deactivated")
        self._assert_owner_survives(db=db, target=user)

        now = utcnow()
        user.is_active = False
        user.deactivated_at = now
        user.deactivation_reason = payload.reason
        revoked_key_count = self._revoke_user_created_api_keys(db, tenant_id=actor.tenant_id, user_id=user.id, revoked_at=now)

        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=actor.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor.id,
            event_type="user.deactivated",
            resource_type="user",
            resource_id=user.id,
            metadata={
                "deactivation_reason": payload.reason,
                "revoked_agent_api_key_count": revoked_key_count,
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(user)
        return user

    def reactivate_user(
        self,
        db: Session,
        *,
        actor: User,
        user_id: str,
        ip_address: str | None,
    ) -> User:
        user = self.get_user(db, tenant_id=actor.tenant_id, user_id=user_id)
        self._assert_manage_access(actor=actor, target=user)
        if user.is_active:
            raise AppError("User is already active.", status_code=409, code="user_already_active")

        user.is_active = True
        user.deactivated_at = None
        user.deactivation_reason = None

        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=actor.tenant_id,
            actor_type=AuditActorType.USER,
            actor_id=actor.id,
            event_type="user.reactivated",
            resource_type="user",
            resource_id=user.id,
            metadata={},
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(user)
        return user

    def create_scim_user(
        self,
        db: Session,
        *,
        tenant_id: str,
        email: str,
        full_name: str,
        active: bool,
        ip_address: str | None,
    ) -> User:
        normalized_email = email.lower().strip()
        self._assert_unique_email(db=db, tenant_id=tenant_id, email=normalized_email)

        user = User(
            tenant_id=tenant_id,
            email=normalized_email,
            full_name=full_name,
            hashed_password=hash_password(secrets.token_urlsafe(48)),
            role=UserRole.VIEWER,
            is_active=active,
            provisioned_source=UserProvisionedSource.SCIM,
            deactivated_at=None if active else utcnow(),
            deactivation_reason=None if active else "scim_active_false",
        )
        db.add(user)
        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type="scim.user.created",
            resource_type="user",
            resource_id=user.id,
            metadata={
                "created_role": user.role.value,
                "initial_active": active,
                "provisioned_source": user.provisioned_source.value,
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(user)
        return user

    def sync_user_from_scim(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        email: str | None,
        full_name: str | None,
        active: bool | None,
        ip_address: str | None,
    ) -> User:
        user = self.get_user(db, tenant_id=tenant_id, user_id=user_id)
        normalized_email = email.lower().strip() if email is not None else None
        changed_fields: list[str] = []
        revoked_key_count = 0
        event_type: str | None = None

        if normalized_email and normalized_email != user.email:
            self._assert_unique_email(db=db, tenant_id=tenant_id, email=normalized_email, exclude_user_id=user.id)
            user.email = normalized_email
            changed_fields.append("email")

        if full_name is not None and full_name != user.full_name:
            user.full_name = full_name
            changed_fields.append("full_name")

        if active is False and user.is_active:
            self._assert_owner_survives(db=db, target=user)
            now = utcnow()
            user.is_active = False
            user.deactivated_at = now
            user.deactivation_reason = "scim_active_false"
            revoked_key_count = self._revoke_user_created_api_keys(
                db,
                tenant_id=tenant_id,
                user_id=user.id,
                revoked_at=now,
            )
            changed_fields.append("active")
            event_type = "scim.user.deactivated"
        elif active is True and not user.is_active:
            user.is_active = True
            user.deactivated_at = None
            user.deactivation_reason = None
            changed_fields.append("active")
            event_type = "scim.user.reactivated"

        if not changed_fields:
            return user

        if event_type is None:
            event_type = "scim.user.updated"

        db.flush()
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=event_type,
            resource_type="user",
            resource_id=user.id,
            metadata={
                "updated_fields": changed_fields,
                "revoked_agent_api_key_count": revoked_key_count,
            },
            ip_address=ip_address,
        )
        db.commit()
        db.refresh(user)
        return user

    def _assert_manage_access(self, *, actor: User, target: User) -> None:
        if actor.role not in {UserRole.OWNER, UserRole.ADMIN}:
            raise AppError("Insufficient permissions.", status_code=403, code="forbidden")
        if target.role == UserRole.OWNER and actor.role != UserRole.OWNER:
            raise AppError(
                "Only tenant owners can manage another owner account.",
                status_code=403,
                code="owner_management_forbidden",
            )

    def _assert_role_change_allowed(
        self,
        *,
        actor: User,
        target: User,
        new_role: UserRole,
        db: Session,
    ) -> None:
        if new_role == UserRole.OWNER and actor.role != UserRole.OWNER:
            raise AppError(
                "Only tenant owners can promote a user to owner.",
                status_code=403,
                code="owner_promotion_forbidden",
            )
        if target.role == UserRole.OWNER and new_role != UserRole.OWNER:
            self._assert_owner_survives(db=db, target=target)

    def _assert_owner_survives(self, *, db: Session, target: User) -> None:
        if target.role != UserRole.OWNER or not target.is_active:
            return
        other_active_owner = db.scalar(
            select(User.id).where(
                User.tenant_id == target.tenant_id,
                User.role == UserRole.OWNER,
                User.is_active.is_(True),
                User.id != target.id,
            )
        )
        if other_active_owner is None:
            raise AppError(
                "You cannot remove the last active owner from this tenant.",
                status_code=409,
                code="last_active_owner_required",
            )

    def _revoke_user_created_api_keys(
        self,
        db: Session,
        *,
        tenant_id: str,
        user_id: str,
        revoked_at,
    ) -> int:
        api_keys = list(
            db.scalars(
                select(AgentAPIKey).where(
                    AgentAPIKey.tenant_id == tenant_id,
                    AgentAPIKey.created_by_user_id == user_id,
                    AgentAPIKey.revoked_at.is_(None),
                )
            )
        )
        for api_key in api_keys:
            api_key.revoked_at = revoked_at
        return len(api_keys)

    def _assert_unique_email(
        self,
        db: Session,
        *,
        tenant_id: str,
        email: str,
        exclude_user_id: str | None = None,
    ) -> None:
        query = select(User.id).where(User.tenant_id == tenant_id, User.email == email)
        if exclude_user_id:
            query = query.where(User.id != exclude_user_id)
        existing = db.scalar(query)
        if existing is not None:
            raise AppError("User email already exists in this tenant.", status_code=409, code="duplicate_email")
