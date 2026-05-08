from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AuditActorType, JobStatus, JobType
from app.models import AuditEvent, Job, Worker
from app.models.base import utcnow
from app.services.job_service import (
    JOB_DEAD_LETTERED_EVENT,
    JOB_MANUAL_RETRY_EVENT,
    JOB_STALE_RECOVERED_EVENT,
    JobService,
)
from app.services.worker_service import WorkerIdentity, WorkerService
from app.tests.conftest import make_token


@pytest.fixture(autouse=True)
def clear_job_reliability_settings(monkeypatch):
    for env_key in (
        "AGENTGATE_JOB_DISPATCH_MODE",
        "AGENTGATE_JOB_BROKER",
        "AGENTGATE_JOB_LEASE_SECONDS",
        "AGENTGATE_JOB_STALE_RECOVERY_BATCH_SIZE",
        "AGENTGATE_WORKER_ID",
        "AGENTGATE_WORKER_HEARTBEAT_INTERVAL_SECONDS",
        "AGENTGATE_WORKER_STALE_AFTER_SECONDS",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _enqueue_job(
    db_session,
    seeded_tenants,
    *,
    tenant_key: str = "tenant_a",
    job_type: JobType = JobType.APPROVAL_NOTIFICATION_SLACK,
    max_attempts: int = 3,
    idempotency_key: str = "job:test",
    payload: dict | None = None,
):
    return JobService().enqueue(
        db_session,
        tenant_id=seeded_tenants[tenant_key].id,
        job_type=job_type,
        idempotency_key=idempotency_key,
        payload=payload or {},
        max_attempts=max_attempts,
    )


def test_worker_heartbeat_creates_and_updates_worker_row(db_session):
    worker_service = WorkerService()
    identity = WorkerIdentity(worker_id="worker-a", hostname="host-a", process_id=1234)

    created = worker_service.heartbeat(
        db_session,
        identity=identity,
        metadata={"environment": "test", "secret": "ghp_should_be_sanitized"},
    )
    updated = worker_service.heartbeat(
        db_session,
        identity=identity,
        metadata={"environment": "test", "batch_size": 5},
    )

    workers = list(db_session.scalars(select(Worker).where(Worker.worker_id == "worker-a")))
    assert len(workers) == 1
    assert created.id == updated.id
    assert updated.status.value == "running"
    assert updated.metadata_json["environment"] == "test"
    assert "secret" not in str(updated.metadata_json)
    assert updated.last_heartbeat_at >= created.last_heartbeat_at


def test_job_lease_claim_prevents_double_execution(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    job = _enqueue_job(
        db_session,
        seeded_tenants,
        idempotency_key="job:lease-claim",
        payload={"approval_id": "apr_1"},
    )
    db_session.commit()

    with session_factory() as first_session:
        claimed = JobService()._claim_job_by_id(first_session, job_id=job.id, worker_id="worker-a")
        assert claimed is True

    with session_factory() as second_session:
        claimed = JobService()._claim_job_by_id(second_session, job_id=job.id, worker_id="worker-b")
        assert claimed is False

    db_session.refresh(job)
    assert job.status == JobStatus.RUNNING
    assert job.locked_by == "worker-a"
    assert job.locked_at is not None
    assert job.lease_expires_at is not None
    assert job.attempts == 1


def test_stale_retryable_job_is_requeued_safely(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_JOB_LEASE_SECONDS", "60")
    get_settings.cache_clear()

    job = _enqueue_job(
        db_session,
        seeded_tenants,
        idempotency_key="job:stale-requeue",
        payload={"approval_id": "apr_stale"},
        max_attempts=3,
    )
    db_session.commit()

    with session_factory() as claim_session:
        assert JobService()._claim_job_by_id(claim_session, job_id=job.id, worker_id="worker-a") is True

    db_session.refresh(job)
    job.lease_expires_at = utcnow() - timedelta(seconds=5)
    db_session.commit()

    recovered = JobService().recover_stale_jobs(session_factory=session_factory, limit=5)

    db_session.refresh(job)
    audit_event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == JOB_STALE_RECOVERED_EVENT))
    assert recovered == 1
    assert job.status == JobStatus.QUEUED
    assert job.dead_letter_reason is None
    assert job.locked_by is None
    assert "requeued" in (job.last_error or "").lower()
    assert audit_event is not None


def test_stale_non_retryable_approved_execution_is_dead_lettered_safely(
    db_session,
    session_factory,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    job = _enqueue_job(
        db_session,
        seeded_tenants,
        job_type=JobType.APPROVAL_EXECUTION_TOOL_CALL,
        idempotency_key="job:stale-approved-execution",
        max_attempts=1,
        payload={"approval_id": "apr_exec", "tool_call_id": "tc_exec"},
    )
    db_session.commit()

    with session_factory() as claim_session:
        assert JobService()._claim_job_by_id(claim_session, job_id=job.id, worker_id="worker-a") is True

    db_session.refresh(job)
    job.lease_expires_at = utcnow() - timedelta(seconds=5)
    db_session.commit()

    recovered = JobService().recover_stale_jobs(session_factory=session_factory, limit=5)

    db_session.refresh(job)
    audit_event = db_session.scalar(
        select(AuditEvent).where(
            AuditEvent.event_type == JOB_DEAD_LETTERED_EVENT,
            AuditEvent.resource_id == job.id,
        )
    )
    assert recovered == 1
    assert job.status == JobStatus.FAILED
    assert job.dead_letter_reason == "lease_expired_non_retryable"
    assert job.locked_by is None
    assert audit_event is not None


def test_stale_retryable_job_with_exhausted_attempts_moves_to_retry_exhausted(
    db_session,
    session_factory,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    job = _enqueue_job(
        db_session,
        seeded_tenants,
        idempotency_key="job:stale-exhausted",
        max_attempts=1,
        payload={"approval_id": "apr_exhausted"},
    )
    db_session.commit()

    with session_factory() as claim_session:
        assert JobService()._claim_job_by_id(claim_session, job_id=job.id, worker_id="worker-a") is True

    db_session.refresh(job)
    job.lease_expires_at = utcnow() - timedelta(seconds=5)
    db_session.commit()

    recovered = JobService().recover_stale_jobs(session_factory=session_factory, limit=5)

    db_session.refresh(job)
    assert recovered == 1
    assert job.status == JobStatus.RETRY_EXHAUSTED
    assert job.dead_letter_reason == "lease_expired_attempts_exhausted"


def test_retry_endpoint_enforces_rbac_and_tenant_isolation(client, seeded_tenants, db_session, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    other_tenant_token = make_token(seeded_tenants["admin_b"])

    job = _enqueue_job(
        db_session,
        seeded_tenants,
        idempotency_key="job:retry-endpoint",
        payload={"approval_id": "apr_retry"},
        max_attempts=1,
    )
    job.status = JobStatus.RETRY_EXHAUSTED
    job.dead_letter_reason = "job_processing_failed"
    job.last_error = "Terminal failure."
    job.completed_at = utcnow()
    db_session.commit()

    viewer_response = client.post(f"/v1/jobs/{job.id}/retry", headers={"Authorization": f"Bearer {viewer_token}"})
    developer_response = client.post(
        f"/v1/jobs/{job.id}/retry",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    cross_tenant_response = client.post(
        f"/v1/jobs/{job.id}/retry",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )
    reviewer_response = client.post(
        f"/v1/jobs/{job.id}/retry",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )

    db_session.refresh(job)
    audit_event = db_session.scalar(select(AuditEvent).where(AuditEvent.event_type == JOB_MANUAL_RETRY_EVENT))

    assert viewer_response.status_code == 403
    assert developer_response.status_code == 403
    assert cross_tenant_response.status_code == 404
    assert reviewer_response.status_code == 200
    assert reviewer_response.json()["status"] == "queued"
    assert job.status == JobStatus.QUEUED
    assert job.dead_letter_reason is None
    assert audit_event is not None

    admin_response = client.post(f"/v1/jobs/{job.id}/retry", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_response.status_code == 409


def test_workers_endpoints_are_safe_and_restricted(client, seeded_tenants, db_session):
    worker_service = WorkerService()
    worker_service.heartbeat(
        db_session,
        identity=WorkerIdentity(worker_id="worker-visible", hostname="host-visible", process_id=999),
        metadata={"environment": "test", "token": "ghp_should_not_leak"},
    )

    admin_token = make_token(seeded_tenants["admin_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    other_tenant_token = make_token(seeded_tenants["admin_b"])

    developer_response = client.get("/v1/workers", headers={"Authorization": f"Bearer {developer_token}"})
    list_response = client.get("/v1/workers", headers={"Authorization": f"Bearer {admin_token}"})
    status_response = client.get("/v1/workers/status", headers={"Authorization": f"Bearer {other_tenant_token}"})

    assert developer_response.status_code == 403
    assert list_response.status_code == 200
    assert status_response.status_code == 200
    assert list_response.json()[0]["worker_id"] == "worker-visible"
    assert "tenant_id" not in list_response.json()[0]
    assert "ghp_should_not_leak" not in str(list_response.json())
    assert status_response.json()["total_workers"] >= 1


def test_metrics_expose_job_reliability_aggregates_without_secrets(client, seeded_tenants, db_session):
    worker_service = WorkerService()
    worker_service.heartbeat(
        db_session,
        identity=WorkerIdentity(worker_id="worker-metrics", hostname="host-metrics", process_id=4242),
        metadata={"environment": "test", "secret": "ghp_metric_secret"},
    )
    job = _enqueue_job(
        db_session,
        seeded_tenants,
        idempotency_key="job:metrics",
        payload={"token": "ghp_metric_secret"},
        max_attempts=1,
    )
    job.status = JobStatus.RETRY_EXHAUSTED
    job.dead_letter_reason = "job_processing_failed"
    db_session.commit()

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "agentgate_workers_current" in response.text
    assert "agentgate_jobs_dead_letter_current" in response.text
    assert "agentgate_jobs_dead_letter_total" in response.text
    assert "ghp_metric_secret" not in response.text
    assert "Bearer " not in response.text
