from __future__ import annotations

from datetime import timedelta

from cryptography.fernet import Fernet

from app.core.config import get_settings
from app.core.enums import AuditActorType, AuditExportDestinationType
from app.models import AuditExportConfig, TenantOIDCConfig
from app.models.base import utcnow
from app.schemas.scheduled_task import ScheduledTaskCreate
from app.services.scheduled_task_service import ScheduledTaskService
from app.tests.conftest import make_token


def test_settings_overview_rbac(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    approver_token = make_token(seeded_tenants["approver_a"])

    admin_response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {admin_token}"})
    reviewer_response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {reviewer_token}"})
    developer_response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {developer_token}"})
    viewer_response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {viewer_token}"})
    approver_response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {approver_token}"})

    assert admin_response.status_code == 200
    assert reviewer_response.status_code == 200
    assert developer_response.status_code == 403
    assert viewer_response.status_code == 403
    assert approver_response.status_code == 403


def test_settings_overview_is_safe_and_tenant_scoped(client, db_session, seeded_tenants, monkeypatch):
    github_secret = "ghp_settings_should_not_leak"
    slack_secret = "xoxb-settings-should-not-leak"
    oidc_secret = "oidc-settings-should-not-leak"

    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", github_secret)
    monkeypatch.setenv("AGENTGATE_SLACK_NOTIFICATIONS_ENABLED", "true")
    monkeypatch.setenv("AGENTGATE_SLACK_DEFAULT_CHANNEL", "C123456")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", slack_secret)
    monkeypatch.setenv("AGENTGATE_TEST_OIDC_SECRET", oidc_secret)
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode("utf-8"))
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", "payload-primary")
    get_settings.cache_clear()

    oidc_config = TenantOIDCConfig(
        tenant_id=seeded_tenants["tenant_a"].id,
        provider_name="ExampleSSO",
        issuer_url="https://issuer.example",
        client_id="oidc-client-123",
        client_secret_env_var="AGENTGATE_TEST_OIDC_SECRET",
        redirect_uri=f"http://localhost:8000/v1/auth/oidc/{seeded_tenants['tenant_a'].slug}/callback",
        scopes=["openid", "profile", "email"],
        enabled=True,
        allowed_email_domains=[],
        role_mapping={},
    )
    export_config = AuditExportConfig(
        tenant_id=seeded_tenants["tenant_a"].id,
        name="Primary SIEM",
        destination_type=AuditExportDestinationType.WEBHOOK,
        enabled=True,
        endpoint_url="https://siem.example.test/agentgate",
        secret_ref=None,
        token_env_var=None,
        event_type_filters=[],
        severity_filters=[],
        max_batch_size=100,
        last_export_status=None,
        last_error=None,
    )
    db_session.add_all([oidc_config, export_config])
    db_session.flush()

    ScheduledTaskService().create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate(
            {
                "name": "Recurring Retention",
                "task_type": "retention_purge",
                "enabled": True,
                "schedule_kind": "interval",
                "interval_seconds": 300,
                "next_run_at": utcnow() - timedelta(minutes=5),
                "config": {"dry_run": True, "limit": 25},
            }
        ),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()

    admin_token = make_token(seeded_tenants["admin_a"])
    response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"]["id"] == seeded_tenants["tenant_a"].id
    assert payload["tenant"]["slug"] == seeded_tenants["tenant_a"].slug
    assert payload["tenant"]["github_connector_count"] == 1
    assert payload["oidc"]["status"] == "ready"
    assert payload["oidc"]["provider_name"] == "ExampleSSO"
    assert payload["github_connectors"]["total"] == 1
    assert payload["github_connectors"]["connectors"][0]["name"] == "GitHub"
    assert payload["github_connectors"]["connectors"][0]["token_present"] is True
    assert payload["slack"]["status"] == "ready"
    assert payload["audit_exports"]["total"] == 1
    assert payload["audit_exports"]["configs"][0]["endpoint_host"] == "siem.example.test"
    assert payload["scheduled_tasks"]["total"] == 1
    assert payload["scheduled_tasks"]["due"] == 1
    assert payload["retention"]["policy"]["standard_days"] >= 1
    assert payload["keys"]["provider"] == "env"
    assert payload["keys"]["readiness"] == "ready"
    assert payload["rate_limiter"]["provider"] in {"in_memory", "redis"}
    assert payload["links"]["readiness_url"].endswith("/ready")
    assert payload["links"]["metrics_url"].endswith("/metrics")

    assert github_secret not in response.text
    assert slack_secret not in response.text
    assert oidc_secret not in response.text
    assert "AGENTGATE_GITHUB_TOKEN" not in response.text
    assert "AGENTGATE_TEST_OIDC_SECRET" not in response.text
    assert "client_secret_env_var" not in response.text


def test_settings_overview_does_not_leak_other_tenant_state(client, db_session, seeded_tenants):
    export_config = AuditExportConfig(
        tenant_id=seeded_tenants["tenant_a"].id,
        name="Tenant A Only Export",
        destination_type=AuditExportDestinationType.WEBHOOK,
        enabled=True,
        endpoint_url="https://siem.example.test/tenant-a",
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
    ScheduledTaskService().create_task(
        db_session,
        tenant_id=seeded_tenants["tenant_a"].id,
        payload=ScheduledTaskCreate.model_validate(
            {
                "name": "Tenant A Scheduled Task",
                "task_type": "retention_purge",
                "enabled": True,
                "schedule_kind": "interval",
                "interval_seconds": 600,
                "config": {"dry_run": True},
            }
        ),
        actor_type=AuditActorType.SYSTEM,
        actor_id=None,
        ip_address=None,
    )
    db_session.commit()

    tenant_b_token = make_token(seeded_tenants["admin_b"])
    response = client.get("/v1/settings/overview", headers={"Authorization": f"Bearer {tenant_b_token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"]["id"] == seeded_tenants["tenant_b"].id
    assert payload["tenant"]["slug"] == seeded_tenants["tenant_b"].slug
    assert payload["github_connectors"]["total"] == 0
    assert payload["audit_exports"]["total"] == 0
    assert payload["scheduled_tasks"]["total"] == 0
    assert "Tenant A Only Export" not in response.text
    assert "Tenant A Scheduled Task" not in response.text
    assert seeded_tenants["tenant_a"].id not in response.text
