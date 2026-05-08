from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AuditActorType, AuditExportDestinationType, JobStatus, JobType
from app.models import AuditExportConfig, Job
from app.models.base import utcnow
from app.schemas.scheduled_task import ScheduledTaskCreate
from app.services.scheduled_task_service import (
    SCHEDULED_TASK_STATUS_DUPLICATE,
    SCHEDULED_TASK_STATUS_ENQUEUED,
    SCHEDULED_TASK_STATUS_FAILED,
    ScheduledTaskService,
)
from app.tests.conftest import make_token


@pytest.fixture(autouse=True)
def clear_scheduler_settings(monkeypatch):
    for env_key in (
        "AGENTGATE_JOB_DISPATCH_MODE",
        "AGENTGATE_JOB_BROKER",
        "AGENTGATE_SCHEDULER_POLL_INTERVAL_SECONDS",
        "AGENTGATE_SCHEDULER_BATCH_SIZE",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _create_scheduled_task(client, token: str, payload: dict) -> dict:
    response = client.post(
        "/v1/scheduled-tasks",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def test_create_scheduled_task(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])

    response = client.post(
        "/v1/scheduled-tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Recurring Retention Dry Run",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 3600,
            "config": {"dry_run": True, "limit": 50},
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["task_type"] == "retention_purge"
    assert payload["schedule_kind"] == "interval"
    assert payload["config"]["dry_run"] is True
    assert payload["last_status"] == "idle"


def test_due_task_enqueues_correct_job(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    task = ScheduledTaskService().create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate({
            "name": "Retention Queue",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "next_run_at": utcnow() - timedelta(minutes=5),
            "config": {"dry_run": True, "limit": 10},
        }),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()

    processed = ScheduledTaskService().process_due_tasks(
        session_factory=session_factory,
        limit=5,
        scheduler_id="scheduler-test",
    )

    job = db_session.scalar(
        select(Job).where(
            Job.tenant_id == seeded_tenants["tenant_a"].id,
            Job.job_type == JobType.RETENTION_PURGE_PLACEHOLDER,
        )
    )
    db_session.refresh(task)

    assert processed == 1
    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert job.payload["scheduled_task_id"] == task.id
    assert task.last_status == SCHEDULED_TASK_STATUS_ENQUEUED


def test_disabled_task_does_not_run(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    task = ScheduledTaskService().create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate({
            "name": "Disabled Retention",
            "task_type": "retention_purge",
            "enabled": False,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "next_run_at": utcnow() - timedelta(minutes=5),
            "config": {"dry_run": True, "limit": 10},
        }),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()

    processed = ScheduledTaskService().process_due_tasks(
        session_factory=session_factory,
        limit=5,
        scheduler_id="scheduler-test",
    )

    jobs = list(db_session.scalars(select(Job).where(Job.tenant_id == seeded_tenants["tenant_a"].id)))
    db_session.refresh(task)

    assert processed == 0
    assert jobs == []
    assert task.last_status == "idle"


def test_run_now_enqueues_job(client, seeded_tenants, db_session, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()
    admin_token = make_token(seeded_tenants["admin_a"])
    task = _create_scheduled_task(
        client,
        admin_token,
        {
            "name": "Manual Integrity Verify",
            "task_type": "audit_integrity_verify",
            "enabled": False,
            "schedule_kind": "interval",
            "interval_seconds": 900,
            "config": {},
        },
    )

    response = client.post(
        f"/v1/scheduled-tasks/{task['id']}/run-now",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    job = db_session.scalar(select(Job).where(Job.id == response.json()["job"]["id"]))
    assert response.status_code == 200
    assert response.json()["job"]["job_type"] == "audit_integrity_verify.placeholder"
    assert response.json()["job"]["status"] == "queued"
    assert job is not None
    assert job.payload["scheduled_task_id"] == task["id"]


def test_run_now_enqueues_audit_integrity_checkpoint_job(client, seeded_tenants, db_session, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()
    admin_token = make_token(seeded_tenants["admin_a"])
    task = _create_scheduled_task(
        client,
        admin_token,
        {
            "name": "Manual Integrity Checkpoint",
            "task_type": "audit_integrity_checkpoint",
            "enabled": False,
            "schedule_kind": "interval",
            "interval_seconds": 900,
            "config": {},
        },
    )

    response = client.post(
        f"/v1/scheduled-tasks/{task['id']}/run-now",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    job = db_session.scalar(select(Job).where(Job.id == response.json()["job"]["id"]))
    assert response.status_code == 200
    assert response.json()["job"]["job_type"] == "audit_integrity_checkpoint.placeholder"
    assert response.json()["job"]["status"] == "queued"
    assert job is not None
    assert job.payload["scheduled_task_id"] == task["id"]


def test_duplicate_enqueue_is_prevented(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()
    service = ScheduledTaskService()
    task = service.create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate({
            "name": "Overlap Guard",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "next_run_at": utcnow() - timedelta(minutes=5),
            "config": {"dry_run": True, "limit": 10},
        }),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()

    assert service.process_due_tasks(session_factory=session_factory, limit=5, scheduler_id="scheduler-test") == 1
    db_session.refresh(task)
    task.next_run_at = utcnow() - timedelta(minutes=1)
    db_session.commit()

    assert service.process_due_tasks(session_factory=session_factory, limit=5, scheduler_id="scheduler-test") == 1
    db_session.refresh(task)
    jobs = list(
        db_session.scalars(
            select(Job).where(
                Job.tenant_id == seeded_tenants["tenant_a"].id,
                Job.job_type == JobType.RETENTION_PURGE_PLACEHOLDER,
            )
        )
    )

    assert len(jobs) == 1
    assert task.last_status == SCHEDULED_TASK_STATUS_DUPLICATE
    assert task.last_run_at is not None
    assert task.next_run_at > task.last_run_at


def test_tenant_isolation_and_rbac_for_scheduled_tasks(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    approver_token = make_token(seeded_tenants["approver_a"])
    other_tenant_token = make_token(seeded_tenants["admin_b"])

    task = _create_scheduled_task(
        client,
        admin_token,
        {
            "name": "Tenant A Retention",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 3600,
            "config": {"dry_run": True},
        },
    )

    reviewer_list = client.get("/v1/scheduled-tasks", headers={"Authorization": f"Bearer {reviewer_token}"})
    reviewer_update = client.patch(
        f"/v1/scheduled-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"enabled": False},
    )
    reviewer_run = client.post(
        f"/v1/scheduled-tasks/{task['id']}/run-now",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    developer_list = client.get("/v1/scheduled-tasks", headers={"Authorization": f"Bearer {developer_token}"})
    developer_run = client.post(
        f"/v1/scheduled-tasks/{task['id']}/run-now",
        headers={"Authorization": f"Bearer {developer_token}"},
    )
    viewer_create = client.post(
        "/v1/scheduled-tasks",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "name": "Viewer Attempt",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "config": {"dry_run": True},
        },
    )
    approver_update = client.patch(
        f"/v1/scheduled-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"enabled": False},
    )
    other_tenant_get = client.get(
        f"/v1/scheduled-tasks/{task['id']}",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )
    other_tenant_run = client.post(
        f"/v1/scheduled-tasks/{task['id']}/run-now",
        headers={"Authorization": f"Bearer {other_tenant_token}"},
    )

    assert reviewer_list.status_code == 200
    assert any(item["id"] == task["id"] for item in reviewer_list.json())
    assert reviewer_update.status_code == 403
    assert reviewer_run.status_code == 403
    assert developer_list.status_code == 403
    assert developer_run.status_code == 403
    assert viewer_create.status_code == 403
    assert approver_update.status_code == 403
    assert other_tenant_get.status_code == 404
    assert other_tenant_run.status_code == 404


def test_task_config_does_not_expose_secrets(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    raw_secret = "ghp-should-not-be-stored"

    response = client.post(
        "/v1/scheduled-tasks",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "name": "Unsafe Config",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "config": {"token": raw_secret},
        },
    )

    assert response.status_code == 422
    assert raw_secret not in response.text


def test_next_run_at_advances_after_enqueue(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()
    service = ScheduledTaskService()
    task = service.create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate({
            "name": "Advance Interval",
            "task_type": "retention_purge",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "next_run_at": utcnow() - timedelta(minutes=5),
            "config": {"dry_run": True, "limit": 10},
        }),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()
    previous_next_run = task.next_run_at

    assert service.process_due_tasks(session_factory=session_factory, limit=5, scheduler_id="scheduler-test") == 1

    db_session.refresh(task)
    assert task.next_run_at > previous_next_run
    assert task.last_run_at is not None


def test_scheduler_handles_failure_safely(db_session, session_factory, seeded_tenants, monkeypatch):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    get_settings.cache_clear()

    export_config = AuditExportConfig(
        tenant_id=seeded_tenants["tenant_a"].id,
        name="Disabled Export",
        destination_type=AuditExportDestinationType.WEBHOOK,
        enabled=False,
        endpoint_url="https://siem.example.test/agentgate",
        secret_ref=None,
        token_env_var=None,
        event_type_filters=[],
        severity_filters=[],
        max_batch_size=100,
        last_export_status=None,
        last_error=None,
    )
    db_session.add(export_config)
    db_session.flush()

    service = ScheduledTaskService()
    task = service.create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate({
            "name": "Failing Export",
            "task_type": "audit_export",
            "enabled": True,
            "schedule_kind": "interval",
            "interval_seconds": 300,
            "next_run_at": utcnow() - timedelta(minutes=5),
            "config": {"audit_export_config_id": export_config.id, "dry_run": False},
        }),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()
    previous_next_run = task.next_run_at

    processed = service.process_due_tasks(
        session_factory=session_factory,
        limit=5,
        scheduler_id="scheduler-test",
    )

    db_session.refresh(task)
    jobs = list(db_session.scalars(select(Job).where(Job.tenant_id == seeded_tenants["tenant_a"].id)))

    assert processed == 1
    assert jobs == []
    assert task.last_status == SCHEDULED_TASK_STATUS_FAILED
    assert "disabled" in (task.last_error or "").lower()
    assert task.next_run_at > previous_next_run
