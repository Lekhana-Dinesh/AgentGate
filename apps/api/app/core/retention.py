from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.enums import PayloadRetentionClass

LEGACY_RESTRICTED_RETENTION_CLASS = "restricted"
PAYLOAD_REDACTION_STATUS_SANITIZED = "sanitized"
PAYLOAD_REDACTION_STATUS_PROTECTED = "protected"
PAYLOAD_REDACTION_STATUS_PURGED = "purged"
PAYLOAD_REDACTION_STATUS_PURGE_FAILED = "purge_failed"
PURGED_PAYLOAD_MARKER = "__agentgate_payload_purged__"


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def normalize_retention_class(value: str | None) -> str:
    normalized = str(value or PayloadRetentionClass.STANDARD.value).strip().lower()
    if normalized == LEGACY_RESTRICTED_RETENTION_CLASS:
        return PayloadRetentionClass.EXTENDED.value
    if normalized in {
        PayloadRetentionClass.STANDARD.value,
        PayloadRetentionClass.SHORT_LIVED.value,
        PayloadRetentionClass.EXTENDED.value,
        PayloadRetentionClass.LEGAL_HOLD.value,
    }:
        return normalized
    return PayloadRetentionClass.STANDARD.value


def retention_window_days(retention_class: str) -> int | None:
    settings = get_settings()
    normalized = normalize_retention_class(retention_class)
    if normalized == PayloadRetentionClass.LEGAL_HOLD.value:
        return None
    if normalized == PayloadRetentionClass.SHORT_LIVED.value:
        return max(1, settings.payload_retention_short_lived_days)
    if normalized == PayloadRetentionClass.EXTENDED.value:
        return max(1, settings.payload_retention_extended_days)
    return max(1, settings.payload_retention_standard_days)


def compute_payload_expiry(
    retention_class: str,
    *,
    from_time: datetime | None = None,
) -> datetime | None:
    days = retention_window_days(retention_class)
    if days is None:
        return None
    baseline = normalize_datetime(from_time or datetime.now(timezone.utc))
    return baseline + timedelta(days=days)


def effective_payload_expiry(
    retention_class: str,
    *,
    payload_expires_at: datetime | None,
    created_at: datetime,
) -> datetime | None:
    if payload_expires_at is not None:
        return normalize_datetime(payload_expires_at)
    return compute_payload_expiry(retention_class, from_time=created_at)


def build_purged_execution_payload(*, purged_at: datetime, reason: str) -> dict[str, str | bool]:
    return {
        PURGED_PAYLOAD_MARKER: True,
        "reason": reason,
        "purged_at": normalize_datetime(purged_at).isoformat(),
    }


def is_purged_execution_payload(value: object) -> bool:
    return isinstance(value, dict) and value.get(PURGED_PAYLOAD_MARKER) is True
