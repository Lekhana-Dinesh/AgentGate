from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import JobType
from app.services.audit_export_service import AuditExportService
from app.services.audit_integrity_checkpoint_service import AuditIntegrityCheckpointService
from app.services.approved_execution_service import ApprovedExecutionService
from app.services.audit_integrity_service import AuditIntegrityService
from app.services.notification_service import NotificationService
from app.services.retention_service import RetentionService
from app.services.tool_health_service import ToolHealthService


def dispatch_job(db: Session, job) -> None:
    if job.job_type == JobType.APPROVAL_NOTIFICATION_SLACK:
        NotificationService().handle_slack_approval_notification_job(db, job=job)
        return
    if job.job_type == JobType.APPROVAL_EXECUTION_TOOL_CALL:
        ApprovedExecutionService().handle_tool_call_execution_job(db, job=job)
        return
    if job.job_type == JobType.RETENTION_PURGE_PLACEHOLDER:
        RetentionService().handle_retention_purge_job(db, job=job)
        return
    if job.job_type in {
        JobType.AUDIT_EXPORT_PLACEHOLDER,
    }:
        AuditExportService().handle_audit_export_job(db, job=job)
        return
    if job.job_type == JobType.AUDIT_INTEGRITY_VERIFY_PLACEHOLDER:
        AuditIntegrityService().handle_verify_job(db, job=job)
        return
    if job.job_type == JobType.AUDIT_INTEGRITY_CHECKPOINT_PLACEHOLDER:
        AuditIntegrityCheckpointService().handle_checkpoint_job(db, job=job)
        return
    if job.job_type == JobType.CONNECTOR_HEALTH_CHECK_PLACEHOLDER:
        ToolHealthService().handle_connector_health_check_job(db, job=job)
        return
    raise ValueError(f"Unsupported job type: {job.job_type}")


def dispatch_job_retry_exhausted(db: Session, job) -> None:
    if job.job_type == JobType.APPROVAL_NOTIFICATION_SLACK:
        NotificationService().handle_slack_retry_exhausted(db, job=job)
        return
    if job.job_type == JobType.AUDIT_EXPORT_PLACEHOLDER:
        AuditExportService().handle_audit_export_retry_exhausted(db, job=job)
