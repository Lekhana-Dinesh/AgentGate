from __future__ import annotations

import hashlib
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import desc, event, select
from sqlalchemy.orm import Session as SASession

from app.models.base import utcnow
from app.services.payload_service import PayloadService

AUDIT_HASH_ALGORITHM = "sha256_json_v1"

payload_service = PayloadService()
_listeners_registered = False


def build_audit_chain_scope(tenant_id: str) -> str:
    return f"tenant:{tenant_id}"


def canonicalize_audit_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_canonical_audit_event_payload(event) -> dict:
    actor_type = getattr(event, "actor_type", None)
    actor_type_value = actor_type.value if hasattr(actor_type, "value") else actor_type
    metadata = payload_service.sanitize_payload(getattr(event, "metadata_json", None) or {})
    return {
        "version": 1,
        "id": getattr(event, "id", None),
        "tenant_id": getattr(event, "tenant_id", None),
        "chain_scope": build_audit_chain_scope(getattr(event, "tenant_id", "")),
        "actor_type": actor_type_value,
        "actor_id": getattr(event, "actor_id", None),
        "event_type": getattr(event, "event_type", None),
        "resource_type": getattr(event, "resource_type", None),
        "resource_id": getattr(event, "resource_id", None),
        "metadata": metadata,
        "ip_address": getattr(event, "ip_address", None),
        "created_at": canonicalize_audit_datetime(getattr(event, "created_at", None)),
    }


def compute_audit_event_hash(event) -> str:
    canonical_payload = build_canonical_audit_event_payload(event)
    canonical_json = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def is_audit_event_anchored(event) -> bool:
    return bool(
        getattr(event, "event_hash", None)
        and getattr(event, "hash_algorithm", None)
        and getattr(event, "chain_scope", None)
        and getattr(event, "sequence_number", None) is not None
        and getattr(event, "anchored_at", None) is not None
    )


def register_audit_event_integrity_listeners(audit_event_cls) -> None:
    global _listeners_registered
    if _listeners_registered:
        return

    @event.listens_for(SASession, "before_flush")
    def _assign_audit_event_integrity(session, flush_context, instances) -> None:  # pragma: no cover - exercised via integration tests
        new_events = [item for item in session.new if isinstance(item, audit_event_cls)]
        if not new_events:
            return

        grouped_events: dict[str, list] = defaultdict(list)
        for audit_event in new_events:
            if not audit_event.id:
                audit_event.id = str(uuid.uuid4())
            if audit_event.created_at is None:
                audit_event.created_at = utcnow()
            audit_event.metadata_json = payload_service.sanitize_payload(audit_event.metadata_json or {})
            grouped_events[audit_event.tenant_id].append(audit_event)

        for tenant_id, tenant_events in grouped_events.items():
            from app.models.tenant import Tenant

            session.execute(
                select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
            ).first()

            previous_event = session.scalar(
                select(audit_event_cls)
                .where(
                    audit_event_cls.tenant_id == tenant_id,
                    audit_event_cls.sequence_number.is_not(None),
                    audit_event_cls.event_hash.is_not(None),
                )
                .order_by(
                    desc(audit_event_cls.sequence_number),
                    desc(audit_event_cls.created_at),
                    desc(audit_event_cls.id),
                )
                .limit(1)
            )
            previous_hash = previous_event.event_hash if previous_event else None
            previous_sequence = previous_event.sequence_number if previous_event else 0
            chain_scope = build_audit_chain_scope(tenant_id)

            for audit_event in sorted(
                tenant_events,
                key=lambda item: (
                    canonicalize_audit_datetime(item.created_at) or "",
                    item.id,
                ),
            ):
                audit_event.event_hash = compute_audit_event_hash(audit_event)
                audit_event.previous_event_hash = previous_hash
                audit_event.hash_algorithm = AUDIT_HASH_ALGORITHM
                audit_event.chain_scope = chain_scope
                previous_sequence += 1
                audit_event.sequence_number = previous_sequence
                audit_event.anchored_at = audit_event.created_at or utcnow()
                previous_hash = audit_event.event_hash

    _listeners_registered = True
