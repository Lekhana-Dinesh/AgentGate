#!/usr/bin/env python
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_CONFIG_ERROR = 2

DEFAULT_LOCAL_API_URL = "http://127.0.0.1:8000"
DEFAULT_LOCAL_WEB_URL = "http://127.0.0.1:3000"
DEFAULT_LOCAL_TENANT_SLUG = "demo-agentgate"
DEFAULT_LOCAL_EMAIL = "admin@demo.agentgate.example.com"
DEFAULT_LOCAL_PASSWORD = "AgentGate123!"

MANUAL_FOLLOW_UPS = (
    "Run one production-style rehearsal against the real pilot deployment shape, not only local Docker Compose.",
    "Complete one isolated restore drill and record the actual RTO plus any manual recovery gaps.",
    "Verify audit-integrity status and the latest checkpoint range after restore or before pilot traffic.",
    "Dry-run or apply the pilot policy pack against the intended tenant after reviewing connector allowlists.",
    "Confirm real owner/admin and security reviewer staffing for the approval volume the pilot will generate.",
    "Freeze connector scope so GitHub stays first, Jira stays optional, and MCP stays disabled unless explicitly reviewed.",
)

REQUIRED_DOCS = (
    "README.md",
    "docs/context/deployment.md",
    "docs/context/testing-ci.md",
    "docs/reviews/PILOT_READINESS_REVIEW.md",
    "docs/reviews/PILOT_SCOPE.md",
    "docs/go-to-market/PRE_PILOT_PREFLIGHT.md",
    "docs/operations/deployment-validation.md",
    "docs/operations/backup-and-restore.md",
    "docs/operations/pilot-policy-pack.md",
    "docs/operations/api-evaluation.md",
    "docs/operations/observability-package.md",
    "docs/operations/pilot-rehearsal.md",
)

API_COLLECTION_FILES = (
    "api-collections/http/AgentGate/http-client.env.json.example",
    "api-collections/http/AgentGate/operator-evaluation-token.http",
    "api-collections/http/AgentGate/operator-evaluation-cookie.http",
)

OBSERVABILITY_FILES = (
    "observability/prometheus/prometheus.yml",
    "observability/prometheus/alert-rules.yml",
    "observability/grafana/agentgate-overview-dashboard.json",
)

POLICY_PACK_PATH = "policy-packs/pilot-default/policies.json"


class ConfigError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RehearsalConfig:
    local: bool
    api_url: str | None
    web_url: str | None
    tenant_slug: str | None
    email: str | None
    password: str | None
    skip_live_api: bool
    skip_policy_pack: bool
    skip_doc_checks: bool


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: str
    detail: str


