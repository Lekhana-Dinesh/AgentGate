from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

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
KEY_PROVIDER_AWS_KMS = "aws_kms"
KEY_STATUS_UNAVAILABLE = "unavailable"
LOCAL_FALLBACK_KEY_REF = "local-dev-fallback"
LEGACY_CONFIGURED_ENV_KEY_REF = "configured-env"
AWS_KMS_DATA_KEY_WRAP_ALGORITHM = "aws-kms-generate-data-key"
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
    region: str | None = None


@dataclass(frozen=True, slots=True)
class KeyRecord:
    material: str | None
    metadata: KeyMetadata
    encrypted_material: str | None = None
    wrapping_algorithm: str | None = None


@dataclass(frozen=True, slots=True)
class KeyPurposeStatus:
    purpose: str
    provider: str
    active_key_ref: str | None
    active_key_version: str | None
    configured_key_refs: list[str]
    status: str
    warnings: list[str]
    region: str | None = None


@dataclass(frozen=True, slots=True)
class _ConfiguredKeySource:
    key_ref: str
    version: str | None
    status: str
    direct_value: str | None = None
    secret_reference: str | None = None
    provider: str = KEY_PROVIDER_ENV
    region: str | None = None


@dataclass(frozen=True, slots=True)
class _AwsKmsKeySource:
    key_ref: str
    key_id: str
    region: str
    version: str | None
    status: str
    endpoint_url: str | None = None


