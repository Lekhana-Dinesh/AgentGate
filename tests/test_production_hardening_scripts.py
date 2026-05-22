from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(module_name: str, relative_path: str):
    target = REPO_ROOT / relative_path
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Could not load script module {relative_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_repo_temp_env(contents: str) -> Path:
    import os

    fd, raw_path = tempfile.mkstemp(prefix="agentgate-recovery-", suffix=".env", dir=REPO_ROOT)
    path = Path(raw_path)
    os.close(fd)
    path.write_text(contents, encoding="utf-8")
    return path


def test_validate_deployment_redacts_evidence_summary(capsys):
    module = _load_script_module("validate_deployment_script", "scripts/validate-deployment.py")
    config = module.ValidationConfig(
        api_url="https://api.agentgate.example.com",
        web_url="https://agentgate.example.com",
        email="owner@example.com",
        password="super-secret-password",
        tenant_slug="customer-pilot",
        timeout_seconds=5.0,
        retries=0,
        retry_delay_seconds=0.0,
        metrics_mode="auto",
    )
    validator = module.DeploymentValidator(config)
    validator.secrets.append("ghp_super_secret_token")
    validator.evidence["operator"]["last_error"] = "Bearer ghp_super_secret_token"
    validator.evidence["github_connectors"] = {
        "connectors": [{"status_summary": "token ghp_super_secret_token was used"}]
    }

    validator.emit_evidence_summary()
    captured = capsys.readouterr().out

    assert "[evidence]" in captured
    assert "super-secret-password" not in captured
    assert "ghp_super_secret_token" not in captured
    assert "[REDACTED]" in captured


def test_validate_deployment_skips_github_readiness_honestly_when_connector_absent(capsys):
    module = _load_script_module("validate_deployment_script_skip", "scripts/validate-deployment.py")
    config = module.ValidationConfig(
        api_url="https://api.agentgate.example.com",
        web_url="https://agentgate.example.com",
        email="owner@example.com",
        password="super-secret-password",
        tenant_slug="customer-pilot",
        timeout_seconds=5.0,
        retries=0,
        retry_delay_seconds=0.0,
        metrics_mode="auto",
    )
    validator = module.DeploymentValidator(config)
    validator.tools_summary_cache = [{"id": "jira-1", "type": "jira", "name": "Jira"}]

    validator.check_github_connector_readiness("GitHub connector readiness")
    captured = capsys.readouterr().out

    assert "[skip] GitHub connector readiness" in captured
    assert validator.evidence["github_connectors"]["status"] == "skipped"
    assert "No GitHub connectors are configured" in validator.evidence["github_connectors"]["note"]


def test_run_pilot_rehearsal_extracts_validator_evidence_summary():
    module = _load_script_module("run_pilot_rehearsal_script", "scripts/run-pilot-rehearsal.py")
    payload = {
        "api": {"health": {"status": "ok"}},
        "workers": {"running_workers": 1},
    }
    stdout = "\n".join(
        [
            "[ok] API /health: API health endpoint returned ok.",
            f"[evidence] {json.dumps(payload, sort_keys=True)}",
            "[ok] Summary: Deployment validation completed successfully.",
        ]
    )

    assert module.extract_evidence_summary(stdout) == payload


def test_recovery_readiness_template_review_warns_honestly():
    module = _load_script_module("recovery_readiness_script_template", "scripts/check-recovery-readiness.py")
    config = module.RecoveryConfig(
        env_file=str(REPO_ROOT / ".env.self-hosted-evaluation.example"),
        allow_placeholders=True,
        backup_confirmed=False,
        restore_target_confirmed=False,
        previous_release_ref=None,
        migration_compatibility="unknown",
        redis_recovery_reviewed=False,
        audit_anchor_reviewed=False,
        kms_recovery_reviewed=False,
        evidence_label="template-review",
    )

    results, env = module.run_checks(config)

    assert module.overall_status(results) == "WARN"
    statuses = {result.name: result.status for result in results}
    assert statuses["PostgreSQL target"] == "WARN"
    assert statuses["Demo credentials guard"] == "PASS"
    assert statuses["Backup preflight"] == "WARN"
    assert env["AGENTGATE_ALLOW_DEMO_CREDENTIALS"] == "false"


def test_recovery_readiness_fails_for_sqlite_and_demo_credentials():
    module = _load_script_module("recovery_readiness_script_fail", "scripts/check-recovery-readiness.py")
    env_file = _write_repo_temp_env(
        "\n".join(
            [
                "AGENTGATE_ENV=production",
                "AGENTGATE_DATABASE_URL=sqlite:///./agentgate.db",
                "AGENTGATE_REDIS_URL=redis://:password@redis.internal.example:6379/0",
                "AGENTGATE_PUBLIC_APP_URL=https://agentgate.example.com",
                "AGENTGATE_PUBLIC_API_URL=https://api.agentgate.example.com",
                "AGENTGATE_CORS_ORIGINS=https://agentgate.example.com",
                "AGENTGATE_ALLOW_DEMO_CREDENTIALS=true",
                "AGENTGATE_KEY_PROVIDER=env",
                "AGENTGATE_PAYLOAD_ENCRYPTION_KEY=ZmFrZS1mZXJuZXQta2V5LW1hdGVyaWFs",
                "AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage",
                "AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET=recovery-bucket",
                "AGENTGATE_AUDIT_INTEGRITY_S3_PREFIX=agentgate/recovery",
                "AGENTGATE_AUDIT_INTEGRITY_S3_REGION=us-east-1",
            ]
        )
    )
    try:
        config = module.RecoveryConfig(
            env_file=str(env_file),
            allow_placeholders=False,
            backup_confirmed=True,
            restore_target_confirmed=True,
            previous_release_ref="agentgate-2026-05-22",
            migration_compatibility="restore-required",
            redis_recovery_reviewed=True,
            audit_anchor_reviewed=True,
            kms_recovery_reviewed=True,
            evidence_label="restore-drill",
        )

        results, _ = module.run_checks(config)

        assert module.overall_status(results) == "FAIL"
        statuses = {result.name: result.status for result in results}
        assert statuses["PostgreSQL target"] == "FAIL"
        assert statuses["Demo credentials guard"] == "FAIL"
    finally:
        env_file.unlink(missing_ok=True)


def test_recovery_readiness_redacts_connection_urls(capsys):
    module = _load_script_module("recovery_readiness_script_redaction", "scripts/check-recovery-readiness.py")
    env_file = _write_repo_temp_env(
        "\n".join(
            [
                "AGENTGATE_ENV=production",
                "AGENTGATE_DATABASE_URL=postgresql+psycopg://agentgate:super-secret-db-password@postgres.internal.example:5432/agentgate",
                "AGENTGATE_REDIS_URL=redis://:super-secret-redis-password@redis.internal.example:6379/0",
                "AGENTGATE_PUBLIC_APP_URL=https://agentgate.example.com",
                "AGENTGATE_PUBLIC_API_URL=https://api.agentgate.example.com",
                "AGENTGATE_CORS_ORIGINS=https://agentgate.example.com",
                "AGENTGATE_ALLOW_DEMO_CREDENTIALS=false",
                "AGENTGATE_KEY_PROVIDER=env",
                "AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF=agentgate/payload-key",
                "AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE=object_storage",
                "AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET=recovery-bucket",
                "AGENTGATE_AUDIT_INTEGRITY_S3_PREFIX=agentgate/recovery",
                "AGENTGATE_AUDIT_INTEGRITY_S3_REGION=us-east-1",
            ]
        )
    )
    try:
        config = module.RecoveryConfig(
            env_file=str(env_file),
            allow_placeholders=False,
            backup_confirmed=True,
            restore_target_confirmed=True,
            previous_release_ref="agentgate-2026-05-22",
            migration_compatibility="backward-compatible",
            redis_recovery_reviewed=True,
            audit_anchor_reviewed=True,
            kms_recovery_reviewed=True,
            evidence_label="restore-drill",
        )

        results, env = module.run_checks(config)
        module.print_summary(config, results, env)
        captured = capsys.readouterr().out

        assert "super-secret-db-password" not in captured
        assert "super-secret-redis-password" not in captured
        assert "[REDACTED]" in captured
    finally:
        env_file.unlink(missing_ok=True)
