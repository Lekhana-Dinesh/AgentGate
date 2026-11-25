#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
WEB_ROOT = REPO_ROOT / "apps" / "web"
LOCAL_DB_PATH = API_ROOT / "agentgate.db"

LOCAL_API_URL = "http://127.0.0.1:8000"
LOCAL_WEB_URL = "http://127.0.0.1:3000"
LOCAL_CORS_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000"
LOCAL_DATABASE_URL = "sqlite:///./agentgate.db"
LOCAL_TENANT_SLUG = "demo-agentgate"
LOCAL_ADMIN_EMAIL = "admin@demo.agentgate.example.com"
LOCAL_ADMIN_PASSWORD = "AgentGate123!"

EXIT_SUCCESS = 0
EXIT_FAILED = 1
EXIT_CONFIG_ERROR = 2


class LocalDemoError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DemoSeedState:
    tenant_slug: str
    tool_name: str
    demo_safe_mock: bool
    auth_mode: str | None
    token_env_var: str | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reset or verify the local AgentGate demo SQLite database and print the exact "
            "manual commands needed to start the API and web apps for the governed GitHub demo."
        ),
        epilog=(
            "This helper is local-development-only. The reset command always forces "
            "AGENTGATE_DATABASE_URL=sqlite:///./agentgate.db under apps/api so it never targets "
            "an external database by accident."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "reset",
        help="Delete apps/api/agentgate.db, rerun migrations, reseed demo data, and verify demo_safe_mock.",
    )
    subparsers.add_parser(
        "check",
        help="Verify that the local demo SQLite DB exists and the seeded GitHub tool has demo_safe_mock=true.",
    )
    subparsers.add_parser(
        "start-commands",
        help="Print the exact manual PowerShell commands to start the API and web apps for local demo use.",
    )
    return parser.parse_args(argv or sys.argv[1:])


def build_local_api_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AGENTGATE_ENV": "development",
            "AGENTGATE_DATABASE_URL": LOCAL_DATABASE_URL,
            "AGENTGATE_CORS_ORIGINS": LOCAL_CORS_ORIGINS,
            "AGENTGATE_PUBLIC_APP_URL": LOCAL_WEB_URL,
            "AGENTGATE_PUBLIC_API_URL": LOCAL_API_URL,
        }
    )
    return env


