from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import (
    AUDIT_HASH_ALGORITHM,
    build_audit_chain_scope,
    compute_audit_event_hash,
    is_audit_event_anchored,
)
from app.core.enums import AuditActorType, JobType
from app.core.errors import AppError
from app.models import AuditEvent, Job
from app.models.base import utcnow
from app.schemas.audit_integrity import (
    AuditIntegrityBackfillResponse,
    AuditIntegrityIssue,
    AuditIntegrityStatusResponse,
    AuditIntegrityVerifyResponse,
)
from app.services.audit_service import AuditService
from app.services.job_service import JobProcessingError, JobService

AUDIT_INTEGRITY_VERIFY_QUEUED_EVENT = "audit_integrity.verify.queued"
AUDIT_INTEGRITY_VERIFY_COMPLETED_EVENT = "audit_integrity.verify.completed"


@dataclass(frozen=True, slots=True)
class VerificationBounds:
    start_event_id: str | None = None
    end_event_id: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class AuditIntegrityService:
    def __init__(self) -> None:
        self.audit_service = AuditService()
        self.job_service = JobService()

    def get_status(self, db: Session, *, tenant_id: str) -> AuditIntegrityStatusResponse:
        events = self._ordered_events(db, tenant_id=tenant_id)
        return self._build_status(tenant_id=tenant_id, events=events)

    def verify_chain(
        self,
        db: Session,
        *,
        tenant_id: str,
        bounds: VerificationBounds | None = None,
    ) -> AuditIntegrityVerifyResponse:
        bounds = bounds or VerificationBounds()
        all_events = self._ordered_events(db, tenant_id=tenant_id)
        anchored_events = [event for event in all_events if is_audit_event_anchored(event)]
        legacy_events = [event for event in all_events if not is_audit_event_anchored(event)]
        chain_scope = build_audit_chain_scope(tenant_id)
        latest_anchored = anchored_events[-1] if anchored_events else None

        if not all_events:
            return AuditIntegrityVerifyResponse(
                tenant_id=tenant_id,
                chain_scope=chain_scope,
                hash_algorithm=AUDIT_HASH_ALGORITHM,
                status="empty",
                chain_valid=True,
                total_events=0,
                anchored_events=0,
                legacy_unanchored_events=0,
                verified_events=0,
                issues=[],
            )

        if not anchored_events:
            return AuditIntegrityVerifyResponse(
                tenant_id=tenant_id,
                chain_scope=chain_scope,
                hash_algorithm=AUDIT_HASH_ALGORITHM,
                status="legacy_only",
                chain_valid=False,
                total_events=len(all_events),
                anchored_events=0,
                legacy_unanchored_events=len(legacy_events),
                verified_events=0,
                issues=[
                    AuditIntegrityIssue(
                        code="legacy_unanchored_events_present",
                        detail="Audit events exist for this tenant, but none are currently hash anchored.",
                    )
                ],
            )

        selection = self._select_verification_window(
            all_events=all_events,
            anchored_events=anchored_events,
            tenant_id=tenant_id,
            bounds=bounds,
        )
        selected_anchored_events = selection["selected"]
        boundary_previous = selection["boundary_previous"]
        issues: list[AuditIntegrityIssue] = []

        if legacy_events:
            issues.append(
                AuditIntegrityIssue(
                    code="legacy_unanchored_events_present",
                    detail=(
                        f"{len(legacy_events)} audit event(s) for this tenant do not currently have "
                        "integrity anchors. Run backfill to anchor the full tenant history."
                    ),
                )
            )

        expected_previous_hash = boundary_previous.event_hash if boundary_previous else None
        expected_sequence = (boundary_previous.sequence_number + 1) if boundary_previous else 1

        for event in selected_anchored_events:
            recalculated_hash = compute_audit_event_hash(event)
            if event.hash_algorithm != AUDIT_HASH_ALGORITHM:
                issues.append(
                    AuditIntegrityIssue(
                        code="hash_algorithm_mismatch",
                        detail="Audit event uses an unexpected hash algorithm marker.",
                        event_id=event.id,
                        sequence_number=event.sequence_number,
                    )
                )
            if event.chain_scope != chain_scope:
                issues.append(
                    AuditIntegrityIssue(
                        code="chain_scope_mismatch",
                        detail="Audit event is linked to an unexpected chain scope.",
                        event_id=event.id,
                        sequence_number=event.sequence_number,
                    )
                )
            if event.sequence_number != expected_sequence:
                issues.append(
                    AuditIntegrityIssue(
                        code="sequence_gap",
                        detail=(
                            f"Expected sequence_number {expected_sequence} but found "
                            f"{event.sequence_number}."
                        ),
                        event_id=event.id,
                        sequence_number=event.sequence_number,
                    )
                )
            if event.previous_event_hash != expected_previous_hash:
                issues.append(
                    AuditIntegrityIssue(
                        code="previous_hash_mismatch",
                        detail="Audit event does not link to the expected previous event hash.",
                        event_id=event.id,
                        sequence_number=event.sequence_number,
                    )
                )
            if event.event_hash != recalculated_hash:
                issues.append(
                    AuditIntegrityIssue(
                        code="event_hash_mismatch",
                        detail="Audit event content no longer matches its stored hash.",
                        event_id=event.id,
                        sequence_number=event.sequence_number,
                    )
                )
            expected_previous_hash = event.event_hash
            expected_sequence = (event.sequence_number or expected_sequence) + 1

        chain_valid = not any(
            issue.code != "legacy_unanchored_events_present"
            for issue in issues
        )
        if not selected_anchored_events and legacy_events:
            status = "legacy_only"
        elif chain_valid and legacy_events:
            status = "verified_with_legacy"
        elif chain_valid:
            status = "verified"
        else:
            status = "broken"

        first_selected = selected_anchored_events[0] if selected_anchored_events else None
        last_selected = selected_anchored_events[-1] if selected_anchored_events else None

        return AuditIntegrityVerifyResponse(
            tenant_id=tenant_id,
            chain_scope=chain_scope,
            hash_algorithm=AUDIT_HASH_ALGORITHM,
            status=status,
            chain_valid=chain_valid,
            boundary_limited=selection["boundary_limited"],
            total_events=len(all_events),
            anchored_events=len(anchored_events),
            legacy_unanchored_events=len(legacy_events),
            verified_events=len(selected_anchored_events),
            first_verified_event_id=first_selected.id if first_selected else None,
            last_verified_event_id=last_selected.id if last_selected else None,
            latest_sequence_number=latest_anchored.sequence_number if latest_anchored else None,
            latest_event_id=latest_anchored.id if latest_anchored else None,
            latest_event_hash=latest_anchored.event_hash if latest_anchored else None,
            latest_anchored_at=latest_anchored.anchored_at if latest_anchored else None,
            issues=issues,
        )

    def backfill_chain(
        self,
        db: Session,
        *,
        tenant_id: str,
        dry_run: bool,
    ) -> AuditIntegrityBackfillResponse:
        events = self._ordered_events(db, tenant_id=tenant_id)
        chain_scope = build_audit_chain_scope(tenant_id)
        anchored_before = sum(1 for event in events if is_audit_event_anchored(event))
        legacy_before = len(events) - anchored_before

        previous_hash: str | None = None
        latest_event = None
        rebuilt_events = 0

        for index, event in enumerate(events, start=1):
            new_hash = compute_audit_event_hash(event)
            if (
                event.event_hash != new_hash
                or event.previous_event_hash != previous_hash
                or event.hash_algorithm != AUDIT_HASH_ALGORITHM
                or event.chain_scope != chain_scope
                or event.sequence_number != index
                or event.anchored_at is None
            ):
                rebuilt_events += 1
            if not dry_run:
                event.event_hash = new_hash
                event.previous_event_hash = previous_hash
                event.hash_algorithm = AUDIT_HASH_ALGORITHM
                event.chain_scope = chain_scope
                event.sequence_number = index
                event.anchored_at = event.anchored_at or utcnow()
            previous_hash = new_hash
            latest_event = event

        if not dry_run:
            db.flush()

        anchored_after = len(events)
        legacy_after = 0 if events else 0
        if dry_run:
            latest_sequence_number = len(events) if latest_event else None
            latest_event_id = latest_event.id if latest_event else None
            latest_event_hash = previous_hash if latest_event else None
        else:
            latest_sequence_number = latest_event.sequence_number if latest_event else None
            latest_event_id = latest_event.id if latest_event else None
            latest_event_hash = latest_event.event_hash if latest_event else None

        return AuditIntegrityBackfillResponse(
            tenant_id=tenant_id,
            chain_scope=chain_scope,
            hash_algorithm=AUDIT_HASH_ALGORITHM,
            dry_run=dry_run,
            total_events=len(events),
            rebuilt_events=rebuilt_events,
            anchored_events_before=anchored_before,
            anchored_events_after=anchored_after,
            legacy_unanchored_events_before=legacy_before,
            legacy_unanchored_events_after=legacy_after,
            latest_sequence_number=latest_sequence_number,
            latest_event_id=latest_event_id,
            latest_event_hash=latest_event_hash,
        )

    def build_bounds_from_scheduled_config(self, config) -> VerificationBounds:
        return VerificationBounds(
            start_event_id=config.start_event_id,
            end_event_id=config.end_event_id,
            start_date=config.start_date,
            end_date=config.end_date,
        )

    def enqueue_verify_job(
        self,
        db: Session,
        *,
        tenant_id: str,
        bounds: VerificationBounds,
        actor_type: AuditActorType,
        actor_id: str | None,
        ip_address: str | None,
        idempotency_key: str,
        source: str,
        scheduled_task_id: str | None,
    ) -> Job:
        job = self.job_service.enqueue(
            db,
            tenant_id=tenant_id,
            job_type=JobType.AUDIT_INTEGRITY_VERIFY_PLACEHOLDER,
            idempotency_key=idempotency_key,
            payload={
                "bounds": {
                    "start_event_id": bounds.start_event_id,
                    "end_event_id": bounds.end_event_id,
                    "start_date": bounds.start_date.isoformat() if bounds.start_date else None,
                    "end_date": bounds.end_date.isoformat() if bounds.end_date else None,
                },
                "source": source,
                "scheduled_task_id": scheduled_task_id,
                "ip_address": ip_address,
            },
            max_attempts=1,
        )
        self.audit_service.create_event(
            db,
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=AUDIT_INTEGRITY_VERIFY_QUEUED_EVENT,
            resource_type="job",
            resource_id=job.id,
            metadata={
                "job_id": job.id,
                "source": source,
                "scheduled_task_id": scheduled_task_id,
            },
            ip_address=ip_address,
        )
        return job

    def handle_verify_job(self, db: Session, *, job: Job) -> None:
        payload = job.payload or {}
        bounds_payload = payload.get("bounds") or {}
        if not isinstance(bounds_payload, dict):
            raise JobProcessingError(
                detail="Audit integrity verify job payload is invalid.",
                code="audit_integrity_verify_job_invalid",
                retryable=False,
            )
        bounds = VerificationBounds(
            start_event_id=str(bounds_payload.get("start_event_id") or "").strip() or None,
            end_event_id=str(bounds_payload.get("end_event_id") or "").strip() or None,
            start_date=self._parse_datetime(bounds_payload.get("start_date")),
            end_date=self._parse_datetime(bounds_payload.get("end_date")),
        )
        result = self.verify_chain(
            db,
            tenant_id=job.tenant_id,
            bounds=bounds,
        )
        job.payload = {
            **payload,
            "result": result.model_dump(mode="json"),
        }
        self.audit_service.create_event(
            db,
            tenant_id=job.tenant_id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type=AUDIT_INTEGRITY_VERIFY_COMPLETED_EVENT,
            resource_type="job",
            resource_id=job.id,
            metadata={
                "job_id": job.id,
                "status": result.status,
                "chain_valid": result.chain_valid,
                "verified_events": result.verified_events,
                "issues": len(result.issues),
                "source": payload.get("source"),
                "scheduled_task_id": payload.get("scheduled_task_id"),
            },
            ip_address=str(payload.get("ip_address") or "").strip() or None,
        )

    def get_job_result(self, db: Session, *, job_id: str, tenant_id: str) -> dict | None:
        job = self.job_service.get_job(db, job_id=job_id, tenant_id=tenant_id)
        if not job:
            return None
        result = (job.payload or {}).get("result")
        if not isinstance(result, dict):
            return None
        return result

    def _ordered_events(self, db: Session, *, tenant_id: str) -> list[AuditEvent]:
        return list(
            db.scalars(
                select(AuditEvent)
                .where(AuditEvent.tenant_id == tenant_id)
                .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
            )
        )

    def _build_status(self, *, tenant_id: str, events: list[AuditEvent]) -> AuditIntegrityStatusResponse:
        anchored_events = [event for event in events if is_audit_event_anchored(event)]
        legacy_count = len(events) - len(anchored_events)
        latest_anchored = anchored_events[-1] if anchored_events else None
        if not events:
            status = "empty"
        elif anchored_events and legacy_count:
            status = "anchored_with_legacy"
        elif anchored_events:
            status = "anchored"
        else:
            status = "legacy_only"
        return AuditIntegrityStatusResponse(
            tenant_id=tenant_id,
            chain_scope=build_audit_chain_scope(tenant_id),
            hash_algorithm=AUDIT_HASH_ALGORITHM,
            status=status,
            total_events=len(events),
            anchored_events=len(anchored_events),
            legacy_unanchored_events=legacy_count,
            latest_sequence_number=latest_anchored.sequence_number if latest_anchored else None,
            latest_event_id=latest_anchored.id if latest_anchored else None,
            latest_event_hash=latest_anchored.event_hash if latest_anchored else None,
            latest_anchored_at=latest_anchored.anchored_at if latest_anchored else None,
        )

    def _select_verification_window(
        self,
        *,
        all_events: list[AuditEvent],
        anchored_events: list[AuditEvent],
        tenant_id: str,
        bounds: VerificationBounds,
    ) -> dict:
        start_index = 0
        end_index = len(anchored_events) - 1
        boundary_limited = False

        if bounds.start_event_id:
            start_index = self._anchored_index_for_event(
                all_events=all_events,
                anchored_events=anchored_events,
                tenant_id=tenant_id,
                event_id=bounds.start_event_id,
            )
            boundary_limited = True
        if bounds.end_event_id:
            end_index = self._anchored_index_for_event(
                all_events=all_events,
                anchored_events=anchored_events,
                tenant_id=tenant_id,
                event_id=bounds.end_event_id,
            )
            boundary_limited = True
        if bounds.start_date:
            for index, event in enumerate(anchored_events):
                if event.created_at >= bounds.start_date:
                    start_index = max(start_index, index)
                    break
            else:
                start_index = len(anchored_events)
            boundary_limited = True
        if bounds.end_date:
            matching_index = -1
            for index, event in enumerate(anchored_events):
                if event.created_at <= bounds.end_date:
                    matching_index = index
            end_index = min(end_index, matching_index)
            boundary_limited = True

        if start_index > end_index or start_index >= len(anchored_events) or end_index < 0:
            return {
                "selected": [],
                "boundary_previous": anchored_events[start_index - 1] if start_index > 0 and start_index - 1 < len(anchored_events) else None,
                "boundary_limited": boundary_limited,
            }

        selected = anchored_events[start_index : end_index + 1]
        boundary_previous = anchored_events[start_index - 1] if start_index > 0 else None
        return {
            "selected": selected,
            "boundary_previous": boundary_previous,
            "boundary_limited": boundary_limited,
        }

    def _anchored_index_for_event(
        self,
        *,
        all_events: list[AuditEvent],
        anchored_events: list[AuditEvent],
        tenant_id: str,
        event_id: str,
    ) -> int:
        for index, event in enumerate(anchored_events):
            if event.id == event_id:
                return index

        raw_event = next((event for event in all_events if event.id == event_id), None)
        if raw_event is None:
            raise AppError(
                "Audit event not found for this tenant.",
                status_code=404,
                code="audit_integrity_event_not_found",
            )
        raise AppError(
            "The requested audit event is legacy or unanchored and cannot be used as a chain boundary until backfill runs.",
            status_code=409,
            code="audit_integrity_event_unanchored",
        )

    def _parse_datetime(self, value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise JobProcessingError(
                detail="Audit integrity verify job payload is invalid.",
                code="audit_integrity_verify_job_invalid",
                retryable=False,
            ) from exc
