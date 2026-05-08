from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import AUDIT_HASH_ALGORITHM
from app.audit.integrity import (
    build_audit_chain_scope,
    canonicalize_audit_datetime,
    compute_audit_event_hash,
    is_audit_event_anchored,
)
from app.core.config import get_settings
from app.core.enums import (
    AuditActorType,
    AuditIntegrityCheckpointStatus,
    JobType,
)
from app.core.errors import AppError
from app.core.redaction import redact_sensitive_string
from app.models import AuditEvent, AuditIntegrityCheckpoint, Job, User
from app.models.base import utcnow
from app.schemas.audit_integrity import (
    AuditIntegrityCheckpointJobResult,
    AuditIntegrityCheckpointResponse,
    AuditIntegrityCheckpointVerifyResponse,
    AuditIntegrityIssue,
)
from app.security.audit_anchoring import (
    AuditAnchorError,
    get_audit_anchor_adapter,
    get_default_audit_anchor_checkpoint_type,
)
from app.services.job_service import JobProcessingError, JobService
from app.services.payload_service import PayloadService

CHECKPOINT_HASH_ALGORITHM = "sha256_checkpoint_v1"
CHECKPOINT_DOCUMENT_VERSION = 1


@dataclass(frozen=True, slots=True)
class PreparedCheckpointRange:
    chain_scope: str
    events: list[AuditEvent]
    previous_event: AuditEvent | None
    previous_checkpoint: AuditIntegrityCheckpoint | None