class KeyProvider(Protocol):
    provider_name: str

    def get_active_key(self, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        ...

    def get_key_by_ref(
        self,
        key_ref: str,
        *,
        purpose: str,
        tenant_id: str | None = None,
        provider_hint: str | None = None,
    ) -> KeyRecord:
        ...

    def get_purpose_status(self, purpose: str, tenant_id: str | None = None) -> KeyPurposeStatus:
        ...


@runtime_checkable
class EnvelopeKeyProvider(KeyProvider, Protocol):
    def generate_data_key(self, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        ...

    def decrypt_data_key(
        self,
        encrypted_material: str,
        *,
        key_ref: str,
        purpose: str,
        tenant_id: str | None = None,
    ) -> KeyRecord:
        ...


def _build_env_key_sources(
    settings: Settings,
    *,
    active_ref: str,
    active_version: str | None,
    include_local_fallback: bool,
) -> dict[str, _ConfiguredKeySource]:
    sources: dict[str, _ConfiguredKeySource] = {}
    direct_value = (settings.payload_encryption_key or "").strip() or None
    active_secret_reference = str(settings.payload_encryption_key_secret_ref or "").strip() or None

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

    for key_ref, secret_reference in settings.payload_encryption_additional_keys.items():
        if key_ref in sources:
            continue
        sources[key_ref] = _ConfiguredKeySource(
            key_ref=key_ref,
            version=settings.payload_encryption_additional_key_versions.get(key_ref),
            status=(KEY_STATUS_ACTIVE if key_ref == active_ref else KEY_STATUS_DECRYPT_ONLY),
            secret_reference=secret_reference,
        )

    if include_local_fallback and settings.environment in {"development", "test"} and not sources:
        sources[LOCAL_FALLBACK_KEY_REF] = _ConfiguredKeySource(
            key_ref=LOCAL_FALLBACK_KEY_REF,
            version="dev-fallback",
            status=KEY_STATUS_ACTIVE,
            direct_value=_local_fallback_key(),
        )

    return sources


def _materialize_env_key(
    source: _ConfiguredKeySource,
    *,
    purpose: str,
    secret_resolver: LocalSecretResolver,
) -> KeyRecord:
    try:
        material = _resolve_env_key_material(source, secret_resolver=secret_resolver)
        Fernet(material.encode("utf-8"))
    except SecretResolutionError as exc:
        raise KeyManagementError(
            "The configured payload protection key could not be resolved.",
            code=exc.code,
        ) from exc
    except KeyManagementError:
        raise
    except Exception as exc:
        raise KeyManagementError(
            "The configured payload protection key is invalid.",
            code="key_invalid",
        ) from exc

    return KeyRecord(
        material=material,
        metadata=KeyMetadata(
            key_ref=source.key_ref,
            provider=source.provider,
            version=source.version,
            purpose=purpose,
            created_at=None,
            status=source.status,
            region=source.region,
        ),
    )


def _resolve_env_key_material(
    source: _ConfiguredKeySource,
    secret_resolver: LocalSecretResolver,
) -> str:
    if source.direct_value:
        return source.direct_value
    if source.secret_reference:
        return secret_resolver.resolve(source.secret_reference).value
    raise KeyManagementError(
        "The configured payload protection key is not available.",
        code="key_not_configured",
    )


def _local_fallback_key() -> str:
    return base64.urlsafe_b64encode(
        sha256(_LOCAL_FALLBACK_SEED.encode("utf-8")).digest()
    ).decode("utf-8")


def _safe_kms_key_ref(key_id: str) -> str:
    normalized = str(key_id or "").strip()
    if not normalized:
        return "aws-kms"
    if normalized.startswith("alias/"):
        return normalized
    if ":alias/" in normalized:
        return f"alias/{normalized.split(':alias/', 1)[1]}"
    if ":key/" in normalized:
        return f"kms-key/{normalized.split(':key/', 1)[1]}"
    if normalized.startswith("arn:"):
        return normalized.rsplit(":", 1)[-1]
    return normalized


def _build_aws_kms_client(*, region_name: str, endpoint_url: str | None) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except Exception as exc:  # pragma: no cover - exercised through provider behavior
        raise KeyManagementError(
            "AWS KMS dependencies are not installed for the configured key provider.",
            code="kms_dependencies_missing",
        ) from exc

    session = boto3.session.Session(region_name=region_name)
    return session.client(
        "kms",
        endpoint_url=endpoint_url,
        config=Config(
            retries={"max_attempts": 2, "mode": "standard"},
            connect_timeout=3,
            read_timeout=5,
        ),
    )


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
        return _materialize_env_key(source, purpose=purpose, secret_resolver=self.secret_resolver)

    def get_key_by_ref(
        self,
        key_ref: str,
        *,
        purpose: str,
        tenant_id: str | None = None,
        provider_hint: str | None = None,  # noqa: ARG002 - kept for interface compatibility
    ) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        normalized_ref = str(key_ref or "").strip()
        source = self._payload_key_sources().get(normalized_ref)
        if not source:
            raise KeyManagementError(
                "The requested payload protection key reference is not configured.",
                code="key_ref_unknown",
            )
        return _materialize_env_key(source, purpose=purpose, secret_resolver=self.secret_resolver)

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
                _materialize_env_key(active_source, purpose=purpose, secret_resolver=self.secret_resolver)
            except KeyManagementError:
                status = "unconfigured"
                warnings.append("The active payload protection key is unavailable or invalid.")

        unresolved_decrypt_only = False
        for source in configured_sources.values():
            if source.status != KEY_STATUS_DECRYPT_ONLY:
                continue
            try:
                _materialize_env_key(source, purpose=purpose, secret_resolver=self.secret_resolver)
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
            region=None,
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
        return _build_env_key_sources(
            self.settings,
            active_ref=self.settings.payload_encryption_active_key_ref,
            active_version=self.settings.payload_encryption_key_version,
            include_local_fallback=True,
        )


class AwsKmsKeyProvider:
    provider_name = KEY_PROVIDER_AWS_KMS

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        secret_resolver: LocalSecretResolver | None = None,
        kms_client: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.secret_resolver = secret_resolver or get_secret_resolver()
        self._kms_client = kms_client

    def get_active_key(self, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        source = self._active_source()
        if not source:
            raise KeyManagementError(
                "AWS KMS payload protection is not fully configured.",
                code="key_not_configured",
            )
        return KeyRecord(
            material=None,
            metadata=KeyMetadata(
                key_ref=source.key_ref,
                provider=self.provider_name,
                version=source.version,
                purpose=purpose,
                created_at=None,
                status=source.status,
                region=source.region,
            ),
        )

    def get_key_by_ref(
        self,
        key_ref: str,
        *,
        purpose: str,
        tenant_id: str | None = None,
        provider_hint: str | None = None,
    ) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        normalized_ref = str(key_ref or "").strip()
        legacy_source = self._legacy_env_sources().get(normalized_ref)
        if provider_hint == KEY_PROVIDER_ENV and legacy_source:
            return _materialize_env_key(legacy_source, purpose=purpose, secret_resolver=self.secret_resolver)
        if legacy_source and normalized_ref != self._active_key_ref():
            return _materialize_env_key(legacy_source, purpose=purpose, secret_resolver=self.secret_resolver)
        if normalized_ref == self._active_key_ref():
            raise KeyManagementError(
                "AWS KMS protected payloads require the stored encrypted data key to decrypt safely.",
                code="kms_encrypted_data_key_required",
            )
        raise KeyManagementError(
            "The requested payload protection key reference is not configured.",
            code="key_ref_unknown",
        )

    def get_purpose_status(self, purpose: str, tenant_id: str | None = None) -> KeyPurposeStatus:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        warnings: list[str] = []
        active_source = self._active_source()
        legacy_sources = self._legacy_env_sources()
        configured_key_refs = sorted({*(legacy_sources.keys()), self._active_key_ref()})

        if not active_source:
            return KeyPurposeStatus(
                purpose=purpose,
                provider=self.provider_name,
                active_key_ref=None,
                active_key_version=None,
                configured_key_refs=sorted(legacy_sources.keys()),
                status="unconfigured",
                warnings=["AWS KMS payload protection is not fully configured."],
                region=str(self.settings.aws_region or "").strip() or None,
            )

        status = "ready"
        try:
            self._describe_active_key(active_source)
        except KeyManagementError:
            status = KEY_STATUS_UNAVAILABLE
            warnings.append("The configured AWS KMS payload protection key is unavailable.")

        unresolved_decrypt_only = False
        for source in legacy_sources.values():
            if source.status != KEY_STATUS_DECRYPT_ONLY:
                continue
            try:
                _materialize_env_key(source, purpose=purpose, secret_resolver=self.secret_resolver)
            except KeyManagementError:
                unresolved_decrypt_only = True
                break
        if status == "ready" and unresolved_decrypt_only:
            status = "degraded"
            warnings.append("One or more legacy decrypt-only payload protection keys are unresolved.")

        if active_source.endpoint_url:
            warnings.append("A custom AWS KMS endpoint URL is configured.")

        return KeyPurposeStatus(
            purpose=purpose,
            provider=self.provider_name,
            active_key_ref=active_source.key_ref,
            active_key_version=active_source.version,
            configured_key_refs=configured_key_refs,
            status=status,
            warnings=warnings,
            region=active_source.region,
        )

    def generate_data_key(self, purpose: str, tenant_id: str | None = None) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        source = self._active_source()
        if not source:
            raise KeyManagementError(
                "AWS KMS payload protection is not fully configured.",
                code="key_not_configured",
            )
        try:
            response = self._kms_client_or_raise().generate_data_key(
                KeyId=source.key_id,
                NumberOfBytes=32,
                EncryptionContext=self._kms_encryption_context(key_ref=source.key_ref, purpose=purpose),
            )
            plaintext_key = response.get("Plaintext")
            ciphertext_blob = response.get("CiphertextBlob")
            if not isinstance(plaintext_key, (bytes, bytearray)) or not isinstance(
                ciphertext_blob, (bytes, bytearray)
            ):
                raise KeyManagementError(
                    "AWS KMS returned an invalid payload protection data key response.",
                    code="kms_invalid_response",
                )
            material = base64.urlsafe_b64encode(bytes(plaintext_key)).decode("utf-8")
            Fernet(material.encode("utf-8"))
            return KeyRecord(
                material=material,
                encrypted_material=base64.b64encode(bytes(ciphertext_blob)).decode("ascii"),
                wrapping_algorithm=AWS_KMS_DATA_KEY_WRAP_ALGORITHM,
                metadata=KeyMetadata(
                    key_ref=source.key_ref,
                    provider=self.provider_name,
                    version=source.version,
                    purpose=purpose,
                    created_at=utcnow(),
                    status=source.status,
                    region=source.region,
                ),
            )
        except KeyManagementError:
            raise
        except Exception as exc:
            raise KeyManagementError(
                "AWS KMS data key generation failed.",
                code="kms_generate_data_key_failed",
            ) from exc

    def decrypt_data_key(
        self,
        encrypted_material: str,
        *,
        key_ref: str,
        purpose: str,
        tenant_id: str | None = None,
    ) -> KeyRecord:
        self._assert_supported_purpose(purpose, tenant_id=tenant_id)
        normalized_key_ref = str(key_ref or "").strip()
        if not normalized_key_ref:
            raise KeyManagementError(
                "The protected payload envelope is missing a key reference.",
                code="key_ref_missing",
            )
        try:
            ciphertext_blob = base64.b64decode(str(encrypted_material or "").encode("ascii"), validate=True)
        except Exception as exc:
            raise KeyManagementError(
                "The protected payload envelope contains an invalid encrypted data key.",
                code="kms_encrypted_data_key_invalid",
            ) from exc

        try:
            response = self._kms_client_or_raise().decrypt(
                CiphertextBlob=ciphertext_blob,
                EncryptionContext=self._kms_encryption_context(key_ref=normalized_key_ref, purpose=purpose),
            )
            plaintext_key = response.get("Plaintext")
            if not isinstance(plaintext_key, (bytes, bytearray)):
                raise KeyManagementError(
                    "AWS KMS returned an invalid decrypted payload protection key.",
                    code="kms_invalid_response",
                )
            material = base64.urlsafe_b64encode(bytes(plaintext_key)).decode("utf-8")
            Fernet(material.encode("utf-8"))
            return KeyRecord(
                material=material,
                encrypted_material=str(encrypted_material or "").strip() or None,
                wrapping_algorithm=AWS_KMS_DATA_KEY_WRAP_ALGORITHM,
                metadata=KeyMetadata(
                    key_ref=normalized_key_ref,
                    provider=self.provider_name,
                    version=self.settings.payload_encryption_key_version,
                    purpose=purpose,
                    created_at=None,
                    status=KEY_STATUS_DECRYPT_ONLY,
                    region=str(self.settings.aws_region or "").strip() or None,
                ),
            )
        except KeyManagementError:
            raise
        except Exception as exc:
            raise KeyManagementError(
                "AWS KMS could not decrypt the protected payload data key.",
                code="kms_decrypt_failed",
            ) from exc

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

    def _active_source(self) -> _AwsKmsKeySource | None:
        key_id = str(self.settings.aws_kms_key_id or "").strip()
        region = str(self.settings.aws_region or "").strip()
        if not key_id or not region:
            return None
        return _AwsKmsKeySource(
            key_ref=self._active_key_ref(),
            key_id=key_id,
            region=region,
            version=self.settings.payload_encryption_key_version,
            status=KEY_STATUS_ACTIVE,
            endpoint_url=str(self.settings.aws_kms_endpoint_url or "").strip() or None,
        )

    def _active_key_ref(self) -> str:
        configured_ref = str(self.settings.payload_encryption_active_key_ref or "").strip()
        if configured_ref and configured_ref != LEGACY_CONFIGURED_ENV_KEY_REF:
            return configured_ref
        return _safe_kms_key_ref(self.settings.aws_kms_key_id or "")

    def _legacy_env_sources(self) -> dict[str, _ConfiguredKeySource]:
        sources = _build_env_key_sources(
            self.settings,
            active_ref=str(self.settings.payload_encryption_active_key_ref or LEGACY_CONFIGURED_ENV_KEY_REF).strip()
            or LEGACY_CONFIGURED_ENV_KEY_REF,
            active_version=self.settings.payload_encryption_key_version,
            include_local_fallback=False,
        )
        for key_ref, source in list(sources.items()):
            sources[key_ref] = _ConfiguredKeySource(
                key_ref=source.key_ref,
                version=source.version,
                status=KEY_STATUS_DECRYPT_ONLY,
                direct_value=source.direct_value,
                secret_reference=source.secret_reference,
                provider=KEY_PROVIDER_ENV,
                region=None,
            )
        return sources

    def _kms_client_or_raise(self) -> Any:
        if self._kms_client is None:
            region = str(self.settings.aws_region or "").strip()
            endpoint_url = str(self.settings.aws_kms_endpoint_url or "").strip() or None
            self._kms_client = _build_aws_kms_client(region_name=region, endpoint_url=endpoint_url)
        return self._kms_client

    def _describe_active_key(self, source: _AwsKmsKeySource) -> None:
        try:
            response = self._kms_client_or_raise().describe_key(KeyId=source.key_id)
            metadata = response.get("KeyMetadata") if isinstance(response, dict) else None
            if not isinstance(metadata, dict):
                raise KeyManagementError(
                    "AWS KMS returned invalid key metadata.",
                    code="kms_invalid_response",
                )
        except KeyManagementError:
            raise
        except Exception as exc:
            raise KeyManagementError(
                "The configured AWS KMS payload protection key is unavailable.",
                code="kms_unavailable",
            ) from exc

    def _kms_encryption_context(self, *, key_ref: str, purpose: str) -> dict[str, str]:
        return {
            "agentgate:purpose": purpose,
            "agentgate:key_ref": key_ref,
        }


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@lru_cache(maxsize=1)
def get_key_provider() -> KeyProvider:
    settings = get_settings()
    if settings.key_provider == KEY_PROVIDER_AWS_KMS:
        return AwsKmsKeyProvider(settings=settings)
    return LocalEnvKeyProvider(settings=settings)
