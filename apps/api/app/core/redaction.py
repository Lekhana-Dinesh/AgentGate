from __future__ import annotations

import re
from typing import Any

REDACTED_VALUE = "[REDACTED]"
PROTECTED_VALUE = "[PROTECTED]"
ENCRYPTED_MARKER = "__agentgate_encrypted__"
SENSITIVE_KEYS = {
    "authorization",
    "token",
    "access_token",
    "github_token",
    "personal_access_token",
    "pat",
    "api_key",
    "x-api-key",
    "secret",
    "password",
    "headers",
}
TOKEN_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]+\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+\b", re.IGNORECASE),
]


def redact_sensitive_string(value: str) -> str:
    redacted = value
    for pattern in TOKEN_PATTERNS:
        redacted = pattern.sub(REDACTED_VALUE, redacted)
    return redacted


def redact_sensitive_data(value: Any) -> Any:
    if _is_encrypted_envelope(value):
        return PROTECTED_VALUE
    if isinstance(value, dict):
        return {
            key: _redact_mapping_value(str(key), item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_string(value)
    return value


def _redact_mapping_value(key: str, value: Any) -> Any:
    normalized_key = key.strip().lower()
    if isinstance(value, str) and value in (REDACTED_VALUE, PROTECTED_VALUE):
        return value
    if normalized_key in SENSITIVE_KEYS:
        return REDACTED_VALUE
    if isinstance(value, str):
        return redact_sensitive_string(value)
    return redact_sensitive_data(value)


def _is_encrypted_envelope(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get(ENCRYPTED_MARKER) is True
        and isinstance(value.get("ciphertext"), str)
    )
