from __future__ import annotations

from typing import Any, Protocol

from cryptography.fernet import Fernet, InvalidToken

from app.security.key_management import (
    EnvelopeKeyProvider,
    KEY_PURPOSE_PAYLOAD_PROTECTION,
    KeyManagementError,
    KeyProvider,
    get_key_provider,
    utcnow,
)

ENCRYPTED_MARKER = "__agentgate_encrypted__"
ENCRYPTED_ALGORITHM = "local-fernet-v1"
PROTECTED_VALUE = "[PROTECTED]"


class PayloadProtectionError(Exception):
    """Raised when protected payloads cannot be safely decrypted or validated."""


class PayloadEncryptionProvider(Protocol):
    algorithm_name: str
    key_ref: str

    def encrypt(self, value: str) -> dict[str, Any]:
        ...

    def decrypt(self, envelope: Any) -> str:
        ...

    def is_encrypted(self, value: Any) -> bool:
        ...

    def redact(self, value: Any) -> str:
        ...


def is_encrypted_envelope(value: Any) -> bool:
    algorithm = value.get("alg") if isinstance(value, dict) else None
    if not isinstance(algorithm, str) and isinstance(value, dict):
        algorithm = value.get("algorithm")
    return (
        isinstance(value, dict)
        and value.get(ENCRYPTED_MARKER) is True
        and isinstance(value.get("ciphertext"), str)
        and isinstance(algorithm, str)
    )


class LocalSymmetricPayloadEncryptionProvider:
    algorithm_name = ENCRYPTED_ALGORITHM

    def __init__(self, *, key_provider: KeyProvider | None = None) -> None:
        self.key_provider = key_provider or get_key_provider()
        self._fernet_cache: dict[str, Fernet] = {}
        self._supports_envelope_keys = isinstance(self.key_provider, EnvelopeKeyProvider)
        try:
            active_key = self.key_provider.get_active_key(KEY_PURPOSE_PAYLOAD_PROTECTION)
            if active_key.material:
                self._fernet_cache[active_key.metadata.key_ref] = Fernet(active_key.material.encode("utf-8"))
            elif not self._supports_envelope_keys:
                raise PayloadProtectionError(
                    "Payload encryption key is invalid for the configured provider."
                )
        except KeyManagementError as exc:
            raise PayloadProtectionError(exc.detail) from exc
        except Exception as exc:  # pragma: no cover - guarded by tests
            raise PayloadProtectionError(
                "Payload encryption key is invalid for the configured provider."
            ) from exc
        self.key_ref = active_key.metadata.key_ref
        self.key_version = active_key.metadata.version
        self.provider_name = active_key.metadata.provider

    def encrypt(self, value: str) -> dict[str, Any]:
        active_key = self._get_encryption_key()
        ciphertext = self._fernet_for_key(
            self._cache_key_for_record(active_key),
            key_material=active_key.material,
        ).encrypt(
            value.encode("utf-8")
        ).decode("utf-8")
        envelope = {
            ENCRYPTED_MARKER: True,
            "alg": self.algorithm_name,
            "algorithm": self.algorithm_name,
            "ciphertext": ciphertext,
            "key_ref": active_key.metadata.key_ref,
            "key_version": active_key.metadata.version,
            "provider": active_key.metadata.provider,
            "created_at": (
                active_key.metadata.created_at or utcnow()
            ).isoformat().replace("+00:00", "Z"),
        }
        if active_key.encrypted_material:
            envelope["encrypted_data_key"] = active_key.encrypted_material
            if active_key.wrapping_algorithm:
                envelope["encrypted_data_key_algorithm"] = active_key.wrapping_algorithm
        return envelope

    def decrypt(self, envelope: Any) -> str:
        if not self.is_encrypted(envelope):
            raise PayloadProtectionError("Protected payload envelope is invalid.")
        if (envelope.get("alg") or envelope.get("algorithm")) != self.algorithm_name:
            raise PayloadProtectionError("Protected payload algorithm is not supported.")
        key_ref = str(envelope.get("key_ref") or self.key_ref).strip()
        provider_hint = str(envelope.get("provider") or "").strip() or None
        try:
            encrypted_data_key = envelope.get("encrypted_data_key")
            if isinstance(encrypted_data_key, str) and encrypted_data_key.strip():
                fernet = self._fernet_for_encrypted_data_key(key_ref, encrypted_data_key)
            else:
                fernet = self._fernet_for_envelope(key_ref, provider_hint=provider_hint)
            return fernet.decrypt(envelope["ciphertext"].encode("utf-8")).decode("utf-8")
        except KeyManagementError as exc:
            raise PayloadProtectionError(exc.detail) from exc
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise PayloadProtectionError("Protected payload could not be decrypted.") from exc

    def is_encrypted(self, value: Any) -> bool:
        return is_encrypted_envelope(value)

    def redact(self, value: Any) -> str:
        return PROTECTED_VALUE

    def _get_encryption_key(self):
        try:
            if self._supports_envelope_keys:
                return self.key_provider.generate_data_key(KEY_PURPOSE_PAYLOAD_PROTECTION)
            return self.key_provider.get_active_key(KEY_PURPOSE_PAYLOAD_PROTECTION)
        except KeyManagementError as exc:
            raise PayloadProtectionError(exc.detail) from exc

    def _fernet_for_encrypted_data_key(self, key_ref: str, encrypted_data_key: str) -> Fernet:
        if not self._supports_envelope_keys:
            raise PayloadProtectionError(
                "The configured key provider cannot decrypt this protected payload envelope."
            )
        try:
            key_record = self.key_provider.decrypt_data_key(
                encrypted_data_key,
                key_ref=key_ref,
                purpose=KEY_PURPOSE_PAYLOAD_PROTECTION,
            )
        except KeyManagementError as exc:
            raise PayloadProtectionError(exc.detail) from exc
        return self._fernet_for_key(
            self._cache_key_for_record(key_record),
            key_material=key_record.material,
        )

    def _fernet_for_envelope(self, key_ref: str, *, provider_hint: str | None = None) -> Fernet:
        try:
            key_record = self.key_provider.get_key_by_ref(
                key_ref,
                purpose=KEY_PURPOSE_PAYLOAD_PROTECTION,
                provider_hint=provider_hint,
            )
        except KeyManagementError as exc:
            raise PayloadProtectionError(exc.detail) from exc
        return self._fernet_for_key(
            self._cache_key_for_record(key_record),
            key_material=key_record.material,
        )

    def _cache_key_for_record(self, key_record) -> str:
        return key_record.encrypted_material or key_record.metadata.key_ref

    def _fernet_for_key(self, cache_key: str, *, key_material: str | None) -> Fernet:
        if not key_material:
            raise PayloadProtectionError(
                "Payload encryption key is unavailable for the protected payload envelope."
            )
        cached = self._fernet_cache.get(cache_key)
        if cached:
            return cached
        try:
            fernet = Fernet(key_material.encode("utf-8"))
        except Exception as exc:  # pragma: no cover - guarded by tests
            raise PayloadProtectionError(
                "Payload encryption key is invalid for the configured provider."
            ) from exc
        self._fernet_cache[cache_key] = fernet
        return fernet
