from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from typing import Callable
from urllib.parse import quote, urlencode, urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AuditActorType, UserProvisionedSource, UserRole
from app.core.errors import AppError
from app.core.metrics import get_metrics_registry
from app.core.security import (
    create_access_token,
    create_oidc_exchange_ticket,
    create_oidc_state_token,
    decode_oidc_exchange_ticket,
    decode_oidc_state_token,
    hash_password,
)
from app.models import Tenant, TenantOIDCConfig, User
from app.schemas.auth import OIDCConfigStatusResponse
from app.services.audit_service import AuditService
from app.services.auth_service import slugify
from app.services.oidc_provider import (
    DiscoveryOIDCProviderClient,
    OIDCIdentity,
    OIDCProviderClient,
    resolve_oidc_client_secret,
)

OIDC_SUCCESS_EVENT = "auth.oidc.login.success"
OIDC_FAILURE_EVENT = "auth.oidc.login.failed"
OIDC_STATE_COOKIE = "agentgate_oidc_state"


@dataclass(slots=True)
class OIDCLoginInitiation:
    authorization_url: str
    state_token: str


@dataclass(slots=True)
class OIDCCompletion:
    exchange_ticket: str
    tenant_slug: str


@dataclass(slots=True)
class RoleResolution:
    role: UserRole
    explicit_match: bool


