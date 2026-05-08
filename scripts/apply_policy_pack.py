from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from policy_pack_utils import (
    DEFAULT_POLICY_PACK_PATH,
    PolicyPackDocument,
    PolicyPackValidationError,
    extract_policy_payload,
    policy_signature,
    read_policy_pack,
)


MASK = "[REDACTED]"
EXIT_SUCCESS = 0
EXIT_APPLICATION_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_RUNTIME_ERROR = 3
DEFAULT_TIMEOUT_SECONDS = 5.0


class ConfigError(Exception):
    pass


class ApplyError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ApplyConfig:
    pack_path: str
    api_url: str
    access_token: str | None
    email: str | None
    password: str | None
    tenant_slug: str | None
    dry_run: bool
    update_existing: bool
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class AuthSession:
    session_mode: str
    access_token: str | None
    csrf_token: str | None


@dataclass(frozen=True, slots=True)
class PlanItem:
    action: str
    policy_name: str
    reason: str
    existing_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ApplyReport:
    created: int
    updated: int
    skipped: int
    conflicts: int
    dry_run: bool


class PolicyClientProtocol(Protocol):
    def list_policies(self) -> list[dict[str, Any]]:
        ...

    def create_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def update_policy(self, policy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        ...


class PolicyPackApplier:
    def __init__(self, client: PolicyClientProtocol) -> None:
        self.client = client

    def build_plan(
        self,
        document: PolicyPackDocument,
        *,
        update_existing: bool,
    ) -> list[PlanItem]:
        existing_records = self.client.list_policies()
        existing_by_name = {
            str(record.get("name", "")).strip().lower(): record
            for record in existing_records
            if isinstance(record, dict) and str(record.get("name", "")).strip()
        }
        plan: list[PlanItem] = []
        for payload in document.policies:
            existing = existing_by_name.get(payload["name"].strip().lower())
            if existing is None:
                plan.append(
                    PlanItem(
                        action="create",
                        policy_name=payload["name"],
                        reason="policy does not exist in the tenant",
                        existing_id=None,
                        payload=payload,
                    )
                )
                continue

            existing_payload = extract_policy_payload(existing)
            if policy_signature(existing_payload) == policy_signature(payload):
                plan.append(
                    PlanItem(
                        action="skip",
                        policy_name=payload["name"],
                        reason="existing policy already matches the pack",
                        existing_id=str(existing.get("id") or ""),
                        payload=payload,
                    )
                )
                continue

            if update_existing:
                plan.append(
                    PlanItem(
                        action="update",
                        policy_name=payload["name"],
                        reason="existing policy differs and --update-existing was requested",
                        existing_id=str(existing.get("id") or ""),
                        payload=payload,
                    )
                )
                continue

            plan.append(
                PlanItem(
                    action="conflict",
                    policy_name=payload["name"],
                    reason="existing policy differs; rerun with --update-existing after review if replacement is intentional",
                    existing_id=str(existing.get("id") or ""),
                    payload=payload,
                )
            )
        return plan

    def apply_plan(self, plan: list[PlanItem], *, dry_run: bool) -> ApplyReport:
        created = 0
        updated = 0
        skipped = 0
        conflicts = 0

        for item in plan:
            if item.action == "create":
                print(f"[plan] create: {item.policy_name} ({item.reason})")
                if not dry_run:
                    self.client.create_policy(item.payload)
                    created += 1
                continue
            if item.action == "update":
                print(f"[plan] update: {item.policy_name} ({item.reason})")
                if not dry_run:
                    if not item.existing_id:
                        raise ApplyError(f"Cannot update policy '{item.policy_name}' without an existing policy id.")
                    self.client.update_policy(item.existing_id, item.payload)
                    updated += 1
                continue
            if item.action == "skip":
                print(f"[skip] {item.policy_name}: {item.reason}")
                skipped += 1
                continue
            if item.action == "conflict":
                print(f"[warn] {item.policy_name}: {item.reason}")
                conflicts += 1
                continue
            raise ApplyError(f"Unknown plan action '{item.action}' for policy '{item.policy_name}'.")

        return ApplyReport(
            created=created,
            updated=updated,
            skipped=skipped,
            conflicts=conflicts,
            dry_run=dry_run,
        )


class AgentGatePolicyClient:
    def __init__(self, config: ApplyConfig) -> None:
        self.config = config
        self.secrets = [
            value
            for value in [
                config.access_token,
                config.password,
            ]
            if value
        ]
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.auth_session: AuthSession | None = None

    def list_policies(self) -> list[dict[str, Any]]:
        payload = self.request(method="GET", path="/v1/policies", expect_statuses={200})
        data = self.parse_json(payload, "list policies")
        if not isinstance(data, list):
            raise ApplyError("Policy list returned an unexpected shape.")
        return [item for item in data if isinstance(item, dict)]

    def create_policy(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.request(
            method="POST",
            path="/v1/policies",
            json_body=payload,
            expect_statuses={200, 201},
        )
        data = self.parse_json(response, "create policy")
        if not isinstance(data, dict):
            raise ApplyError("Create policy returned an unexpected shape.")
        return data

    def update_policy(self, policy_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.request(
            method="PUT",
            path=f"/v1/policies/{urllib.parse.quote(policy_id)}",
            json_body=payload,
            expect_statuses={200},
        )
        data = self.parse_json(response, "update policy")
        if not isinstance(data, dict):
            raise ApplyError("Update policy returned an unexpected shape.")
        return data

    def request(
        self,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        expect_statuses: set[int],
    ) -> bytes:
        self.ensure_authenticated()
        headers = {
            "Accept": "application/json",
            "User-Agent": "AgentGatePolicyPackApplier/0.1",
        }
        data = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body).encode("utf-8")

        if self.auth_session and self.auth_session.session_mode == "token" and self.auth_session.access_token:
            headers["Authorization"] = f"Bearer {self.auth_session.access_token}"
        if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and self.auth_session and self.auth_session.session_mode == "cookie":
            csrf_token = self.auth_session.csrf_token or self.fetch_csrf_token()
            if csrf_token:
                headers["X-CSRF-Token"] = csrf_token

        request = urllib.request.Request(
            url=build_url(self.config.api_url, path),
            method=method.upper(),
            headers=headers,
            data=data,
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
                if response.getcode() not in expect_statuses:
                    raise ApplyError(f"Unexpected HTTP {response.getcode()} for {path}.")
                return body
        except urllib.error.HTTPError as exc:
            if exc.code in expect_statuses:
                return exc.read()
            raise self.build_http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise ApplyError(redact_text(f"Connection error while calling {path}: {exc.reason}", self.secrets)) from exc
        except TimeoutError as exc:
            raise ApplyError(redact_text(f"Timed out while calling {path}.", self.secrets)) from exc

    def ensure_authenticated(self) -> None:
        if self.auth_session is not None:
            return
        if self.config.access_token:
            self.auth_session = AuthSession(
                session_mode="token",
                access_token=self.config.access_token,
                csrf_token=None,
            )
            return
        if not self.config.email or not self.config.password or not self.config.tenant_slug:
            raise ConfigError(
                "Set AGENTGATE_ACCESS_TOKEN or provide AGENTGATE_EMAIL, AGENTGATE_PASSWORD, and AGENTGATE_TENANT_SLUG."
            )

        request = urllib.request.Request(
            url=build_url(self.config.api_url, "/v1/auth/login"),
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "AgentGatePolicyPackApplier/0.1",
            },
            data=json.dumps(
                {
                    "email": self.config.email,
                    "password": self.config.password,
                    "tenant_slug": self.config.tenant_slug,
                }
            ).encode("utf-8"),
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise self.build_http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise ApplyError(redact_text(f"Connection error during login: {exc.reason}", self.secrets)) from exc

        data = self.parse_json(body, "login")
        if not isinstance(data, dict):
            raise ApplyError("Login returned an unexpected shape.")

        session_mode = str(data.get("session_mode") or "")
        access_token = data.get("access_token")
        csrf_token = data.get("csrf_token")
        if session_mode not in {"token", "cookie"}:
            raise ApplyError("Login did not return a recognized AgentGate session mode.")
        if session_mode == "token":
            if not isinstance(access_token, str) or not access_token:
                raise ApplyError("Token login did not return an access token.")
            self.secrets.append(access_token)
        if isinstance(csrf_token, str) and csrf_token:
            self.secrets.append(csrf_token)
        self.auth_session = AuthSession(
            session_mode=session_mode,
            access_token=access_token if isinstance(access_token, str) and access_token else None,
            csrf_token=csrf_token if isinstance(csrf_token, str) and csrf_token else None,
        )
        if session_mode == "cookie" and not self.auth_session.csrf_token:
            self.auth_session = AuthSession(
                session_mode="cookie",
                access_token=None,
                csrf_token=self.fetch_csrf_token(),
            )

    def fetch_csrf_token(self) -> str | None:
        request = urllib.request.Request(
            url=build_url(self.config.api_url, "/v1/auth/csrf-token"),
            method="GET",
            headers={"Accept": "application/json", "User-Agent": "AgentGatePolicyPackApplier/0.1"},
        )
        try:
            with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise self.build_http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise ApplyError(redact_text(f"Connection error while fetching CSRF token: {exc.reason}", self.secrets)) from exc
        data = self.parse_json(body, "csrf-token")
        if not isinstance(data, dict):
            raise ApplyError("CSRF token endpoint returned an unexpected shape.")
        token = data.get("csrf_token")
        if isinstance(token, str) and token:
            self.secrets.append(token)
            return token
        return None

    def parse_json(self, payload: bytes, label: str) -> Any:
        try:
            return json.loads(payload.decode("utf-8"))
        except Exception as exc:
            raise ApplyError(redact_text(f"{label} returned invalid JSON: {exc}", self.secrets)) from exc

    def build_http_error(self, exc: urllib.error.HTTPError) -> ApplyError:
        body = exc.read()
        detail = exc.reason
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error_section = payload.get("error")
            if isinstance(error_section, dict) and error_section.get("detail"):
                detail = str(error_section["detail"])
            elif payload.get("detail"):
                detail = str(payload["detail"])
        return ApplyError(redact_text(f"HTTP {exc.code} from {exc.geturl()}: {detail}", self.secrets))


def redact_text(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, MASK)
    redacted = re.sub(r"(Bearer)\s+[A-Za-z0-9._\-+/=]+", rf"\1 {MASK}", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r'("access_token"\s*:\s*")[^"]+(")', rf"\1{MASK}\2", redacted)
    redacted = re.sub(r'("csrf_token"\s*:\s*")[^"]+(")', rf"\1{MASK}\2", redacted)
    return redacted


def env_or_default(name: str) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    return value


def parse_args(argv: list[str] | None = None) -> ApplyConfig:
    parser = argparse.ArgumentParser(
        description="Review and apply a conservative AgentGate policy pack through the existing /v1/policies API.",
        epilog=(
            "The script is idempotent by policy name. Existing matching policies are skipped. "
            "Existing differing policies are reported and left untouched unless --update-existing is set."
        ),
    )
    parser.add_argument("--pack", default=str(DEFAULT_POLICY_PACK_PATH), help="Path to the policy-pack JSON file.")
    parser.add_argument("--api-url", default=env_or_default("AGENTGATE_API_URL"), help="Base AgentGate API URL.")
    parser.add_argument(
        "--access-token",
        default=env_or_default("AGENTGATE_ACCESS_TOKEN"),
        help="Bearer token for an operator account. If omitted, the script can log in with email/password/tenant slug.",
    )
    parser.add_argument("--email", default=env_or_default("AGENTGATE_EMAIL"), help="Operator email for login fallback.")
    parser.add_argument("--password", default=env_or_default("AGENTGATE_PASSWORD"), help="Operator password for login fallback.")
    parser.add_argument("--tenant-slug", default=env_or_default("AGENTGATE_TENANT_SLUG"), help="Tenant slug for login fallback.")
    parser.add_argument("--dry-run", action="store_true", help="Show the apply plan without creating or updating policies.")
    parser.add_argument(
        "--update-existing",
        action="store_true",
        help="Update existing policies when the pack name matches but the payload differs.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(env_or_default("AGENTGATE_POLICY_PACK_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT_SECONDS),
        help="Per-request timeout in seconds.",
    )
    args = parser.parse_args(argv or sys.argv[1:])

    if not args.api_url:
        raise ConfigError("Set --api-url or AGENTGATE_API_URL.")
    if args.timeout_seconds <= 0:
        raise ConfigError("timeout-seconds must be greater than zero.")

    return ApplyConfig(
        pack_path=str(args.pack),
        api_url=normalize_base_url(str(args.api_url), "API URL"),
        access_token=str(args.access_token) if args.access_token else None,
        email=str(args.email) if args.email else None,
        password=str(args.password) if args.password else None,
        tenant_slug=str(args.tenant_slug) if args.tenant_slug else None,
        dry_run=bool(args.dry_run),
        update_existing=bool(args.update_existing),
        timeout_seconds=float(args.timeout_seconds),
    )


def normalize_base_url(url: str, label: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{label} must be a full http(s) URL.")
    return url.rstrip("/")


def build_url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(argv)
        document = read_policy_pack(config.pack_path)
        client = AgentGatePolicyClient(config)
        applier = PolicyPackApplier(client)
        plan = applier.build_plan(document, update_existing=config.update_existing)
        report = applier.apply_plan(plan, dry_run=config.dry_run)
        print(
            f"[ok] Summary: created={report.created}, updated={report.updated}, "
            f"skipped={report.skipped}, conflicts={report.conflicts}, dry_run={str(report.dry_run).lower()}"
        )
        if report.conflicts and not report.dry_run:
            return EXIT_APPLICATION_FAILED
        return EXIT_SUCCESS
    except (ConfigError, PolicyPackValidationError) as exc:
        print(f"[fail] Configuration: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except ApplyError as exc:
        print(f"[fail] Apply: {exc}", file=sys.stderr)
        return EXIT_APPLICATION_FAILED
    except KeyboardInterrupt:
        print("[fail] Apply: interrupted by user.", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except Exception as exc:
        print(f"[fail] Runtime: {exc}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