def run_api_command(*args: str) -> None:
    completed = subprocess.run(
        [sys.executable, *args],
        cwd=API_ROOT,
        env=build_local_api_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = "\n".join(
            line for line in [completed.stdout.strip(), completed.stderr.strip()] if line
        ).strip()
        raise LocalDemoError(
            f"Command failed in apps/api: python {' '.join(args)}\n{detail or 'No additional output.'}"
        )


def load_demo_seed_state() -> DemoSeedState:
    if not LOCAL_DB_PATH.is_file():
        raise LocalDemoError(
            f"Local demo SQLite DB was not found at {LOCAL_DB_PATH}. "
            "Run 'python scripts/local-demo.py reset' first."
        )

    with sqlite3.connect(LOCAL_DB_PATH) as connection:
        row = connection.execute(
            """
            SELECT tenants.slug, tools.name, tools.config
            FROM tools
            JOIN tenants ON tenants.id = tools.tenant_id
            WHERE tenants.slug = ? AND tools.name = ?
            LIMIT 1
            """,
            (LOCAL_TENANT_SLUG, "GitHub"),
        ).fetchone()

    if row is None:
        raise LocalDemoError(
            "The seeded GitHub tool was not found in the local demo DB. "
            "Run 'python scripts/local-demo.py reset' to rebuild local demo data."
        )

    tenant_slug, tool_name, raw_config = row
    try:
        config = json.loads(raw_config or "{}")
    except json.JSONDecodeError as exc:
        raise LocalDemoError("The seeded GitHub tool config is not valid JSON.") from exc

    return DemoSeedState(
        tenant_slug=str(tenant_slug),
        tool_name=str(tool_name),
        demo_safe_mock=bool(config.get("demo_safe_mock")),
        auth_mode=str(config.get("auth_mode")).strip() if config.get("auth_mode") is not None else None,
        token_env_var=str(config.get("token_env_var")).strip() if config.get("token_env_var") is not None else None,
    )


def verify_demo_seed_state() -> DemoSeedState:
    state = load_demo_seed_state()
    if not state.demo_safe_mock:
        raise LocalDemoError(
            "The seeded GitHub tool is missing demo_safe_mock=true. "
            "Run 'python scripts/local-demo.py reset' to rebuild the local demo DB."
        )
    return state


def print_start_commands() -> None:
    print("Local demo assumptions:")
    print(f"- SQLite DB: {LOCAL_DB_PATH}")
    print(f"- API URL: {LOCAL_API_URL}")
    print(f"- Web URL: {LOCAL_WEB_URL}")
    print(f"- Tenant: {LOCAL_TENANT_SLUG}")
    print(f"- Admin: {LOCAL_ADMIN_EMAIL} / {LOCAL_ADMIN_PASSWORD}")
    print("")
    print("Start the API in one PowerShell terminal:")
    print(f"cd {API_ROOT}")
    print(f"$env:AGENTGATE_ENV='development'")
    print(f"$env:AGENTGATE_DATABASE_URL='{LOCAL_DATABASE_URL}'")
    print(f"$env:AGENTGATE_CORS_ORIGINS='{LOCAL_CORS_ORIGINS}'")
    print(f"$env:AGENTGATE_PUBLIC_APP_URL='{LOCAL_WEB_URL}'")
    print(f"$env:AGENTGATE_PUBLIC_API_URL='{LOCAL_API_URL}'")
    print("python -m uvicorn app.main:app --host 127.0.0.1 --port 8000")
    print("")
    print("Start the web app in another PowerShell terminal:")
    print(f"cd {WEB_ROOT}")
    print(f"$env:NEXT_PUBLIC_API_BASE_URL='{LOCAL_API_URL}'")
    print("npm run dev -- --hostname 127.0.0.1 --port 3000")
    print("")
    print("Then open:")
    print(f"- Login: {LOCAL_WEB_URL}/login")
    print(f"- Demo: {LOCAL_WEB_URL}/demo")
    print(f"- Policies: {LOCAL_WEB_URL}/policies")
    print("")
    print("The seeded governed GitHub demo is demo-safe by default and does not require live GitHub credentials.")
    print("Real GitHub execution still requires the configured auth mode and runtime credentials.")


def command_reset() -> int:
    if LOCAL_DB_PATH.exists():
        LOCAL_DB_PATH.unlink()
        print(f"Deleted local demo DB: {LOCAL_DB_PATH}")
    else:
        print(f"Local demo DB was already absent: {LOCAL_DB_PATH}")

    print("Running local SQLite migrations...")
    run_api_command("-m", "alembic", "upgrade", "head")

    print("Seeding local demo data...")
    run_api_command("-m", "app.db.seed")

    state = verify_demo_seed_state()
    print(
        "Verified seeded GitHub tool:",
    )
    print(
        f"- tenant={state.tenant_slug} tool={state.tool_name} demo_safe_mock={state.demo_safe_mock} "
        f"auth_mode={state.auth_mode or 'unknown'} token_env_var={state.token_env_var or 'unset'}"
    )
    print("")
    print_start_commands()
    return EXIT_SUCCESS


def command_check() -> int:
    state = verify_demo_seed_state()
    print("Local demo seed looks healthy:")
    print(f"- SQLite DB: {LOCAL_DB_PATH}")
    print(f"- tenant={state.tenant_slug}")
    print(f"- tool={state.tool_name}")
    print(f"- demo_safe_mock={state.demo_safe_mock}")
    print(f"- auth_mode={state.auth_mode or 'unknown'}")
    print(f"- token_env_var={state.token_env_var or 'unset'}")
    print("")
    print_start_commands()
    return EXIT_SUCCESS


def command_start_commands() -> int:
    print_start_commands()
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if args.command == "reset":
            return command_reset()
        if args.command == "check":
            return command_check()
        if args.command == "start-commands":
            return command_start_commands()
        raise LocalDemoError(f"Unsupported command: {args.command}")
    except LocalDemoError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG_ERROR if "Run 'python scripts/local-demo.py reset'" in str(exc) else EXIT_FAILED
    except KeyboardInterrupt:
        print("Local demo command interrupted by user.", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