class OIDCService:
    def __init__(
        self,
        *,
        provider_factory: Callable[[TenantOIDCConfig], OIDCProviderClient] | None = None,
    ) -> None:
        self.audit_service = AuditService()
        self._provider_factory = provider_factory or (lambda _: DiscoveryOIDCProviderClient())
        self.metrics = get_metrics_registry()

    def get_config_status(self, db: Session, *, tenant_slug: str) -> OIDCConfigStatusResponse:
        tenant = self._get_tenant(db, tenant_slug=tenant_slug, required=False)
        if not tenant:
            return OIDCConfigStatusResponse(configured=False, enabled=False, local_auth_enabled=True)
        config = self._get_enabled_config(db, tenant_id=tenant.id)
        if not config:
            return OIDCConfigStatusResponse(configured=False, enabled=False, local_auth_enabled=True)
        try:
            self._validate_redirect_uri(config, tenant.slug)
            self._validate_secret_configuration(config)
        except AppError:
            return OIDCConfigStatusResponse(
                configured=False,
                enabled=bool(config.enabled),
                local_auth_enabled=True,
                provider_name=config.provider_name,
                reason="misconfigured",
            )
        return OIDCConfigStatusResponse(
            configured=True,
            enabled=bool(config.enabled),
            local_auth_enabled=True,
            provider_name=config.provider_name,
            login_url=f"{get_settings().public_api_url}/v1/auth/oidc/{tenant.slug}/login",
        )

    def initiate_login(self, db: Session, *, tenant_slug: str) -> OIDCLoginInitiation:
        tenant = self._get_tenant(db, tenant_slug=tenant_slug, required=True)
        config = self._get_enabled_config_or_raise(db, tenant_id=tenant.id)
        self._validate_redirect_uri(config, tenant.slug)
        self._validate_secret_configuration(config)
        nonce = secrets.token_urlsafe(24)
        state_token = create_oidc_state_token(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            config_id=config.id,
            nonce=nonce,
        )
        authorization_url = self._resolve_provider(config).get_authorization_url(
            config,
            state=state_token,
            nonce=nonce,
        )
        return OIDCLoginInitiation(authorization_url=authorization_url, state_token=state_token)

    def handle_callback(
        self,
        db: Session,
        *,
        tenant_slug: str,
        state_token: str | None,
        state_cookie: str | None,
        code: str | None,
        ip_address: str | None,
    ) -> OIDCCompletion:
        tenant = self._get_tenant(db, tenant_slug=tenant_slug, required=True)
        config = self._get_enabled_config_or_raise(db, tenant_id=tenant.id)
        self._validate_redirect_uri(config, tenant.slug)

        if not state_token or not state_cookie or not hmac.compare_digest(state_token, state_cookie):
            self._audit_failure(
                db,
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                provider_name=config.provider_name,
                reason="invalid_state",
                ip_address=ip_address,
            )
            raise AppError("OIDC state validation failed.", status_code=401, code="oidc_invalid_state")
        state_payload = decode_oidc_state_token(state_token)
        if state_payload.tenant_slug != tenant.slug or state_payload.tenant_id != tenant.id or state_payload.config_id != config.id:
            self._audit_failure(
                db,
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                provider_name=config.provider_name,
                reason="cross_tenant_state_mismatch",
                ip_address=ip_address,
            )
            raise AppError("OIDC state validation failed.", status_code=401, code="oidc_invalid_state")
        if not code:
            self._audit_failure(
                db,
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                provider_name=config.provider_name,
                reason="missing_code",
                ip_address=ip_address,
            )
            raise AppError("OIDC callback did not include an authorization code.", status_code=400, code="oidc_missing_code")

        try:
            identity = self._resolve_provider(config).exchange_code_for_identity(
                config,
                code=code,
                expected_nonce=state_payload.nonce,
            )
            self._validate_allowed_email_domain(config, identity)
            user = self._provision_user(db, tenant=tenant, config=config, identity=identity)
        except AppError as exc:
            self._audit_failure(
                db,
                tenant_id=tenant.id,
                tenant_slug=tenant.slug,
                provider_name=config.provider_name,
                reason=exc.code,
                ip_address=ip_address,
            )
            raise

        ticket = create_oidc_exchange_ticket(
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role.value,
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant.id,
            actor_type=AuditActorType.USER,
            actor_id=user.id,
            event_type=OIDC_SUCCESS_EVENT,
            resource_type="user",
            resource_id=user.id,
            metadata={
                "provider_name": config.provider_name,
                "tenant_slug": tenant.slug,
                "email": user.email,
                "role": user.role.value,
            },
            ip_address=ip_address,
        )
        self.metrics.increment("agentgate_oidc_logins_total", result="success")
        db.commit()
        return OIDCCompletion(exchange_ticket=ticket, tenant_slug=tenant.slug)

    def exchange_ticket(self, db: Session, *, ticket: str):
        payload = decode_oidc_exchange_ticket(ticket)
        user = db.scalar(
            select(User).where(User.id == payload.sub, User.tenant_id == payload.tenant_id)
        )
        if not user or not user.is_active:
            raise AppError(
                "OIDC login exchange could not be completed.",
                status_code=401,
                code="oidc_exchange_user_invalid",
            )
        return create_access_token(user_id=user.id, tenant_id=user.tenant_id, role=user.role.value)

    def _get_tenant(self, db: Session, *, tenant_slug: str, required: bool) -> Tenant | None:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == slugify(tenant_slug)))
        if required and not tenant:
            raise AppError("SSO is not configured for this tenant.", status_code=404, code="oidc_tenant_not_found")
        return tenant

    def _get_enabled_config(self, db: Session, *, tenant_id: str) -> TenantOIDCConfig | None:
        return db.scalar(
            select(TenantOIDCConfig)
            .where(
                TenantOIDCConfig.tenant_id == tenant_id,
                TenantOIDCConfig.enabled.is_(True),
            )
            .order_by(TenantOIDCConfig.created_at.asc())
            .limit(1)
        )

    def _get_enabled_config_or_raise(self, db: Session, *, tenant_id: str) -> TenantOIDCConfig:
        config = self._get_enabled_config(db, tenant_id=tenant_id)
        if not config:
            raise AppError(
                "SSO is not enabled for this tenant.",
                status_code=404,
                code="oidc_provider_disabled",
            )
        return config

    def _validate_redirect_uri(self, config: TenantOIDCConfig, tenant_slug: str) -> None:
        expected = f"{get_settings().public_api_url}/v1/auth/oidc/{tenant_slug}/callback"
        if config.redirect_uri.rstrip("/") != expected.rstrip("/"):
            raise AppError(
                "OIDC redirect URI is not valid for this deployment.",
                status_code=503,
                code="oidc_redirect_invalid",
            )
        parsed = urlparse(config.redirect_uri)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AppError(
                "OIDC redirect URI is not valid for this deployment.",
                status_code=503,
                code="oidc_redirect_invalid",
            )

    def _resolve_provider(self, config: TenantOIDCConfig) -> OIDCProviderClient:
        return self._provider_factory(config)

    def _validate_secret_configuration(self, config: TenantOIDCConfig) -> None:
        resolve_oidc_client_secret(config)

    def _validate_allowed_email_domain(self, config: TenantOIDCConfig, identity: OIDCIdentity) -> None:
        allowed = [str(item).strip().lower() for item in (config.allowed_email_domains or []) if str(item).strip()]
        if not allowed:
            return
        if "@" not in identity.email:
            raise AppError("OIDC identity email is invalid.", status_code=401, code="oidc_email_invalid")
        domain = identity.email.split("@", 1)[1].lower()
        if domain not in allowed:
            raise AppError(
                "OIDC email domain is not allowed for this tenant.",
                status_code=403,
                code="oidc_email_domain_forbidden",
            )

    def _provision_user(
        self,
        db: Session,
        *,
        tenant: Tenant,
        config: TenantOIDCConfig,
        identity: OIDCIdentity,
    ) -> User:
        existing = db.scalar(
            select(User).where(
                User.tenant_id == tenant.id,
                User.auth_provider == config.provider_name,
                User.external_subject == identity.subject,
            )
        )
        if not existing:
            existing = db.scalar(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.email == identity.email,
                )
            )
        if existing and not existing.is_active:
            raise AppError("User account is inactive.", status_code=403, code="inactive_user")
        if existing and existing.auth_provider and existing.auth_provider != config.provider_name:
            raise AppError(
                "OIDC identity conflicts with an existing user binding.",
                status_code=409,
                code="oidc_identity_conflict",
            )
        if existing and existing.external_subject and existing.external_subject != identity.subject:
            raise AppError(
                "OIDC identity conflicts with an existing user binding.",
                status_code=409,
                code="oidc_identity_conflict",
            )

        role_resolution = self._resolve_role(config.role_mapping or {}, identity)
        if existing:
            existing.email = identity.email
            existing.full_name = identity.full_name
            existing.auth_provider = config.provider_name
            existing.external_subject = identity.subject
            existing.provisioned_source = UserProvisionedSource.OIDC
            if role_resolution.explicit_match:
                existing.role = role_resolution.role
            db.flush()
            return existing

        user = User(
            tenant_id=tenant.id,
            email=identity.email,
            full_name=identity.full_name,
            hashed_password=hash_password(secrets.token_urlsafe(48)),
            auth_provider=config.provider_name,
            external_subject=identity.subject,
            role=role_resolution.role,
            is_active=True,
            provisioned_source=UserProvisionedSource.OIDC,
        )
        db.add(user)
        db.flush()
        return user

    def _resolve_role(self, role_mapping: dict, identity: OIDCIdentity) -> RoleResolution:
        groups_map = role_mapping.get("groups") or {}
        if isinstance(groups_map, dict):
            normalized_group_map = {
                str(key).strip().lower(): self._coerce_role(value)
                for key, value in groups_map.items()
                if str(key).strip()
            }
            for group in identity.groups:
                mapped_role = normalized_group_map.get(group.strip().lower())
                if mapped_role:
                    return RoleResolution(role=mapped_role, explicit_match=True)

        claims_map = role_mapping.get("claims") or {}
        if isinstance(claims_map, dict):
            for claim_name, mapping in claims_map.items():
                if not isinstance(mapping, dict):
                    continue
                claim_value = identity.claims.get(claim_name)
                values = claim_value if isinstance(claim_value, list) else [claim_value]
                normalized = {
                    str(key).strip().lower(): self._coerce_role(value)
                    for key, value in mapping.items()
                    if str(key).strip()
                }
                for value in values:
                    mapped_role = normalized.get(str(value).strip().lower())
                    if mapped_role:
                        return RoleResolution(role=mapped_role, explicit_match=True)

        default_role = self._coerce_role(role_mapping.get("default_role") or UserRole.VIEWER.value)
        return RoleResolution(role=default_role, explicit_match=False)

    def _coerce_role(self, value: str | UserRole) -> UserRole:
        try:
            return value if isinstance(value, UserRole) else UserRole(str(value))
        except ValueError as exc:
            raise AppError(
                "OIDC role mapping contains an unsupported AgentGate role.",
                status_code=500,
                code="oidc_role_mapping_invalid",
            ) from exc

    def _audit_failure(
        self,
        db: Session,
        *,
        tenant_id: str,
        tenant_slug: str,
        provider_name: str,
        reason: str,
        ip_address: str | None,
    ) -> None:
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=OIDC_FAILURE_EVENT,
            resource_type="tenant",
            resource_id=tenant_id,
            metadata={
                "tenant_slug": tenant_slug,
                "provider_name": provider_name,
                "reason": reason,
            },
            ip_address=ip_address,
        )
        self.metrics.increment("agentgate_oidc_logins_total", result="failure")
        db.commit()


def build_oidc_frontend_redirect(*, tenant_slug: str, ticket: str | None = None, error_code: str | None = None) -> str:
    params = {"tenant_slug": tenant_slug}
    if error_code:
        params["sso_error"] = error_code
    base = f"{get_settings().public_app_url}/login"
    if ticket:
        return f"{base}?{urlencode(params)}#oidc_ticket={quote(ticket)}"
    return f"{base}?{urlencode(params)}"
