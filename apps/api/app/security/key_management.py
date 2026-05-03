from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from typing import Protocol

from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings
from app.security.secret_references import (
    LocalSecretResolver,
    SecretResolutionError,
    get_secret_resolver,
)

KEY_PURPOSE_PAYLOAD_PROTECTION = "payload_protection"
KEY_STATUS_ACTIVE = "active"
KEY_STATUS_DECRYPT_ONLY = "decrypt_only"
KEY_PROVIDER_ENV = "env"
LOCAL_FALLBACK_KEY_REF = "local-dev-fallback"
LEGACY_CONFIGURED_ENV_KEY_REF = "configured-env"
_LOCAL_FALLBACK_SEED = "agentgate-development-payload-protection-v1"


class KeyManagementError(Exception):
    def __init__(self, detail: str, *, code: str) -> None:
        self.detail = detail
        self.code = code
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class KeyMetadata:
    key_ref: str
    provider: str
    version: str | None
    purpose: str
    created_at: datetime | None
    status: str


@dataclass(frozen=True, slots=True)
class KeyRecord:
    material: str
    metadata: KeyMetadata


@dataclass(frozen=True, slots=True)
class KeyPurposeStatus:
    purpose: str
    provider: str
    active_key_ref: str | None
    active_key_version: str | None
    configured_key_refs: list[str]
    status: str
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class _ConfiguredKeySource:
    key_ref: str
    version: str | None
    status: str
    direct_value: str | None = None
    secret_reference: str | None = None


