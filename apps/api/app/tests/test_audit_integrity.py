from __future__ import annotations

import json

import httpx

from app.core.enums import AuditActorType
from app.models import AuditEvent
from app.models.base import utcnow
from app.services.audit_export_service import AuditExportDispatcher
from app.services.audit_integrity_service import AuditIntegrityService
from app.services.audit_service import AuditService
from app.tests.conftest import make_token


def _create_audit_event(db_session, seeded_tenants, *, tenant_key: str = "tenant_a", actor_key: str = "admin_a", note: str = "safe"):
    audit_service = AuditService()
    actor = seeded_tenants[actor_key]
    tenant = seeded_tenants[tenant_key]
    event = audit_service.create_event(
        db_session,
        tenant_id=tenant.id,
        actor_type=AuditActorType.USER,
        actor_id=actor.id,
        event_type="security.integrity.test",
        resource_type="tool_call",
        resource_id=f"tool-call-{note}",
        metadata={"note": note},
        ip_address="10.0.0.10",
    )
    db_session.commit()
    return event


def _install_audit_export_transport(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    def _build_client(self, *, timeout_seconds: float, headers: dict[str, str]):
        return httpx.Client(
            headers=headers,
            timeout=timeout_seconds,
            transport=transport,
        )

    monkeypatch.setattr(AuditExportDispatcher, "_build_client", _build_client)


def _create_export_config(client, token: str, payload: dict) -> dict:
    response = client.post(
        "/v1/audit-exports",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def test_new_audit_events_are_hash_chained(db_session, seeded_tenants):
    first = _create_audit_event(db_session, seeded_tenants, note="first")
    second = _create_audit_event(db_session, seeded_tenants, note="second")
    third = _create_audit_event(db_session, seeded_tenants, note="third")

    assert first.event_hash
    assert first.previous_event_hash is None
    assert first.sequence_number == 1
    assert first.hash_algorithm == "sha256_json_v1"
    assert first.chain_scope == f"tenant:{seeded_tenants['tenant_a'].id}"
    assert second.previous_event_hash == first.event_hash
    assert second.sequence_number == 2
    assert third.previous_event_hash == second.event_hash
    assert third.sequence_number == 3


def test_audit_chain_verifies_successfully(db_session, seeded_tenants):
    _create_audit_event(db_session, seeded_tenants, note="first")
    _create_audit_event(db_session, seeded_tenants, note="second")

    result = AuditIntegrityService().verify_chain(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
    )

    assert result.status == "verified"
    assert result.chain_valid is True
    assert result.verified_events == 2
    assert result.issues == []


def test_tampered_audit_metadata_is_detected(db_session, seeded_tenants):
    event = _create_audit_event(db_session, seeded_tenants, note="original")
    event.metadata_json = {"note": "tampered"}
    db_session.commit()

    result = AuditIntegrityService().verify_chain(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
    )

    assert result.status == "broken"
    assert any(issue.code == "event_hash_mismatch" for issue in result.issues)


def test_deleted_audit_event_is_detected_as_a_broken_chain(db_session, seeded_tenants):
    first = _create_audit_event(db_session, seeded_tenants, note="first")
    second = _create_audit_event(db_session, seeded_tenants, note="second")
    third = _create_audit_event(db_session, seeded_tenants, note="third")
    db_session.delete(second)
    db_session.commit()

    result = AuditIntegrityService().verify_chain(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
    )

    assert result.status == "broken"
    assert any(issue.code in {"sequence_gap", "previous_hash_mismatch"} for issue in result.issues)
    assert first.sequence_number == 1
    assert third.sequence_number == 3


def test_cross_tenant_audit_chains_are_isolated(db_session, seeded_tenants):
    _create_audit_event(db_session, seeded_tenants, tenant_key="tenant_a", actor_key="admin_a", note="tenant-a")
    _create_audit_event(db_session, seeded_tenants, tenant_key="tenant_b", actor_key="admin_b", note="tenant-b")

    tenant_a_result = AuditIntegrityService().verify_chain(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
    )
    tenant_b_result = AuditIntegrityService().verify_chain(
        db_session,
        tenant_id=seeded_tenants["tenant_b"].id,
    )

    assert tenant_a_result.verified_events == 1
    assert tenant_b_result.verified_events == 1
    assert tenant_a_result.tenant_id != tenant_b_result.tenant_id
    assert tenant_a_result.latest_event_hash != tenant_b_result.latest_event_hash


def test_legacy_unanchored_events_are_reported_and_can_be_backfilled(client, db_session, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    db_session.execute(
        AuditEvent.__table__.insert().values(
            id="legacy-audit-event-0000000000000001",
            tenant_id=seeded_tenants["tenant_a"].id,
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            event_type="legacy.audit.imported",
            resource_type="tenant",
            resource_id=seeded_tenants["tenant_a"].id,
            metadata={"legacy": True},
            ip_address=None,
            created_at=utcnow(),
        )
    )
    db_session.commit()
    _create_audit_event(db_session, seeded_tenants, note="anchored")

    status_response = client.get(
        "/v1/audit-integrity/status",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    verify_before = client.post(
        "/v1/audit-integrity/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    dry_run = client.post(
        "/v1/audit-integrity/backfill",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": True},
    )
    run_response = client.post(
        "/v1/audit-integrity/backfill",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )
    verify_after = client.post(
        "/v1/audit-integrity/verify",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "anchored_with_legacy"
    assert status_response.json()["legacy_unanchored_events"] == 1
    assert verify_before.status_code == 200
    assert verify_before.json()["status"] == "verified_with_legacy"
    assert dry_run.status_code == 200
    assert dry_run.json()["rebuilt_events"] >= 1
    assert run_response.status_code == 200
    assert run_response.json()["legacy_unanchored_events_after"] == 0
    assert verify_after.status_code == 200
    assert verify_after.json()["status"] == "verified"
    assert verify_after.json()["legacy_unanchored_events"] == 0


def test_audit_export_includes_safe_integrity_metadata(client, seeded_tenants, db_session, monkeypatch):
    admin_token = make_token(seeded_tenants["admin_a"])
    event = _create_audit_event(db_session, seeded_tenants, note="export")
    config = _create_export_config(
        client,
        admin_token,
        {
            "name": "Integrity Webhook",
            "destination_type": "webhook",
            "enabled": True,
            "endpoint_url": "https://siem.example.test/agentgate",
            "event_type_filters": ["security.integrity.test"],
            "max_batch_size": 100,
        },
    )

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, json={"ok": True})

    _install_audit_export_transport(monkeypatch, handler)

    run_response = client.post(
        f"/v1/audit-exports/{config['id']}/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"dry_run": False},
    )

    assert run_response.status_code == 200
    exported_event = captured_payloads[0]["events"][0]
    assert exported_event["integrity"]["event_hash"] == event.event_hash
    assert exported_event["integrity"]["previous_event_hash"] == event.previous_event_hash
    assert exported_event["integrity"]["sequence_number"] == event.sequence_number
    assert "ghp_" not in json.dumps(exported_event["integrity"])


def test_audit_integrity_endpoints_enforce_rbac_and_tenant_isolation(client, seeded_tenants, db_session):
    _create_audit_event(db_session, seeded_tenants, note="tenant-a")
    viewer_token = make_token(seeded_tenants["viewer_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    admin_b_token = make_token(seeded_tenants["admin_b"])

    viewer_status = client.get(
        "/v1/audit-integrity/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    viewer_verify = client.post(
        "/v1/audit-integrity/verify",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={},
    )
    viewer_backfill = client.post(
        "/v1/audit-integrity/backfill",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"dry_run": True},
    )
    reviewer_status = client.get(
        "/v1/audit-integrity/status",
        headers={"Authorization": f"Bearer {reviewer_token}"},
    )
    tenant_b_status = client.get(
        "/v1/audit-integrity/status",
        headers={"Authorization": f"Bearer {admin_b_token}"},
    )

    assert viewer_status.status_code == 403
    assert viewer_verify.status_code == 403
    assert viewer_backfill.status_code == 403
    assert reviewer_status.status_code == 200
    assert reviewer_status.json()["tenant_id"] == seeded_tenants["tenant_a"].id
    assert tenant_b_status.status_code == 200
    assert tenant_b_status.json()["tenant_id"] == seeded_tenants["tenant_b"].id
    assert tenant_b_status.json()["total_events"] == 0
