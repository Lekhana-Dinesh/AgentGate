from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.enums import PayloadRetentionClass
from app.core.errors import AppError
from app.core.retention import (
    PAYLOAD_REDACTION_STATUS_PROTECTED,
    PAYLOAD_REDACTION_STATUS_SANITIZED,
    compute_payload_expiry,
    is_purged_execution_payload,
)
from app.core.redaction import REDACTED_VALUE, redact_sensitive_data, redact_sensitive_string
from app.security.payload_protection import (
    LocalSymmetricPayloadEncryptionProvider,
    PayloadEncryptionProvider,
    PayloadProtectionError,
)

_SENSITIVE_KEYS = {
    "authorization",
    "token",
    "access_token",
    "password",
    "secret",
    "api_key",
    "private_key",
    "client_secret",
    "refresh_token",
    "bearer",
    "cookie",
    "set_cookie",
    "headers",
}
_DISPLAY_REDACTION_KEYS = {
    "attachment",
    "attachments",
    "body",
    "comment",
    "content",
    "html_body",
    "message",
    "query",
    "sql",
    "text",
}
_CONTENT_PROTECTION_CLASSES = {"confidential", "internal", "internal_pricing", "financial"}
_VALUE_SECRET_MARKERS = ("ghp_", "github_pat_", "Bearer ", "xoxb-", "xoxp-", "xoxa-")


@dataclass(slots=True)
class PayloadProtectionContext:
    tool_name: str | None = None
    action_name: str | None = None
    data_classifications: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProtectedPayloadBundle:
    protected_payload: Any
    sanitized_payload: Any
    protected_field_paths: list[str]
    protection_version: str | None
    retention_class: str
    expires_at: datetime | None
    redaction_status: str