def parse_args(argv: list[str] | None = None) -> RehearsalConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run a lightweight AgentGate pilot rehearsal by reusing the repo secret scan, "
            "pilot policy-pack validator, deployment validator, and documentation or asset presence checks."
        ),
        epilog=(
            "This rehearsal is a controlled-pilot wrapper around existing safe checks. "
            "It does not call external connectors, create checkpoints, or replace a restore drill."
        ),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help=(
            "Use the seeded local demo defaults for API URL, web URL, tenant slug, email, and password "
            "unless those values are explicitly overridden."
        ),
    )
    parser.add_argument("--api-url", help="Base AgentGate API URL for live deployment validation.")
    parser.add_argument("--web-url", help="Base AgentGate web URL for live deployment validation.")
    parser.add_argument("--tenant-slug", help="Tenant slug for live deployment validation login.")
    parser.add_argument("--email", help="Operator email for live deployment validation login.")
    parser.add_argument("--password", help="Operator password for live deployment validation login.")
    parser.add_argument(
        "--skip-live-api",
        action="store_true",
        help="Skip live deployment validation and run only repo or artifact checks.",
    )
    parser.add_argument(
        "--skip-policy-pack",
        action="store_true",
        help="Skip the pilot policy-pack validator step.",
    )
    parser.add_argument(
        "--skip-doc-checks",
        action="store_true",
        help="Skip required docs and artifact presence checks.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    api_url = args.api_url or (DEFAULT_LOCAL_API_URL if args.local else None)
    web_url = args.web_url or (DEFAULT_LOCAL_WEB_URL if args.local else None)
    tenant_slug = args.tenant_slug or (DEFAULT_LOCAL_TENANT_SLUG if args.local else None)
    email = args.email or (DEFAULT_LOCAL_EMAIL if args.local else None)
    password = args.password or (DEFAULT_LOCAL_PASSWORD if args.local else None)

    return RehearsalConfig(
        local=bool(args.local),
        api_url=api_url,
        web_url=web_url,
        tenant_slug=tenant_slug,
        email=email,
        password=password,
        skip_live_api=bool(args.skip_live_api),
        skip_policy_pack=bool(args.skip_policy_pack),
        skip_doc_checks=bool(args.skip_doc_checks),
    )


def format_result(result: CheckResult) -> str:
    return f"[{result.status}] {result.name}: {result.detail}"


def summarize_process_output(stdout: str, stderr: str) -> str:
    combined_lines = [line.strip() for line in (stdout.splitlines() + stderr.splitlines()) if line.strip()]
    if not combined_lines:
        return "Command completed without additional output."
    return combined_lines[-1]


def run_python_command(
    name: str,
    script_path: str,
    *script_args: str,
    env_overrides: dict[str, str] | None = None,
) -> CheckResult:
    target = REPO_ROOT / script_path
    if not target.is_file():
        return CheckResult(name=name, status="FAIL", detail=f"Required script is missing: {script_path}")

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)

    completed = subprocess.run(
        [sys.executable, str(target), *script_args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    detail = summarize_process_output(completed.stdout, completed.stderr)
    status = "PASS" if completed.returncode == 0 else "FAIL"
    return CheckResult(name=name, status=status, detail=detail)


def check_required_paths(name: str, relative_paths: tuple[str, ...]) -> CheckResult:
    missing = [path for path in relative_paths if not (REPO_ROOT / path).exists()]
    if missing:
        return CheckResult(
            name=name,
            status="FAIL",
            detail=f"Missing required path(s): {', '.join(missing)}",
        )
    return CheckResult(
        name=name,
        status="PASS",
        detail=f"Verified {len(relative_paths)} required path(s).",
    )


def live_validation_status(config: RehearsalConfig) -> CheckResult | None:
    if config.skip_live_api:
        return CheckResult(
            name="Live deployment validation",
            status="SKIP",
            detail="Skipped because --skip-live-api was requested.",
        )

    required_values = {
        "--api-url": config.api_url,
        "--web-url": config.web_url,
        "--tenant-slug": config.tenant_slug,
        "--email": config.email,
        "--password": config.password,
    }
    missing = [name for name, value in required_values.items() if not value]
    if missing:
        return CheckResult(
            name="Live deployment validation",
            status="SKIP",
            detail=(
                "Skipped because live deployment inputs were not fully provided: "
                + ", ".join(missing)
            ),
        )

    env_overrides = {
        "AGENTGATE_VALIDATE_API_URL": str(config.api_url),
        "AGENTGATE_VALIDATE_WEB_URL": str(config.web_url),
        "AGENTGATE_VALIDATE_EMAIL": str(config.email),
        "AGENTGATE_VALIDATE_PASSWORD": str(config.password),
        "AGENTGATE_VALIDATE_TENANT_SLUG": str(config.tenant_slug),
    }
    return run_python_command(
        "Live deployment validation",
        "scripts/validate-deployment.py",
        env_overrides=env_overrides,
    )


def calculate_overall_status(results: list[CheckResult]) -> str:
    if any(result.status == "FAIL" for result in results):
        return "FAIL"
    if any(result.status in {"WARN", "SKIP"} for result in results):
        return "WARN"
    return "PASS"


def print_summary(results: list[CheckResult]) -> None:
    overall = calculate_overall_status(results)
    print(f"Overall result: {overall}")
    print("")
    print("Automated checks:")
    for result in results:
        print(f"- {format_result(result)}")
    print("")
    print("Required manual follow-ups before partner traffic:")
    for item in MANUAL_FOLLOW_UPS:
        print(f"- {item}")


def run_rehearsal(config: RehearsalConfig) -> int:
    results: list[CheckResult] = []
    results.append(run_python_command("Public doc secret scan", "scripts/check-no-live-secrets.py"))

    if config.skip_policy_pack:
        results.append(
            CheckResult(
                name="Pilot policy-pack validation",
                status="SKIP",
                detail="Skipped because --skip-policy-pack was requested.",
            )
        )
    else:
        results.append(
            run_python_command(
                "Pilot policy-pack validation",
                "scripts/validate-policy-pack.py",
                "--pack",
                POLICY_PACK_PATH,
            )
        )

    if config.skip_doc_checks:
        results.append(
            CheckResult(
                name="Required docs and artifacts",
                status="SKIP",
                detail="Skipped because --skip-doc-checks was requested.",
            )
        )
    else:
        results.append(check_required_paths("Required docs", REQUIRED_DOCS))
        results.append(check_required_paths("API evaluation collection", API_COLLECTION_FILES))
        results.append(check_required_paths("Observability starter assets", OBSERVABILITY_FILES))
        results.append(check_required_paths("Pilot policy-pack artifact", (POLICY_PACK_PATH,)))

    live_result = live_validation_status(config)
    if live_result is not None:
        results.append(live_result)

    print_summary(results)
    return EXIT_FAILED if calculate_overall_status(results) == "FAIL" else EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(argv)
        return run_rehearsal(config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except KeyboardInterrupt:
        print("Pilot rehearsal interrupted by user.", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
