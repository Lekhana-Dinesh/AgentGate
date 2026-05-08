from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import ToolCall
from app.models.base import utcnow
from app.tests.conftest import make_token


@pytest.fixture(autouse=True)
def clear_retention_settings(monkeypatch):
    for env_key in (
        "AGENTGATE_JOB_DISPATCH_MODE",
        "AGENTGATE_JOB_BROKER",
        "AGENTGATE_GITHUB_TOKEN",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _create_protected_tool_call(client, seeded_tenants, *, token: str, agent_id: str, user_id: str, secret: str) -> str:
    response = client.post(
        "/v1/gateway/tool-call",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "agent_id": agent_id,
            "user_id": user_id,
            "original_intent": "Read the customer account safely.",
            "tool_name": "Salesforce",
            "action_name": "read_account",
            "arguments": {
                "account_id": "acc_retention_test_001",
                "access_token": secret,
                "authorization": f"Bearer {secret}",
            },
            "data_classifications": ["customer_data"],
            "metadata": {},
        },
    )
    assert response.status_code == 200
    return response.json()["tool_call_id"]


def test_retention_status_is_reviewable_but_purge_requires_owner_or_admin(client, seeded_tenants):
    admin_token = make_token(seeded_tenants["admin_a"])
    reviewer_token = make_token(seeded_tenants["reviewer_a"])
    developer_token = make_token(seeded_tenants["developer_a"])
    viewer_token = make_token(seeded_tenants["viewer_a"])
    approver_token = make_token(seeded_tenants["approver_a"])

    admin_status = client.get("/v1/retention/status", headers={"Authorization": f"Bearer {admin_token}"})
    reviewer_status = client.get("/v1/retention/status", headers={"Authorization": f"Bearer {reviewer_token}"})
    developer_status = client.get("/v1/retention/status", headers={"Authorization": f"Bearer {developer_token}"})
    reviewer_purge = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {reviewer_token}"},
        json={"dry_run": True, "limit": 5},
    )
    developer_purge = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {developer_token}"},
        json={"dry_run": True, "limit": 5},
    )
    viewer_purge = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"dry_run": True, "limit": 5},
    )
    approver_purge = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {approver_token}"},
        json={"dry_run": True, "limit": 5},
    )

    assert admin_status.status_code == 200
    assert reviewer_status.status_code == 200
    assert developer_status.status_code == 403
    assert reviewer_purge.status_code == 403
    assert developer_purge.status_code == 403
    assert viewer_purge.status_code == 403
    assert approver_purge.status_code == 403


def test_retention_dry_run_is_tenant_scoped_and_sanitized(client, seeded_tenants, db_session):
    admin_token_a = make_token(seeded_tenants["admin_a"])
    admin_token_b = make_token(seeded_tenants["admin_b"])
    secret = "ghp-retention-private-secret"
    tool_call_id = _create_protected_tool_call(
        client,
        seeded_tenants,
        token=admin_token_b,
        agent_id=seeded_tenants["agent_b"].id,
        user_id=seeded_tenants["admin_b"].id,
        secret=secret,
    )

    tool_call = db_session.scalar(select(ToolCall).where(ToolCall.id == tool_call_id))
    assert tool_call is not None
    tool_call.payload_expires_at = utcnow() - timedelta(days=1)
    db_session.commit()

    response = client.post(
        "/v1/retention/purge",
        headers={"Authorization": f"Bearer {admin_token_a}"},
        json={"dry_run": True, "tool_call_ids": [tool_call_id], "limit": 10},
    )

    assert response.status_code == 200
    assert response.json()["result"]["requested"] == 0
    assert secret not in response.text
    assert "execution_arguments" not in response.text
