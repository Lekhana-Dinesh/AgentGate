#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_CONFIG_ERROR = 2
MASK = "[REDACTED]"
PLACEHOLDER_PATTERN = re.compile(
    r"replace-with|replace-me|example\.com|<[^>]+>|changeme|placeholder",
    re.IGNORECASE,
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryConfig:
    env_file: str | None
    allow_placeholders: bool
    backup_confirmed: bool
    restore_target_confirmed: bool
    previous_release_ref: str | None
    migration_compatibility: str
    redis_recovery_reviewed: bool
    audit_anchor_reviewed: bool
    kms_recovery_reviewed: bool
    evidence_label: str | None


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    detail: str
    evidence: dict[str, Any] | None = None


def parse_args(argv: list[str] | None = None) -> RecoveryConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Check whether an AgentGate recovery drill or rollback rehearsal is ready to execute "
            "without performing any destructive restore steps."
        ),
        epilog=(
            "This script is non-destructive by default. It verifies config shape, recovery prerequisites, "
            "and operator confirmations without printing secrets or mutating data."
        ),
    )
    parser.add_argument(
        "--env-file",
        help=(
            "Optional dotenv-style file to read in addition to the current shell environment. "
            "Use the real off-repo pilot env file for a live rehearsal, or the example file for package review."
        ),
    )
    parser.add_argument(
        "--allow-placeholders",
        action="store_true",
        help="Allow example or placeholder values and report them as WARN instead of FAIL.",
    )
    parser.add_argument(
        "--backup-confirmed",
        action="store_true",
        help="Confirm that a fresh PostgreSQL backup or snapshot exists before migration or restore work.",
    )
    parser.add_argument(
        "--restore-target-confirmed",
        action="store_true",
        help="Confirm that an isolated clean PostgreSQL restore target is identified for the drill.",
    )
    parser.add_argument(
        "--previous-release-ref",
        help="Record the previous image tag, build SHA, or release reference retained for rollback.",
    )
    parser.add_argument(
        "--migration-compatibility",
        choices=("unknown", "backward-compatible", "restore-required"),
        default="unknown",
        help=(
            "Rollback decision point for the target migration set: "
            "unknown, backward-compatible, or restore-required."
        ),
    )
    parser.add_argument(
        "--redis-recovery-reviewed",
        action="store_true",
        help="Confirm that Redis recovery expectations were reviewed for restored PostgreSQL snapshots.",
    )
    parser.add_argument(
        "--audit-anchor-reviewed",
        action="store_true",
        help="Confirm that audit-integrity checkpoint recovery and verification steps were reviewed.",
    )
    parser.add_argument(
        "--kms-recovery-reviewed",
        action="store_true",
        help="Confirm that key-provider or secret-manager recovery access was reviewed.",
    )
    parser.add_argument(
        "--evidence-label",
        help="Optional operator label for the recovery evidence summary, such as rehearsal-2026-05-22.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    return RecoveryConfig(
        env_file=args.env_file,
        allow_placeholders=bool(args.allow_placeholders),
        backup_confirmed=bool(args.backup_confirmed),
        restore_target_confirmed=bool(args.restore_target_confirmed),
        previous_release_ref=args.previous_release_ref,
        migration_compatibility=str(args.migration_compatibility),
        redis_recovery_reviewed=bool(args.redis_recovery_reviewed),
        audit_anchor_reviewed=bool(args.audit_anchor_reviewed),
        kms_recovery_reviewed=bool(args.kms_recovery_reviewed),
        evidence_label=args.evidence_label,
    )


def redact_value(value: str) -> str:
    if not value:
        return value

    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme and parsed.netloc:
        hostname = parsed.hostname or ""
        port = f":{parsed.port}" if parsed.port else ""
        userinfo = f"{MASK}@" if parsed.username or parsed.password else ""
        path = parsed.path or ""
        query = f"?{parsed.query}" if parsed.query else ""
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"{parsed.scheme}://{userinfo}{hostname}{port}{path}{query}{fragment}"

    redacted = re.sub(r"(Bearer)\s+[A-Za-z0-9._\-+/=]+", rf"\1 {MASK}", value, flags=re.IGNORECASE)
    if len(redacted) > 16 and any(token in redacted.lower() for token in ("token", "secret", "password", "key")):
        return MASK
    return redacted