class PayloadService:
    def __init__(self, provider: PayloadEncryptionProvider | None = None) -> None:
        self.provider = provider or LocalSymmetricPayloadEncryptionProvider()

    def protect_payload(
        self,
        payload: Any,
        *,
        context: PayloadProtectionContext | None = None,
    ) -> ProtectedPayloadBundle:
        effective_context = context or PayloadProtectionContext()
        protected_paths: list[str] = []
        protected_payload = self._protect_value(
            payload,
            context=effective_context,
            path="$",
            parent_key=None,
            protected_paths=protected_paths,
        )
        sanitized_payload = self.sanitize_payload(payload)
        retention_class = self._retention_class(effective_context, bool(protected_paths))
        redaction_status = (
            PAYLOAD_REDACTION_STATUS_PROTECTED if protected_paths else PAYLOAD_REDACTION_STATUS_SANITIZED
        )
        expires_at = (
            compute_payload_expiry(retention_class)
            if protected_paths and retention_class != PayloadRetentionClass.LEGAL_HOLD.value
            else None
        )
        return ProtectedPayloadBundle(
            protected_payload=protected_payload,
            sanitized_payload=sanitized_payload,
            protected_field_paths=protected_paths,
            protection_version=self.provider.algorithm_name if protected_paths else None,
            retention_class=retention_class,
            expires_at=expires_at,
            redaction_status=redaction_status,
        )

    def decrypt_payload_for_execution(self, payload: Any) -> Any:
        if is_purged_execution_payload(payload):
            raise AppError(
                "Protected execution payload has already been purged by retention policy.",
                status_code=409,
                code="protected_payload_purged",
            )
        if payload is None:
            raise AppError(
                "Protected execution payload is no longer available.",
                status_code=409,
                code="protected_payload_unavailable",
            )
        try:
            return self._decrypt_value(payload)
        except PayloadProtectionError as exc:
            raise AppError(
                "Protected payload state is invalid and could not be decrypted for execution.",
                status_code=500,
                code="protected_payload_invalid",
            ) from exc

    def sanitize_payload(self, payload: Any) -> Any:
        return self._sanitize_value(payload, parent_key=None)

    def _protect_value(
        self,
        value: Any,
        *,
        context: PayloadProtectionContext,
        path: str,
        parent_key: str | None,
        protected_paths: list[str],
    ) -> Any:
        if self.provider.is_encrypted(value):
            return value

        if isinstance(value, dict):
            protected: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = self._normalize_key(key)
                child_path = self._child_path(path, key)
                if self._should_encrypt_value(
                    key=normalized_key,
                    value=item,
                    context=context,
                ):
                    protected[key] = self._encrypt_json_value(item)
                    protected_paths.append(child_path)
                    continue
                protected[key] = self._protect_value(
                    item,
                    context=context,
                    path=child_path,
                    parent_key=normalized_key,
                    protected_paths=protected_paths,
                )
            return protected

        if isinstance(value, list):
            return [
                self._protect_value(
                    item,
                    context=context,
                    path=f"{path}[{index}]",
                    parent_key=parent_key,
                    protected_paths=protected_paths,
                )
                for index, item in enumerate(value)
            ]

        return value

    def _decrypt_value(self, value: Any) -> Any:
        if self.provider.is_encrypted(value):
            decrypted = self.provider.decrypt(value)
            try:
                return json.loads(decrypted)
            except ValueError:
                return decrypted
        if isinstance(value, dict):
            return {key: self._decrypt_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._decrypt_value(item) for item in value]
        return value

    def _sanitize_value(self, value: Any, *, parent_key: str | None) -> Any:
        if self.provider.is_encrypted(value):
            return self.provider.redact(value)

        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = self._normalize_key(key)
                if normalized_key in _DISPLAY_REDACTION_KEYS:
                    sanitized[key] = REDACTED_VALUE
                    continue
                sanitized[key] = self._sanitize_value(item, parent_key=normalized_key)
            return redact_sensitive_data(sanitized)

        if isinstance(value, list):
            return [self._sanitize_value(item, parent_key=parent_key) for item in value]

        if isinstance(value, str):
            if parent_key in _DISPLAY_REDACTION_KEYS:
                return REDACTED_VALUE
            return redact_sensitive_string(value)

        return value

    def _should_encrypt_value(
        self,
        *,
        key: str,
        value: Any,
        context: PayloadProtectionContext,
    ) -> bool:
        if key in _SENSITIVE_KEYS:
            return True
        if key in _DISPLAY_REDACTION_KEYS and self._requires_content_protection(context):
            return True
        if key in _DISPLAY_REDACTION_KEYS and self._contains_secret_like_value(value):
            return True
        if context.tool_name and context.tool_name.lower() == "github" and key == "body":
            return self._has_sensitive_classification(context, {"confidential", "internal", "internal_pricing"})
        if context.tool_name and context.tool_name.lower() == "slack" and key in {"text", "message", "body"}:
            return self._contains_secret_like_value(value)
        return False

    def _requires_content_protection(self, context: PayloadProtectionContext) -> bool:
        return self._has_sensitive_classification(context, _CONTENT_PROTECTION_CLASSES)

    def _has_sensitive_classification(
        self,
        context: PayloadProtectionContext,
        allowed: set[str],
    ) -> bool:
        data_classes = {self._normalize_key(item) for item in context.data_classifications}
        return bool(data_classes & allowed)

    def _contains_secret_like_value(self, value: Any) -> bool:
        if isinstance(value, str):
            redacted = redact_sensitive_string(value)
            return any(marker in value for marker in _VALUE_SECRET_MARKERS) or redacted != value
        if isinstance(value, dict):
            return any(self._contains_secret_like_value(item) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_secret_like_value(item) for item in value)
        return False

    def _encrypt_json_value(self, value: Any) -> dict[str, Any]:
        serialized = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        return self.provider.encrypt(serialized)

    def _retention_class(self, context: PayloadProtectionContext, has_protected_fields: bool) -> str:
        normalized_classes = {self._normalize_key(item) for item in context.data_classifications}
        if "legal_hold" in normalized_classes:
            return PayloadRetentionClass.LEGAL_HOLD.value
        if self._requires_content_protection(context):
            return PayloadRetentionClass.EXTENDED.value
        if has_protected_fields:
            return PayloadRetentionClass.SHORT_LIVED.value
        return PayloadRetentionClass.STANDARD.value

    def _child_path(self, parent: str, key: str) -> str:
        return f"{parent}.{key}" if parent else key

    def _normalize_key(self, value: str) -> str:
        return str(value).strip().lower()
