from __future__ import annotations

import json

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models import TenantOIDCConfig
from app.notifications.slack_notifier import SlackNotifier
from app.security.key_management import get_key_provider
from app.security.payload_protection import ENCRYPTED_MARKER, LocalSymmetricPayloadEncryptionProvider
from app.security.secret_references import LocalSecretResolver, SecretResolutionError
from app.services.oidc_provider import resolve_oidc_client_secret
from app.tests.conftest import make_token
from app.tools.github_auth import EnvironmentTokenAuthProvider


@pytest.fixture(autouse=True)
def clear_key_management_caches(monkeypatch):
    for env_key in (
        "AGENTGATE_KEY_PROVIDER",
        "AGENTGATE_PAYLOAD_ENCRYPTION_KEY",
        "AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF",
        "AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF",
        "AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION",
        "AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS",
        "AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEY_VERSIONS",
        "AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS",
        "AGENTGATE_GITHUB_TOKEN",
        "AGENTGATE_SLACK_BOT_TOKEN",
        "AGENTGATE_TEST_OIDC_SECRET",
    ):
        monkeypatch.delenv(env_key, raising=False)
    get_settings.cache_clear()
    get_key_provider.cache_clear()
    yield
    get_settings.cache_clear()
    get_key_provider.cache_clear()


def test_active_key_resolution_and_envelope_metadata(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", key)
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", "payload-primary")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION", "2026-05")
    get_settings.cache_clear()
    get_key_provider.cache_clear()

    provider = LocalSymmetricPayloadEncryptionProvider()
    envelope = provider.encrypt("demo-secret")

    assert envelope[ENCRYPTED_MARKER] is True
    assert envelope["key_ref"] == "payload-primary"
    assert envelope["key_version"] == "2026-05"
    assert envelope["provider"] == "env"
    assert envelope["created_at"]
    assert provider.decrypt(envelope) == "demo-secret"


def test_payload_provider_decrypts_legacy_envelope_by_key_ref(monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    get_key_provider.cache_clear()

    ciphertext = Fernet(key.encode("utf-8")).encrypt(b"legacy-secret").decode("utf-8")
    provider = LocalSymmetricPayloadEncryptionProvider()

    legacy_envelope = {
        ENCRYPTED_MARKER: True,
        "alg": "local-fernet-v1",
        "ciphertext": ciphertext,
        "key_ref": "configured-env",
    }

    assert provider.decrypt(legacy_envelope) == "legacy-secret"


def test_additional_key_ref_can_decrypt_previous_envelopes(monkeypatch):
    current_key = Fernet.generate_key().decode("utf-8")
    previous_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", current_key)
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", "payload-2026-05")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS", previous_key)
    monkeypatch.setenv(
        "AGENTGATE_PAYLOAD_ENCRYPTION_ADDITIONAL_KEYS",
        json.dumps({"configured-env": "env:AGENTGATE_PAYLOAD_ENCRYPTION_KEY_PREVIOUS"}),
    )
    get_settings.cache_clear()
    get_key_provider.cache_clear()

    ciphertext = Fernet(previous_key.encode("utf-8")).encrypt(b"rotated-secret").decode("utf-8")
    provider = LocalSymmetricPayloadEncryptionProvider()

    legacy_envelope = {
        ENCRYPTED_MARKER: True,
        "alg": "local-fernet-v1",
        "ciphertext": ciphertext,
        "key_ref": "configured-env",
    }

    assert provider.decrypt(legacy_envelope) == "rotated-secret"


def test_invalid_or_missing_active_key_fails_closed_outside_dev_test():
    with pytest.raises(ValueError):
        Settings(
            environment="production",
            debug=False,
            secret_key="0123456789abcdef0123456789abcdef",
            key_provider="env",
            payload_encryption_key_secret_ref="secret_ref:prod/payload-protection",
        )


def test_secret_resolver_supports_env_and_rejects_invalid_refs(monkeypatch):
    monkeypatch.setenv("AGENTGATE_SECRET_SAMPLE", "sample-secret")
    resolver = LocalSecretResolver()

    resolved = resolver.resolve("env:AGENTGATE_SECRET_SAMPLE", allow_bare_env=False)
    assert resolved.value == "sample-secret"
    assert resolved.reference.display_ref == "env:AGENTGATE_SECRET_SAMPLE"

    with pytest.raises(SecretResolutionError) as exc_info:
        resolver.resolve("env:1INVALID", allow_bare_env=False)

    assert exc_info.value.code == "invalid_secret_ref"


def test_github_and_slack_env_secret_resolution_still_work(monkeypatch):
    monkeypatch.setenv("AGENTGATE_GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("AGENTGATE_SLACK_BOT_TOKEN", "xoxb-test-token")

    auth_context = EnvironmentTokenAuthProvider().get_auth_context(
        {"token_env_var": "AGENTGATE_GITHUB_TOKEN"}
    )
    slack_health = SlackNotifier().health_check(
        enabled=True,
        token_env_var="AGENTGATE_SLACK_BOT_TOKEN",
        default_channel="C123456",
        timeout_seconds=1.0,
        probe=False,
    )

    assert auth_context.token_present is True
    assert auth_context.auth_headers["Authorization"] == "Bearer ghp_test_token"
    assert auth_context.secret_reference == "env:AGENTGATE_GITHUB_TOKEN"
    assert slack_health.configured is True
    assert slack_health.status == "ready"


def test_oidc_client_secret_refs_fail_closed_without_leaking_secret_values():
    config = TenantOIDCConfig(
        tenant_id="tenant-1",
        provider_name="ExampleSSO",
        issuer_url="https://issuer.example",
        client_id="oidc-client",
        client_secret_ref="secret_ref:oidc/client",
        redirect_uri="http://localhost:8000/v1/auth/oidc/example/callback",
        scopes=["openid", "profile", "email"],
        enabled=True,
        allowed_email_domains=[],
        role_mapping={},
    )

    with pytest.raises(AppError) as exc_info:
        resolve_oidc_client_secret(config)

    assert exc_info.value.code == "oidc_secret_ref_unsupported"
    assert "oidc/client" not in exc_info.value.detail


def test_key_status_endpoint_hides_sensitive_values(client, seeded_tenants, monkeypatch):
    key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY", key)
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_ACTIVE_KEY_REF", "payload-primary")
    monkeypatch.setenv("AGENTGATE_PAYLOAD_ENCRYPTION_KEY_VERSION", "2026-05")
    get_settings.cache_clear()
    get_key_provider.cache_clear()

    token = make_token(seeded_tenants["admin_a"])
    response = client.get(
        "/v1/security/key-status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "env"
    assert payload["purposes"][0]["active_key_ref"] == "payload-primary"
    assert payload["purposes"][0]["active_key_version"] == "2026-05"
    assert key not in response.text