def load_env_file(path: str) -> dict[str, str]:
    target = Path(path)
    if not target.is_file():
        raise ConfigError(f"Env file not found: {path}")

    values: dict[str, str] = {}
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def build_env(config: RecoveryConfig) -> dict[str, str]:
    env: dict[str, str] = {}
    if config.env_file:
        env.update(load_env_file(config.env_file))
    for key, value in os.environ.items():
        if value != "":
            env.setdefault(key, value)
    return env


def get_env_value(env: dict[str, str], key: str) -> str | None:
    value = env.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped else None


def looks_placeholder(value: str | None) -> bool:
    if value is None:
        return False
    return bool(PLACEHOLDER_PATTERN.search(value))


def parse_boolish(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    return None


def parse_url(url: str, label: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https", "postgresql", "postgresql+psycopg", "redis", "rediss", "sqlite"}:
        raise ConfigError(f"{label} must be a recognizable URL.")
    return parsed


def status_for_placeholder(*, value: str | None, allow_placeholders: bool, fail_detail: str, warn_detail: str) -> tuple[str, str]:
    if value is None:
        return "FAIL", fail_detail
    if looks_placeholder(value):
        return ("WARN", warn_detail) if allow_placeholders else ("FAIL", fail_detail)
    return "PASS", ""


def build_evidence_summary(
    *,
    config: RecoveryConfig,
    env: dict[str, str],
    results: list[CheckResult],
) -> dict[str, Any]:
    warnings = [result.detail for result in results if result.status == "WARN"]
    failures = [result.detail for result in results if result.status == "FAIL"]
    return {
        "label": config.evidence_label or "recovery-readiness",
        "env_source": config.env_file or "process-environment",
        "checks": {result.name: result.status for result in results},
        "recovery": {
            "database_url": redact_value(get_env_value(env, "AGENTGATE_DATABASE_URL") or ""),
            "redis_url": redact_value(get_env_value(env, "AGENTGATE_REDIS_URL") or ""),
            "public_app_url": redact_value(get_env_value(env, "AGENTGATE_PUBLIC_APP_URL") or ""),
            "public_api_url": redact_value(get_env_value(env, "AGENTGATE_PUBLIC_API_URL") or ""),
            "audit_anchor_type": get_env_value(env, "AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE") or "unset",
            "key_provider": get_env_value(env, "AGENTGATE_KEY_PROVIDER") or "unset",
            "allow_demo_credentials": get_env_value(env, "AGENTGATE_ALLOW_DEMO_CREDENTIALS") or "unset",
            "previous_release_ref_present": bool(config.previous_release_ref),
            "migration_compatibility": config.migration_compatibility,
            "backup_confirmed": config.backup_confirmed,
            "restore_target_confirmed": config.restore_target_confirmed,
            "redis_recovery_reviewed": config.redis_recovery_reviewed,
            "audit_anchor_reviewed": config.audit_anchor_reviewed,
            "kms_recovery_reviewed": config.kms_recovery_reviewed,
        },
        "warnings": warnings,
        "failures": failures,
    }


def overall_status(results: list[CheckResult]) -> str:
    if any(result.status == "FAIL" for result in results):
        return "FAIL"
    if any(result.status == "WARN" for result in results):
        return "WARN"
    return "PASS"


def check_deployment_shape(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    env_name = get_env_value(env, "AGENTGATE_ENV")
    if env_name is None:
        return CheckResult("Deployment mode", "WARN", "AGENTGATE_ENV is not set. Use production or an explicitly documented pilot-equivalent mode.")
    if env_name.lower() != "production":
        return CheckResult(
            "Deployment mode",
            "WARN",
            f"AGENTGATE_ENV is {env_name!r}. Confirm this mode is intentionally production-like for recovery rehearsal evidence.",
            evidence={"env": env_name},
        )
    return CheckResult("Deployment mode", "PASS", "AGENTGATE_ENV is production.", evidence={"env": env_name})


def check_database(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    database_url = get_env_value(env, "AGENTGATE_DATABASE_URL")
    if not database_url:
        return CheckResult("PostgreSQL target", "FAIL", "AGENTGATE_DATABASE_URL is missing.")
    status, detail = status_for_placeholder(
        value=database_url,
        allow_placeholders=config.allow_placeholders,
        fail_detail="AGENTGATE_DATABASE_URL still contains a placeholder value.",
        warn_detail="AGENTGATE_DATABASE_URL is still placeholder-shaped, which is acceptable for a redacted template review only.",
    )
    try:
        parsed = parse_url(database_url, "AGENTGATE_DATABASE_URL")
    except ConfigError as exc:
        return CheckResult("PostgreSQL target", "FAIL", str(exc))
    if parsed.scheme == "sqlite":
        return CheckResult("PostgreSQL target", "FAIL", "AGENTGATE_DATABASE_URL points at SQLite. Recovery rehearsal requires external PostgreSQL.")
    if not parsed.scheme.startswith("postgresql"):
        return CheckResult("PostgreSQL target", "FAIL", "AGENTGATE_DATABASE_URL must use a PostgreSQL driver URL.")
    if status == "PASS":
        detail = "AGENTGATE_DATABASE_URL points at PostgreSQL and not SQLite."
    return CheckResult(
        "PostgreSQL target",
        status,
        detail,
        evidence={"database_url": redact_value(database_url)},
    )


def check_redis(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    redis_url = get_env_value(env, "AGENTGATE_REDIS_URL")
    if not redis_url:
        return CheckResult("Redis target", "FAIL", "AGENTGATE_REDIS_URL is missing.")
    status, detail = status_for_placeholder(
        value=redis_url,
        allow_placeholders=config.allow_placeholders,
        fail_detail="AGENTGATE_REDIS_URL still contains a placeholder value.",
        warn_detail="AGENTGATE_REDIS_URL is still placeholder-shaped, which is acceptable for a redacted template review only.",
    )
    try:
        parsed = parse_url(redis_url, "AGENTGATE_REDIS_URL")
    except ConfigError as exc:
        return CheckResult("Redis target", "FAIL", str(exc))
    if parsed.scheme not in {"redis", "rediss"}:
        return CheckResult("Redis target", "FAIL", "AGENTGATE_REDIS_URL must use redis:// or rediss://.")
    if status == "PASS":
        detail = "AGENTGATE_REDIS_URL is present for external Redis recovery expectations."
    return CheckResult("Redis target", status, detail, evidence={"redis_url": redact_value(redis_url)})


def check_public_urls(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    app_url = get_env_value(env, "AGENTGATE_PUBLIC_APP_URL")
    api_url = get_env_value(env, "AGENTGATE_PUBLIC_API_URL")
    cors_origins = get_env_value(env, "AGENTGATE_CORS_ORIGINS")
    if not app_url or not api_url:
        return CheckResult("Public URL posture", "FAIL", "AGENTGATE_PUBLIC_APP_URL and AGENTGATE_PUBLIC_API_URL are both required.")

    app_status, app_detail = status_for_placeholder(
        value=app_url,
        allow_placeholders=config.allow_placeholders,
        fail_detail="AGENTGATE_PUBLIC_APP_URL still contains a placeholder value.",
        warn_detail="AGENTGATE_PUBLIC_APP_URL is placeholder-shaped, which is acceptable for template review only.",
    )
    api_status, api_detail = status_for_placeholder(
        value=api_url,
        allow_placeholders=config.allow_placeholders,
        fail_detail="AGENTGATE_PUBLIC_API_URL still contains a placeholder value.",
        warn_detail="AGENTGATE_PUBLIC_API_URL is placeholder-shaped, which is acceptable for template review only.",
    )
    try:
        app_parsed = parse_url(app_url, "AGENTGATE_PUBLIC_APP_URL")
        api_parsed = parse_url(api_url, "AGENTGATE_PUBLIC_API_URL")
    except ConfigError as exc:
        return CheckResult("Public URL posture", "FAIL", str(exc))
    if app_parsed.scheme != "https" or api_parsed.scheme != "https":
        return CheckResult("Public URL posture", "FAIL", "Public app and API URLs must use HTTPS for production-style recovery evidence.")

    statuses = [app_status, api_status]
    if not cors_origins:
        return CheckResult("Public URL posture", "FAIL", "AGENTGATE_CORS_ORIGINS is required and must include the public app URL.")
    if app_url not in cors_origins:
        return CheckResult("Public URL posture", "FAIL", "AGENTGATE_CORS_ORIGINS does not include AGENTGATE_PUBLIC_APP_URL.")

    if "WARN" in statuses:
        detail = app_detail or api_detail or "Public URLs are placeholder-shaped for template review."
        status = "WARN"
    else:
        detail = "Public app, API, and CORS settings are aligned for a production-style recovery drill."
        status = "PASS"
    return CheckResult(
        "Public URL posture",
        status,
        detail,
        evidence={
            "public_app_url": redact_value(app_url),
            "public_api_url": redact_value(api_url),
            "cors_origins": redact_value(cors_origins),
        },
    )


def check_demo_credentials(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    raw = get_env_value(env, "AGENTGATE_ALLOW_DEMO_CREDENTIALS")
    value = parse_boolish(raw)
    if value is None:
        return CheckResult("Demo credentials guard", "FAIL", "AGENTGATE_ALLOW_DEMO_CREDENTIALS must be explicitly true or false.")
    if value:
        return CheckResult("Demo credentials guard", "FAIL", "AGENTGATE_ALLOW_DEMO_CREDENTIALS=true is not acceptable for a production-style recovery rehearsal.")
    return CheckResult("Demo credentials guard", "PASS", "Demo credentials are disabled for recovery rehearsal evidence.")


def check_backup_preflight(config: RecoveryConfig) -> CheckResult:
    if not config.backup_confirmed:
        return CheckResult(
            "Backup preflight",
            "WARN",
            "Fresh PostgreSQL backup confirmation was not provided. Do not run migrations or restore-drill cutover without it.",
        )
    return CheckResult("Backup preflight", "PASS", "Fresh PostgreSQL backup or snapshot was explicitly confirmed.")


def check_restore_target(config: RecoveryConfig) -> CheckResult:
    if not config.restore_target_confirmed:
        return CheckResult(
            "Restore target",
            "WARN",
            "Isolated clean PostgreSQL restore target was not explicitly confirmed for the drill.",
        )
    return CheckResult("Restore target", "PASS", "Isolated restore target was explicitly confirmed.")


def check_rollback_readiness(config: RecoveryConfig) -> CheckResult:
    if not config.previous_release_ref:
        return CheckResult(
            "Rollback readiness",
            "WARN",
            "Previous release or image reference was not recorded. Retain one known-good release before migrations.",
        )
    if config.migration_compatibility == "unknown":
        return CheckResult(
            "Rollback readiness",
            "WARN",
            "Previous release is retained, but migration compatibility is still unknown. Review rollback decision points before rollout.",
            evidence={"previous_release_ref": redact_value(config.previous_release_ref)},
        )
    if config.migration_compatibility == "restore-required":
        return CheckResult(
            "Rollback readiness",
            "PASS",
            "Previous release is retained and rollback is correctly marked as database-involved if the migration is not backward compatible.",
            evidence={"previous_release_ref": redact_value(config.previous_release_ref)},
        )
    return CheckResult(
        "Rollback readiness",
        "PASS",
        "Previous release is retained and migration compatibility is marked as backward-compatible for an app-only rollback path.",
        evidence={"previous_release_ref": redact_value(config.previous_release_ref)},
    )


def check_redis_recovery(config: RecoveryConfig) -> CheckResult:
    if not config.redis_recovery_reviewed:
        return CheckResult(
            "Redis recovery expectations",
            "WARN",
            "Redis recovery expectations were not explicitly reviewed. Restoring an older PostgreSQL snapshot may require clearing or isolating stale broker state.",
        )
    return CheckResult(
        "Redis recovery expectations",
        "PASS",
        "Redis recovery expectations were explicitly reviewed for restored PostgreSQL snapshots.",
    )


def check_key_provider(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    provider = (get_env_value(env, "AGENTGATE_KEY_PROVIDER") or "env").strip().lower()
    if provider == "aws_kms":
        region = get_env_value(env, "AGENTGATE_AWS_REGION")
        key_id = get_env_value(env, "AGENTGATE_AWS_KMS_KEY_ID")
        missing = [name for name, value in (("AGENTGATE_AWS_REGION", region), ("AGENTGATE_AWS_KMS_KEY_ID", key_id)) if not value]
        if missing:
            return CheckResult("Key recovery posture", "FAIL", f"Missing required AWS KMS settings: {', '.join(missing)}")
        if (looks_placeholder(region) or looks_placeholder(key_id)) and not config.allow_placeholders:
            return CheckResult("Key recovery posture", "FAIL", "AWS KMS settings still contain placeholder values.")
        if not config.kms_recovery_reviewed:
            return CheckResult(
                "Key recovery posture",
                "WARN",
                "AWS KMS is configured, but recovery access for decrypting payloads was not explicitly reviewed.",
                evidence={"key_provider": provider, "kms_key_id": redact_value(key_id or "")},
            )
        return CheckResult(
            "Key recovery posture",
            "PASS",
            "AWS KMS settings are present and recovery access was explicitly reviewed.",
            evidence={"key_provider": provider, "kms_key_id": redact_value(key_id or "")},
        )

    payload_key = get_env_value(env, "AGENTGATE_PAYLOAD_ENCRYPTION_KEY")
    payload_secret_ref = get_env_value(env, "AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF")
    if not payload_key and not payload_secret_ref:
        return CheckResult(
            "Key recovery posture",
            "FAIL",
            "Env key provider requires AGENTGATE_PAYLOAD_ENCRYPTION_KEY or AGENTGATE_PAYLOAD_ENCRYPTION_KEY_SECRET_REF.",
        )
    if (looks_placeholder(payload_key) or looks_placeholder(payload_secret_ref)) and not config.allow_placeholders:
        return CheckResult("Key recovery posture", "FAIL", "Env key provider still contains placeholder key material or reference names.")
    if not config.kms_recovery_reviewed:
        return CheckResult(
            "Key recovery posture",
            "WARN",
            "Env-backed key material or secret reference is configured, but recovery access was not explicitly reviewed.",
            evidence={"key_provider": provider},
        )
    return CheckResult(
        "Key recovery posture",
        "PASS",
        "Key-provider configuration is present and recovery access was explicitly reviewed.",
        evidence={"key_provider": provider},
    )


def check_audit_anchor(env: dict[str, str], config: RecoveryConfig) -> CheckResult:
    anchor_type = (get_env_value(env, "AGENTGATE_AUDIT_INTEGRITY_ANCHOR_TYPE") or "").strip().lower()
    if not anchor_type:
        return CheckResult("Audit checkpoint posture", "WARN", "Audit-integrity anchor type is not set. Recovery evidence will rely on the database chain only.")
    if anchor_type == "custom_placeholder":
        return CheckResult("Audit checkpoint posture", "FAIL", "custom_placeholder audit anchor mode is not valid for recovery evidence.")
    if anchor_type == "local":
        return CheckResult(
            "Audit checkpoint posture",
            "WARN",
            "Audit checkpoints are configured for local filesystem storage. That is acceptable for development, but not a strong external evidence boundary.",
            evidence={"audit_anchor_type": anchor_type},
        )

    if anchor_type == "object_storage":
        bucket = get_env_value(env, "AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET")
        prefix = get_env_value(env, "AGENTGATE_AUDIT_INTEGRITY_S3_PREFIX")
        region = get_env_value(env, "AGENTGATE_AUDIT_INTEGRITY_S3_REGION")
        missing = [
            name
            for name, value in (
                ("AGENTGATE_AUDIT_INTEGRITY_S3_BUCKET", bucket),
                ("AGENTGATE_AUDIT_INTEGRITY_S3_PREFIX", prefix),
                ("AGENTGATE_AUDIT_INTEGRITY_S3_REGION", region),
            )
            if not value
        ]
        if missing:
            return CheckResult("Audit checkpoint posture", "FAIL", f"Missing object-storage anchor settings: {', '.join(missing)}")
        placeholders_present = looks_placeholder(bucket) or looks_placeholder(prefix) or looks_placeholder(region)
        if placeholders_present and not config.allow_placeholders:
            return CheckResult("Audit checkpoint posture", "FAIL", "Object-storage audit anchor settings still contain placeholder values.")
        if not config.audit_anchor_reviewed:
            return CheckResult(
                "Audit checkpoint posture",
                "WARN",
                "Audit-integrity object-storage settings are present, but checkpoint verification and destination recovery were not explicitly reviewed.",
                evidence={"audit_anchor_type": anchor_type, "bucket": redact_value(bucket or ""), "prefix": prefix},
            )
        detail = (
            "Audit-integrity object-storage settings are present and checkpoint verification or recovery steps were explicitly reviewed."
            if not placeholders_present
            else "Object-storage audit anchor settings are placeholder-shaped for template review; checkpoint recovery still needs real-environment evidence."
        )
        status = "PASS" if config.audit_anchor_reviewed and not placeholders_present else "WARN"
        return CheckResult(
            "Audit checkpoint posture",
            status,
            detail,
            evidence={"audit_anchor_type": anchor_type, "bucket": redact_value(bucket or ""), "prefix": prefix},
        )

    return CheckResult(
        "Audit checkpoint posture",
        "WARN",
        f"Audit-integrity anchor type {anchor_type!r} is not explicitly covered by this readiness checker. Review external checkpoint recovery manually.",
        evidence={"audit_anchor_type": anchor_type},
    )


def run_checks(config: RecoveryConfig) -> tuple[list[CheckResult], dict[str, str]]:
    env = build_env(config)
    results = [
        check_deployment_shape(env, config),
        check_database(env, config),
        check_redis(env, config),
        check_public_urls(env, config),
        check_demo_credentials(env, config),
        check_backup_preflight(config),
        check_restore_target(config),
        check_rollback_readiness(config),
        check_redis_recovery(config),
        check_key_provider(env, config),
        check_audit_anchor(env, config),
    ]
    return results, env


def print_summary(config: RecoveryConfig, results: list[CheckResult], env: dict[str, str]) -> None:
    overall = overall_status(results)
    print(f"Overall result: {overall}")
    print("")
    print("Recovery readiness checks:")
    for result in results:
        print(f"- [{result.status}] {result.name}: {result.detail}")

    evidence = build_evidence_summary(config=config, env=env, results=results)
    print("")
    print("Redacted recovery evidence summary:")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    print("")
    print(f"[evidence] {json.dumps(evidence, sort_keys=True, separators=(',', ':'))}")
    print("")
    print("Operator notes:")
    print("- App-only rollback is safe only when migrations are deliberately reviewed as backward compatible.")
    print("- Database-involved rollback means stop write traffic, restore PostgreSQL, then redeploy the previous application release.")
    print("- Redis is not the durable source of truth, but stale broker state must still be reviewed after restoring an older PostgreSQL snapshot.")
    print("- External audit checkpoints are stronger evidence than database-only history, but they are not immutable unless the destination enforces WORM or Object Lock.")


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(argv)
        results, env = run_checks(config)
        print_summary(config, results, env)
        return EXIT_FAILED if overall_status(results) == "FAIL" else EXIT_SUCCESS
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except KeyboardInterrupt:
        print("Recovery readiness check interrupted by user.", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