class AuditIntegrityCheckpointService:
    def __init__(self) -> None:
        self.job_service = JobService()
        self.payload_service = PayloadService()

    def list_checkpoints(self, db: Session, *, tenant_id: str) -> list[AuditIntegrityCheckpointResponse]:
        checkpoints = list(
            db.scalars(
                select(AuditIntegrityCheckpoint)
                .where(AuditIntegrityCheckpoint.tenant_id == tenant_id)
                .order_by(AuditIntegrityCheckpoint.created_at.desc(), AuditIntegrityCheckpoint.id.desc())
            )
        )
        return [self.serialize_checkpoint(item) for item in checkpoints]

    def get_checkpoint_or_raise(
        self,
        db: Session,
        *,
        tenant_id: str,
        checkpoint_id: str,
    ) -> AuditIntegrityCheckpoint:
        checkpoint = db.scalar(
            select(AuditIntegrityCheckpoint).where(
                AuditIntegrityCheckpoint.id == checkpoint_id,
                AuditIntegrityCheckpoint.tenant_id == tenant_id,
            )
        )
        if not checkpoint:
            raise AppError(
                "Audit integrity checkpoint not found.",
                status_code=404,
                code="audit_integrity_checkpoint_not_found",
            )
        return checkpoint

    def serialize_checkpoint(self, checkpoint: AuditIntegrityCheckpoint) -> AuditIntegrityCheckpointResponse:
        return AuditIntegrityCheckpointResponse(
            id=checkpoint.id,
            tenant_id=checkpoint.tenant_id,
            checkpoint_type=checkpoint.checkpoint_type,
            chain_scope=checkpoint.chain_scope,
            from_sequence_number=checkpoint.from_sequence_number,
            to_sequence_number=checkpoint.to_sequence_number,
            from_event_id=checkpoint.from_event_id,
            to_event_id=checkpoint.to_event_id,
            checkpoint_hash=checkpoint.checkpoint_hash,
            previous_checkpoint_hash=checkpoint.previous_checkpoint_hash,
            event_count=checkpoint.event_count,
            destination_ref=checkpoint.destination_ref,
            status=checkpoint.status,
            created_at=checkpoint.created_at,
            anchored_at=checkpoint.anchored_at,
            metadata=self.payload_service.sanitize_payload(checkpoint.metadata_json or {}),
        )

    def enqueue_checkpoint_job(
        self,
        db: Session,
        *,
        tenant_id: str,
        requested_by: User | None,
        ip_address: str | None,
        actor_type: AuditActorType | None = None,
        actor_id: str | None = None,
        idempotency_key: str | None = None,
        source: str = "manual",
        scheduled_task_id: str | None = None,
    ) -> Job:
        del actor_type
        del actor_id
        job = self.job_service.enqueue(
            db,
            tenant_id=tenant_id,
            job_type=JobType.AUDIT_INTEGRITY_CHECKPOINT_PLACEHOLDER,
            idempotency_key=(
                idempotency_key
                or f"audit_integrity_checkpoint.placeholder:{tenant_id}:{utcnow().timestamp()}"
            ),
            payload={
                "requested_by_user_id": requested_by.id if requested_by else None,
                "ip_address": ip_address,
                "source": source,
                "scheduled_task_id": scheduled_task_id,
            },
            max_attempts=(
                1
                if self.job_service.is_inline_dispatch()
                else max(1, get_settings().job_audit_integrity_checkpoint_max_attempts)
            ),
        )
        return job

    def handle_checkpoint_job(self, db: Session, *, job: Job) -> None:
        payload = job.payload or {}
        source = str(payload.get("source") or "manual")
        scheduled_task_id = str(payload.get("scheduled_task_id") or "").strip() or None
        requested_by_user_id = str(payload.get("requested_by_user_id") or "").strip() or None
        ip_address = str(payload.get("ip_address") or "").strip() or None

        result = self._run_checkpoint(
            db,
            tenant_id=job.tenant_id,
            requested_by_user_id=requested_by_user_id,
            ip_address=ip_address,
            source=source,
            scheduled_task_id=scheduled_task_id,
        )
        job.payload = {
            **payload,
            "result": result.model_dump(mode="json"),
        }

    def get_job_result(
        self,
        db: Session,
        *,
        job_id: str,
        tenant_id: str,
    ) -> AuditIntegrityCheckpointJobResult | None:
        job = self.job_service.get_job(db, job_id=job_id, tenant_id=tenant_id)
        if not job:
            return None
        payload = job.payload or {}
        result = payload.get("result")
        if not isinstance(result, dict):
            return None
        return AuditIntegrityCheckpointJobResult.model_validate(result)

    def verify_checkpoint(
        self,
        db: Session,
        *,
        tenant_id: str,
        checkpoint_id: str,
    ) -> AuditIntegrityCheckpointVerifyResponse:
        checkpoint = self.get_checkpoint_or_raise(db, tenant_id=tenant_id, checkpoint_id=checkpoint_id)
        issues: list[AuditIntegrityIssue] = []

        if checkpoint.status != AuditIntegrityCheckpointStatus.ANCHORED or not checkpoint.checkpoint_hash:
            issues.append(
                AuditIntegrityIssue(
                    code="checkpoint_not_anchored",
                    detail="Only anchored checkpoints can be verified.",
                )
            )
            return AuditIntegrityCheckpointVerifyResponse(
                checkpoint_id=checkpoint.id,
                tenant_id=tenant_id,
                status="broken",
                chain_valid=False,
                checkpoint_hash_valid=False,
                external_anchor_valid=False,
                stored_checkpoint_hash=checkpoint.checkpoint_hash,
                recomputed_checkpoint_hash=None,
                verified_at=utcnow(),
                issues=issues,
            )

        prepared = self._prepared_range_for_checkpoint(db, checkpoint=checkpoint)
        if len(prepared.events) != checkpoint.event_count:
            issues.append(
                AuditIntegrityIssue(
                    code="checkpoint_event_count_mismatch",
                    detail=(
                        f"Expected {checkpoint.event_count} checkpoint event(s) but found "
                        f"{len(prepared.events)}."
                    ),
                )
            )
        if prepared.events:
            if prepared.events[0].id != checkpoint.from_event_id:
                issues.append(
                    AuditIntegrityIssue(
                        code="checkpoint_start_event_mismatch",
                        detail="Current checkpoint start event does not match the stored checkpoint boundary.",
                        event_id=prepared.events[0].id,
                        sequence_number=prepared.events[0].sequence_number,
                    )
                )
            if prepared.events[-1].id != checkpoint.to_event_id:
                issues.append(
                    AuditIntegrityIssue(
                        code="checkpoint_end_event_mismatch",
                        detail="Current checkpoint end event does not match the stored checkpoint boundary.",
                        event_id=prepared.events[-1].id,
                        sequence_number=prepared.events[-1].sequence_number,
                    )
                )
        range_issues = self._verify_range(
            chain_scope=prepared.chain_scope,
            events=prepared.events,
            previous_event=prepared.previous_event,
        )
        issues.extend(range_issues)
        if not prepared.events:
            return AuditIntegrityCheckpointVerifyResponse(
                checkpoint_id=checkpoint.id,
                tenant_id=tenant_id,
                status="broken",
                chain_valid=False,
                checkpoint_hash_valid=False,
                external_anchor_valid=False,
                stored_checkpoint_hash=checkpoint.checkpoint_hash,
                recomputed_checkpoint_hash=None,
                verified_at=utcnow(),
                issues=issues,
            )

        summary, event_rows = self._build_checkpoint_summary(
            tenant_id=tenant_id,
            chain_scope=prepared.chain_scope,
            events=prepared.events,
            previous_checkpoint_hash=checkpoint.previous_checkpoint_hash,
        )
        recomputed_checkpoint_hash = self._hash_dict(summary)
        checkpoint_hash_valid = recomputed_checkpoint_hash == checkpoint.checkpoint_hash
        if not checkpoint_hash_valid:
            issues.append(
                AuditIntegrityIssue(
                    code="checkpoint_hash_mismatch",
                    detail="Current checkpoint evidence no longer matches the stored checkpoint hash.",
                )
            )

        external_anchor_valid = True
        if not checkpoint.destination_ref:
            external_anchor_valid = False
            issues.append(
                AuditIntegrityIssue(
                    code="external_anchor_missing",
                    detail="The checkpoint does not reference an external anchor document.",
                )
            )
        else:
            try:
                document = get_audit_anchor_adapter(
                    checkpoint_type=checkpoint.checkpoint_type
                ).read_document(destination_ref=checkpoint.destination_ref)
                stored_document_hash = str((checkpoint.metadata_json or {}).get("document_sha256") or "").strip()
                external_document_hash = self._hash_dict(document)
                if str(document.get("checkpoint_hash") or "").strip() != checkpoint.checkpoint_hash:
                    external_anchor_valid = False
                    issues.append(
                        AuditIntegrityIssue(
                            code="external_anchor_checkpoint_hash_mismatch",
                            detail="The external checkpoint document does not match the stored checkpoint hash.",
                        )
                    )
                if stored_document_hash and external_document_hash != stored_document_hash:
                    external_anchor_valid = False
                    issues.append(
                        AuditIntegrityIssue(
                            code="external_anchor_document_hash_mismatch",
                            detail="The external checkpoint document content no longer matches the recorded document hash.",
                        )
                    )
            except AuditAnchorError as exc:
                external_anchor_valid = False
                issues.append(
                    AuditIntegrityIssue(
                        code=exc.code,
                        detail=redact_sensitive_string(exc.detail),
                    )
                )

        chain_valid = not range_issues
        return AuditIntegrityCheckpointVerifyResponse(
            checkpoint_id=checkpoint.id,
            tenant_id=tenant_id,
            status=(
                "verified"
                if chain_valid and checkpoint_hash_valid and external_anchor_valid
                else "broken"
            ),
            chain_valid=chain_valid,
            checkpoint_hash_valid=checkpoint_hash_valid,
            external_anchor_valid=external_anchor_valid,
            stored_checkpoint_hash=checkpoint.checkpoint_hash,
            recomputed_checkpoint_hash=recomputed_checkpoint_hash,
            verified_at=utcnow(),
            issues=issues,
        )

    def _run_checkpoint(
        self,
        db: Session,
        *,
        tenant_id: str,
        requested_by_user_id: str | None,
        ip_address: str | None,
        source: str,
        scheduled_task_id: str | None,
    ) -> AuditIntegrityCheckpointJobResult:
        prepared = self._prepare_next_range(db, tenant_id=tenant_id)
        if prepared is None:
            return AuditIntegrityCheckpointJobResult(
                created=False,
                status="no_new_events",
            )

        checkpoint = AuditIntegrityCheckpoint(
            tenant_id=tenant_id,
            checkpoint_type=get_default_audit_anchor_checkpoint_type(),
            chain_scope=prepared.chain_scope,
            from_sequence_number=prepared.events[0].sequence_number or 0,
            to_sequence_number=prepared.events[-1].sequence_number or 0,
            from_event_id=prepared.events[0].id,
            to_event_id=prepared.events[-1].id,
            checkpoint_hash=None,
            previous_checkpoint_hash=(
                prepared.previous_checkpoint.checkpoint_hash if prepared.previous_checkpoint else None
            ),
            event_count=len(prepared.events),
            destination_ref=None,
            status=AuditIntegrityCheckpointStatus.PENDING,
            anchored_at=None,
            metadata_json={
                "source": source,
                "scheduled_task_id": scheduled_task_id,
                "requested_by_user_id": requested_by_user_id,
                "checkpoint_hash_algorithm": CHECKPOINT_HASH_ALGORITHM,
                "event_hash_algorithm": AUDIT_HASH_ALGORITHM,
                "document_version": CHECKPOINT_DOCUMENT_VERSION,
            },
        )
        db.add(checkpoint)
        db.flush()

        try:
            issues = self._verify_range(
                chain_scope=prepared.chain_scope,
                events=prepared.events,
                previous_event=prepared.previous_event,
            )
            if issues:
                raise AppError(
                    "Audit chain verification failed for the requested checkpoint range.",
                    status_code=409,
                    code="audit_integrity_checkpoint_chain_broken",
                )

            summary, event_rows = self._build_checkpoint_summary(
                tenant_id=tenant_id,
                chain_scope=prepared.chain_scope,
                events=prepared.events,
                previous_checkpoint_hash=checkpoint.previous_checkpoint_hash,
            )
            checkpoint_hash = self._hash_dict(summary)
            document = {
                "document_version": CHECKPOINT_DOCUMENT_VERSION,
                "checkpoint_hash_algorithm": CHECKPOINT_HASH_ALGORITHM,
                "event_hash_algorithm": AUDIT_HASH_ALGORITHM,
                "generated_at": canonicalize_audit_datetime(utcnow()),
                "checkpoint": summary,
                "checkpoint_hash": checkpoint_hash,
                "events": event_rows,
            }
            document_sha256 = self._hash_dict(document)
            anchor_result = get_audit_anchor_adapter(
                checkpoint_type=checkpoint.checkpoint_type
            ).write_document(
                checkpoint_id=checkpoint.id,
                tenant_id=tenant_id,
                document=document,
            )
        except AuditAnchorError as exc:
            return self._fail_checkpoint(
                db,
                checkpoint=checkpoint,
                detail=exc.detail,
                code=exc.code,
                retryable=exc.retryable,
                ip_address=ip_address,
            )
        except AppError as exc:
            return self._fail_checkpoint(
                db,
                checkpoint=checkpoint,
                detail=exc.detail,
                code=exc.code,
                retryable=False,
                ip_address=ip_address,
            )

        checkpoint.checkpoint_hash = checkpoint_hash
        checkpoint.destination_ref = anchor_result.destination_ref
        checkpoint.status = AuditIntegrityCheckpointStatus.ANCHORED
        checkpoint.anchored_at = utcnow()
        checkpoint.metadata_json = self.payload_service.sanitize_payload(
            {
                **(checkpoint.metadata_json or {}),
                "event_hashes_digest": summary["event_hashes_digest"],
                "document_sha256": document_sha256,
                "anchor": anchor_result.metadata,
            }
        )
        return AuditIntegrityCheckpointJobResult(
            created=True,
            status="anchored",
            checkpoint_id=checkpoint.id,
            checkpoint_status=checkpoint.status,
            event_count=checkpoint.event_count,
            from_sequence_number=checkpoint.from_sequence_number,
            to_sequence_number=checkpoint.to_sequence_number,
            checkpoint_hash=checkpoint.checkpoint_hash,
        )

    def _fail_checkpoint(
        self,
        db: Session,
        *,
        checkpoint: AuditIntegrityCheckpoint,
        detail: str,
        code: str,
        retryable: bool,
        ip_address: str | None,
    ) -> AuditIntegrityCheckpointJobResult:
        redacted_detail = redact_sensitive_string(detail)
        checkpoint.status = AuditIntegrityCheckpointStatus.FAILED
        checkpoint.anchored_at = None
        checkpoint.metadata_json = self.payload_service.sanitize_payload(
            {
                **(checkpoint.metadata_json or {}),
                "error_code": code,
                "error_detail": redacted_detail,
            }
        )
        raise JobProcessingError(
            detail=redacted_detail,
            code=code,
            retryable=retryable,
            persist_state=True,
        )

    def _prepare_next_range(self, db: Session, *, tenant_id: str) -> PreparedCheckpointRange | None:
        previous_checkpoint = db.scalar(
            select(AuditIntegrityCheckpoint)
            .where(
                AuditIntegrityCheckpoint.tenant_id == tenant_id,
                AuditIntegrityCheckpoint.status == AuditIntegrityCheckpointStatus.ANCHORED,
            )
            .order_by(
                AuditIntegrityCheckpoint.to_sequence_number.desc(),
                AuditIntegrityCheckpoint.created_at.desc(),
            )
            .limit(1)
        )
        start_sequence = (previous_checkpoint.to_sequence_number + 1) if previous_checkpoint else 1
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.sequence_number.is_not(None),
                    AuditEvent.event_hash.is_not(None),
                    AuditEvent.sequence_number >= start_sequence,
                )
                .order_by(AuditEvent.sequence_number.asc(), AuditEvent.id.asc())
            )
        )
        if not events:
            return None
        previous_event = None
        if start_sequence > 1:
            previous_event = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id,
                    AuditEvent.sequence_number == start_sequence - 1,
                )
            )
        return PreparedCheckpointRange(
            chain_scope=build_audit_chain_scope(tenant_id),
            events=events,
            previous_event=previous_event,
            previous_checkpoint=previous_checkpoint,
        )

    def _prepared_range_for_checkpoint(
        self,
        db: Session,
        *,
        checkpoint: AuditIntegrityCheckpoint,
    ) -> PreparedCheckpointRange:
        events = list(
            db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.tenant_id == checkpoint.tenant_id,
                    AuditEvent.sequence_number >= checkpoint.from_sequence_number,
                    AuditEvent.sequence_number <= checkpoint.to_sequence_number,
                )
                .order_by(AuditEvent.sequence_number.asc(), AuditEvent.id.asc())
            )
        )
        previous_event = None
        if checkpoint.from_sequence_number > 1:
            previous_event = db.scalar(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == checkpoint.tenant_id,
                    AuditEvent.sequence_number == checkpoint.from_sequence_number - 1,
                )
            )
        return PreparedCheckpointRange(
            chain_scope=checkpoint.chain_scope,
            events=events,
            previous_event=previous_event,
            previous_checkpoint=None,
        )

    def _verify_range(
        self,
        *,
        chain_scope: str,
        events: list[AuditEvent],
        previous_event: AuditEvent | None,
    ) -> list[AuditIntegrityIssue]:
        issues: list[AuditIntegrityIssue] = []
        expected_previous_hash = previous_event.event_hash if previous_event else None
        expected_sequence = (previous_event.sequence_number + 1) if previous_event else 1
        for event in events:
            if not is_audit_event_anchored(event):
                issues.append(
                    AuditIntegrityIssue(
                        code="event_unanchored",
                        detail="Audit event in the checkpoint range is not currently anchored.",
                        event_id=event.id,
                        sequence_number=event.sequence_number,
                    )
                )
                continue
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
                        detail=f"Expected sequence_number {expected_sequence} but found {event.sequence_number}.",
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
            recalculated_hash = compute_audit_event_hash(event)
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
        return issues

    def _build_checkpoint_summary(
        self,
        *,
        tenant_id: str,
        chain_scope: str,
        events: list[AuditEvent],
        previous_checkpoint_hash: str | None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        event_rows = [
            {
                "event_id": event.id,
                "sequence_number": event.sequence_number,
                "event_hash": event.event_hash,
                "previous_event_hash": event.previous_event_hash,
                "anchored_at": canonicalize_audit_datetime(event.anchored_at),
                "created_at": canonicalize_audit_datetime(event.created_at),
            }
            for event in events
        ]
        event_hashes_digest = self._hash_dict({"events": event_rows})
        summary = {
            "version": 1,
            "tenant_id": tenant_id,
            "chain_scope": chain_scope,
            "checkpoint_hash_algorithm": CHECKPOINT_HASH_ALGORITHM,
            "event_hash_algorithm": AUDIT_HASH_ALGORITHM,
            "from_sequence_number": events[0].sequence_number,
            "to_sequence_number": events[-1].sequence_number,
            "from_event_id": events[0].id,
            "to_event_id": events[-1].id,
            "event_count": len(events),
            "event_hashes_digest": event_hashes_digest,
            "previous_checkpoint_hash": previous_checkpoint_hash,
        }
        return summary, event_rows

    def _hash_dict(self, payload: dict[str, Any]) -> str:
        canonical_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
