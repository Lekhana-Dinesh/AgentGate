from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import (
    AuditActorType,
    AuditIntegrityCheckpointStatus,
    AuditIntegrityCheckpointType,
    JobStatus,
)
from app.models import AuditIntegrityCheckpoint, Job
from app.schemas.audit_integrity import AuditIntegrityCheckpointVerifyResponse
from app.services.audit_integrity_checkpoint_service import AuditIntegrityCheckpointService
from app.services.audit_service import AuditService
from app.security.audit_anchoring import AuditAnchorError
from app.tests.conftest import make_token


def _create_audit_event(
    db_session,
    seeded_tenants,
    *,
    tenant_key: str = "tenant_a",
    actor_key: str = "admin_a",
    note: str = "safe",
    metadata: dict | None = None,
):
    audit_service = AuditService()
    actor = seeded_tenants[actor_key]
    tenant = seeded_tenants[tenant_key]
    event = audit_service.create_event(
        db_session,
        tenant_id=tenant.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        event_type="security.integrity.checkpoint",
        resource_type="tool_call",
        resource_id=f"tool-call-{note}",
        metadata=metadata or {"note": note},
        ip_address="10.0.0.20",
    )
    db_session.commit()
    return event


def _create_checkpoint(client, token: str) -> dict:
    response = client.post(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _local_anchor_dir(name: str) -> Path:
    return (Path(".tmp") / "audit-integrity-checkpoints-tests" / name).resolve()


def test_checkpoint_creation_writes_safe_external_document(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    local_dir = _local_anchor_dir("create")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "local")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH", str(local_dir))
    get_settings.cache_clear()

    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants, note="first")
    _create_audit_event(db_session, seeded_tenants, note="second")

    run_response = _create_checkpoint(client, admin_token)
    checkpoints_response = client.get(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert run_response["dispatch_mode"] == "inline"
    assert run_response["result"]["created"] is True
    assert run_response["result"]["status"] == "anchored"
    assert checkpoints_response.status_code == 200
    assert len(checkpoints_response.json()) == 1

    checkpoint_payload = checkpoints_response.json()[0]
    assert checkpoint_payload["checkpoint_type"] == "local"
    assert checkpoint_payload["status"] == "anchored"
    assert checkpoint_payload["event_count"] == 2
    assert checkpoint_payload["checkpoint_hash"]
    assert checkpoint_payload["destination_ref"].startswith("local://audit-integrity/")

    relative_ref = checkpoint_payload["destination_ref"].split("local://audit-integrity/", 1)[1]
    document_path = (local_dir / Path(relative_ref)).resolve()
    assert document_path.exists()
    document_text = document_path.read_text(encoding="utf-8")
    assert "ghp_" not in document_text
    assert '"events"' in document_text

    verify_response = client.post(
        f"/v1/audit-integrity/checkpoints/{checkpoint_payload['id']}/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    assert verify_response.status_code == 200
    assert AuditIntegrityCheckpointVerifyResponse.model_validate(verify_response.json()).status == "verified"


def test_tampered_chain_blocks_checkpoint_and_persists_failed_attempt(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "local")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH", str(_local_anchor_dir("tampered")))
    get_settings.cache_clear()

    admin_token = make_token(seeded_tenants["admin_a"])
    event = _create_audit_event(db_session, seeded_tenants, note="tampered")
    event.metadata_json = {"note": "tampered-after-anchor"}
    db_session.commit()

    response = client.post(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    checkpoints = list(
        db_session.scalars(
            select(AuditIntegrityCheckpoint).where(
                AuditIntegrityCheckpoint.tenant_id == seeded_tenants["tenant_a"].id
            )
        )
    )

    assert response.status_code == 409
    assert checkpoints
    assert checkpoints[0].status == AuditIntegrityCheckpointStatus.FAILED
    assert checkpoints[0].checkpoint_hash is None
    assert checkpoints[0].destination_ref is None


def test_checkpoint_hash_is_deterministic(db_session, seeded_tenants):
    _create_audit_event(db_session, seeded_tenants, note="one")
    _create_audit_event(db_session, seeded_tenants, note="two")

    service = AuditIntegrityCheckpointService()
    prepared = service._prepare_next_range(db_session, tenant_id=seeded_tenants["tenant_a"].id)
    assert prepared is not None

    summary_one, event_rows_one = service._build_checkpoint_summary(
        tenant_id=seeded_tenants["tenant_a"].id,
        chain_scope=prepared.chain_scope,
        events=prepared.events,
        previous_checkpoint_hash=None,
    )
    summary_two, event_rows_two = service._build_checkpoint_summary(
        tenant_id=seeded_tenants["tenant_a"].id,
        chain_scope=prepared.chain_scope,
        events=prepared.events,
        previous_checkpoint_hash=None,
    )

    assert summary_one == summary_two
    assert event_rows_one == event_rows_two
    assert service._hash_dict(summary_one) == service._hash_dict(summary_two)


def test_checkpoint_endpoints_are_tenant_scoped_and_rbac_restricted(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "local")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH", str(_local_anchor_dir("rbac")))
    get_settings.cache_clear()

    _create_audit_event(db_session, seeded_tenants, note="tenant-a")
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    admin_b_token = make_token(seeded_tenants["admin_b"])

    checkpoint_id = _create_checkpoint(client, admin_token)["result"]["checkpoint_id"]

    viewer_create = client.post(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={},
    )
    reviewer_list = client.get(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    other_tenant_get = client.get(
        f"/v1/audit-integrity/checkpoints/{checkpoint_id}",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )
    other_tenant_verify = client.post(
        f"/v1/audit-integrity/checkpoints/{checkpoint_id}/verify",
        headers={"Authorization": f"Bearer {admin_b_token}"},
        json={},
    )

    assert viewer_create.status_code == 403
    assert reviewer_list.status_code == 200
    assert len(reviewer_list.json()) == 1
    assert other_tenant_get.status_code == 404
    assert other_tenant_verify.status_code == 404


def test_checkpoint_payloads_and_api_responses_do_not_leak_secrets(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "local")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH", str(_local_anchor_dir("secrets")))
    get_settings.cache_clear()

    admin_token = make_token(seeded_tenants["admin_a"])
    raw_secret = "ghp_secret_should_not_leak"
    _create_audit_event(
        db_session,
        seeded_tenants,
        note="secret-test",
        metadata={"token": raw_secret, "note": "secret-test"},
    )

    run_response = _create_checkpoint(client, admin_token)
    list_response = client.get(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert raw_secret not in str(run_response)
    assert raw_secret not in list_response.text
    assert "access_key" not in list_response.text.lower()


def test_object_storage_checkpoint_adapter_success_is_mockable(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "object_storage")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET", "agentgate-audit")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_REGION", "us-east-1")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_ENDPOINT_URL", "http://minio.local")
    get_settings.cache_clear()

    class FakeS3Client:
        def put_object(self, **kwargs):
            assert kwargs["Bucket"] == "agentgate-audit"
            assert kwargs["Key"].startswith("agentgate/audit-integrity/")
            return {"ETag": '"etag-123"', "VersionId": "version-1"}

        def get_object(self, **kwargs):
            raise AssertionError("get_object should not be called during create")

    monkeypatch.setattr(
        "app.security.audit_anchoring.S3AuditAnchorAdapter._client",
        lambda self: FakeS3Client(),
    )

    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants, note="object-storage")
    response = _create_checkpoint(client, admin_token)
    checkpoint = db_session.scalar(
        select(AuditIntegrityCheckpoint).where(
            AuditIntegrityCheckpoint.id == response["result"]["checkpoint_id"]
        )
    )

    assert checkpoint is not None
    assert checkpoint.checkpoint_type == AuditIntegrityCheckpointType.OBJECT_STORAGE
    assert checkpoint.destination_ref == f"s3://agentgate-audit/agentgate/audit-integrity/{seeded_tenants['tenant_a'].id}/{checkpoint.id}.json"


def test_object_storage_checkpoint_adapter_failure_is_mockable(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "object_storage")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET", "agentgate-audit")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_REGION", "us-east-1")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_S3_ENDPOINT_URL", "http://minio.local")
    get_settings.cache_clear()

    class FakeS3Client:
        def put_object(self, **kwargs):
            raise AuditAnchorError(
                detail="Checkpoint object storage is temporarily unavailable.",
                code="audit_integrity_anchor_unavailable",
                retryable=True,
            )

    monkeypatch.setattr(
        "app.security.audit_anchoring.S3AuditAnchorAdapter._client",
        lambda self: FakeS3Client(),
    )

    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants, note="object-storage-failure")

    response = client.post(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )

    checkpoints = list(
        db_session.scalars(
            select(AuditIntegrityCheckpoint).where(
                AuditIntegrityCheckpoint.tenant_id == seeded_tenants["tenant_a"].id
            )
        )
    )

    assert response.status_code == 503
    assert checkpoints
    assert checkpoints[0].status == AuditIntegrityCheckpointStatus.FAILED


def test_checkpoint_job_can_be_queued_and_executed_in_worker_mode(
    client,
    db_session,
    seeded_tenants,
    monkeypatch,
):
    monkeypatch.setenv("AGENTGATE_JOB_DISPATCH_MODE", "worker")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE", "local")
    monkeypatch.setenv("AGENTGATE_AUDIT_INTEGRITY_LOCAL_PATH", str(_local_anchor_dir("worker")))
    get_settings.cache_clear()

    admin_token = make_token(seeded_tenants["admin_a"])
    _create_audit_event(db_session, seeded_tenants, note="queued")
    response = client.post(
        "/v1/audit-integrity/checkpoints",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    assert response.status_code == 200
    assert response.json()["dispatch_mode"] == "worker"
    assert response.json()["job"]["status"] == "queued"
    assert response.json()["result"] is None

    job_id = response.json()["job"]["id"]
    job = AuditIntegrityCheckpointService().job_service.process_job(db_session, job_id=job_id)
    checkpoint = db_session.scalar(
        select(AuditIntegrityCheckpoint).where(AuditIntegrityCheckpoint.tenant_id == seeded_tenants["tenant_a"].id)
    )

    assert job is not None
    assert job.status == JobStatus.SUCCEEDED
    assert checkpoint is not None
    assert checkpoint.status == AuditIntegrityCheckpointStatus.ANCHORED