class KeyProvider(Protocol):
    provider_name: str

    def get_active_key(self, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        ...

    def get_key_by_ref(self, key_ref: str, *, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        ...

    def get_purpose_status(self, purpose: str, tenant_id: str | None = None) -> KeyPurposeStatus:
        ...


class LocalEnvKeyProvider:
    provider_name = KEY_PROVIDER_ENV

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        secret_resolver: LocalSecretResolver | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.secret_resolver = secret_resolver or get_secret_resolver()

    def get_active_key(self, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        source = self._active_source()
        if not source:
            raise KeyManagementError(
                "No active payload protection key is configured.",
                code="key_not_configured",
            )
        return self._materialize_key(source, purpose=purpose)

    def get_key_by_ref(self, key_ref: str, *, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        normalized_ref = str(key_ref or "").strip()
        source = self._payload_key_sources().get(normalized_ref)
        if not source:
            raise KeyManagementError(
                "The requested payload protection key reference is not configured.",
                code="key_ref_unknown",
            )
        return self._materialize_key(source, purpose=purpose)

    def get_purpose_status(self, purpose: str, tenant_id: str | None = None) -> KeyPurposeStatus:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        warnings: list[str] = []
        configured_sources = self._payload_key_sources()
        active_source = self._active_source()
        configured_key_refs = sorted(configured_sources.keys())

        status = "ready"
        active_key_ref = active_source.key_ref if active_source else None
        active_key_version = active_source.version if active_source else None

        if not active_source:
            status = "unconfigured"
            warnings.append("No active payload protection key is configured.")
        else:
            try:
                self._materialize_key(active_source, purpose=purpose)
            except KeyManagementError:
                status = "unconfigured"
                warnings.append("The active payload protection key is unavailable or invalid.")

        unresolved_decrypt_only = False
        for source in configured_sources.values():
            if source.status != KEY_STATUS_DECRYPT_ONLY:
                continue
            try:
                self._materialize_key(source, purpose=purpose)
            except KeyManagementError:
                unresolved_decrypt_only = True
                break
        if status == "ready" and unresolved_decrypt_only:
            status = "degraded"
            warnings.append("One or more decrypt-only payload protection keys are unresolved.")

        if (
            self.settings.environment in {"development", "test"}
            and active_key_ref == LOCAL_FALLBACK_KEY_REF
        ):
            warnings.append("Development fallback payload key is active.")

        return KeyPurposeStatus(
            purpose=purpose,
            provider=self.provider_name,
            active_key_ref=active_key_ref,
            active_key_version=active_key_version,
            configured_key_refs=configured_key_refs,
            status=status,
            warnings=warnings,
        )

    def _assert_supported_purpose(self, purpose: str, *, tenant_id: str | None) -> None:
        if tenant_id is not None:
            raise KeyManagementError(
                "Tenant-scoped key providers are not implemented in this build.",
                code="tenant_keys_unsupported",
            )
        if purpose != KEY_PURPOSE_PAYLOAD_PROTECTION:
            raise KeyManagementError(
                "The requested key purpose is not supported in this build.",
                code="key_purpose_unsupported",
            )

    def _active_source(self) -> _ConfiguredKeySource | None:
        active_ref = self.settings.payload_encryption_active_key_ref
        sources = self._payload_key_sources()
        source = sources.get(active_ref)
        if source:
            return source
        if self.settings.environment in {"development", "test"}:
            return sources.get(LOCAL_FALLBACK_KEY_REF)
        return None

    def _payload_key_sources(self) -> dict[str, _ConfiguredKeySource]:
        sources: dict[str, _ConfiguredKeySource] = {}
        active_ref = self.settings.payload_encryption_active_key_ref
        active_version = self.settings.payload_encryption_key_version
        direct_value = (self.settings.payload_encryption_key or "").strip() or None
        active_secret_reference = str(self.settings.payload_encryption_key_secret_ref or "").strip() or None

        if active_secret_reference:
            sources[active_ref] = _ConfiguredKeySource(
                key_ref=active_ref,
                version=active_version,
                status=KEY_STATUS_ACTIVE,
                secret_reference=active_secret_reference,
            )
        elif direct_value:
            sources[active_ref] = _ConfiguredKeySource(
                key_ref=active_ref,
                version=active_version,
                status=KEY_STATUS_ACTIVE,
                direct_value=direct_value,
            )

        for key_ref, secret_reference in self.settings.payload_encryption_additional_keys.items():
            if key_ref in sources:
                continue
            sources[key_ref] = _ConfiguredKeySource(
                key_ref=key_ref,
                version=self.settings.payload_encryption_additional_key_versions.get(key_ref),
                status=(KEY_STATUS_ACTIVE if key_ref == active_ref else KEY_STATUS_DECRYPT_ONLY),
                secret_reference=secret_reference,
            )

        if self.settings.environment in {"development", "test"} and not sources:
            sources[LOCAL_FALLBACK_KEY_REF] = _ConfiguredKeySource(
                key_ref=LOCAL_FALLBACK_KEY_REF,
                version="dev-fallback",
                status=KEY_STATUS_ACTIVE,
                direct_value=self._local_fallback_key(),
            )

        if (
            direct_value
            and active_ref == LEGACY_CONFIGURED_ENV_KEY_REF
            and LEGACY_CONFIGURED_ENV_KEY_REF not in sources
        ):
            sources[LEGACY_CONFIGURED_ENV_KEY_REF] = _ConfiguredKeySource(
                key_ref=LEGACY_CONFIGURED_ENV_KEY_REF,
                version=active_version,
                status=KEY_STATUS_ACTIVE,
                direct_value=direct_value,
            )

        return sources

    def _materialize_key(self, source: _ConfiguredKeySource, *, purpose: str) -> KeyRecord:
        try:
            material = self._resolve_key_material(source)
            Fernet(material.encode("utf-8"))
        except SecretResolutionError as exc:
            raise KeyManagementError(
                "The configured payload protection key could not be resolved.",
                code=exc.code,
            ) from exc
        except Exception as exc:
            raise KeyManagementError(
                "The configured payload protection key is invalid.",
                code="key_invalid",
            ) from exc

        return KeyRecord(
            material=material,
            metadata=KeyMetadata(
                key_ref=source.key_ref,
                provider=self.provider_name,
                version=source.version,
                purpose=purpose,
                created_at=None,
                status=source.status,
            ),
        )

    def _resolve_key_material(self, source: _ConfiguredKeySource) -> str:
        if source.direct_value:
            return source.direct_value
        if source.secret_reference:
            return self.secret_resolver.resolve(source.secret_reference).value
        raise KeyManagementError(
            "The configured payload protection key is not available.",
            code="key_not_configured",
        )

    def _local_fallback_key(self) -> str:
        return base64.urlsafe_b64encode(
            sha256(_LOCAL_FALLBACK_SEED.encode("utf-8")).digest()
        ).decode("utf-8")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_key_provider() -> LocalEnvKeyProvider:
    return LocalEnvKeyProvider()
