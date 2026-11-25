#!/usr/bin/env python
from __future__ import annotations

import argparse
import http.cookiejar
import ipaddress
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


EXIT_SUCCESS = 0
EXIT_VALIDATION_FAILED = 1
EXIT_CONFIG_ERROR = 2
EXIT_RUNTIME_ERROR = 3

MASK = "[REDACTED]"
DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 2.0


class ConfigError(Exception):
    pass


class ValidationFailure(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    api_url: str
    web_url: str
    email: str
    password: str
    tenant_slug: str
    timeout_seconds: float
    retries: int
    retry_delay_seconds: float
    metrics_mode: str


@dataclass(frozen=True, slots=True)
class AuthSession:
    session_mode: str
    access_token: str | None
    csrf_token: str | None


@dataclass(frozen=True, slots=True)
class ResponsePayload:
    status_code: int
    headers: dict[str, str]
    body: bytes
    url: str


def env_or_default(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def parse_float_setting(name: str, default: float) -> float:
    raw = env_or_default(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number.") from exc


def parse_int_setting(name: str, default: int) -> int:
    raw = env_or_default(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def normalize_base_url(url: str, label: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(f"{label} must be a full http(s) URL.")
    return url.rstrip("/")


def build_url(base_url: str, path: str) -> str:
    return f"{base_url}{path}"


def redact_text(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, MASK)
    redacted = re.sub(r"(Bearer)\s+[A-Za-z0-9._\-+/=]+", rf"\1 {MASK}", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r"(Cookie|Set-Cookie):\s*[^;\n]+", rf"\1: {MASK}", redacted, flags=re.IGNORECASE)
    redacted = re.sub(r'("access_token"\s*:\s*")[^"]+(")', rf"\1{MASK}\2", redacted)
    redacted = re.sub(r'("csrf_token"\s*:\s*")[^"]+(")', rf"\1{MASK}\2", redacted)
    return redacted


def safe_json_loads(raw: bytes) -> Any | None:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def parse_metrics_mode(raw: str | None) -> str:
    value = (raw or "auto").strip().lower()
    if value in {"auto", "true", "always"}:
        return "always" if value in {"true", "always"} else "auto"
    if value in {"false", "never"}:
        return "never"
    raise ConfigError("Metrics mode must be one of: auto, true, false, always, never.")


def should_check_metrics(api_url: str, metrics_mode: str) -> bool:
    if metrics_mode == "always":
        return True
    if metrics_mode == "never":
        return False
    parsed = urllib.parse.urlparse(api_url)
    hostname = (parsed.hostname or "").strip().lower()
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        ip = ipaddress.ip_address(hostname)
        return ip.is_loopback
    except ValueError:
        return False


class DeploymentValidator:
    def __init__(self, config: ValidationConfig) -> None:
        self.config = config
        self.secrets = [config.password]
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookie_jar))
        self.auth_session: AuthSession | None = None
        self.tools_summary_cache: list[dict[str, Any]] | None = None
        self.evidence: dict[str, Any] = {
            "api": {},
            "operator": {},
            "jobs": {},
            "workers": {},
            "github_connectors": {},
            "audit_integrity": {},
            "metrics": {},
            "warnings": [],
        }

    def run(self) -> int:
        steps = [
            ("API /health", self.check_health),
            ("API /ready", self.check_ready),
            ("Web login page", self.check_web_login_page),
            ("Operator login", self.check_login),
            ("Current user", self.check_current_user),
            ("Settings overview", self.check_settings_overview),
            ("Onboarding status", self.check_onboarding_status),
            ("Tools summary", self.check_tools_summary),
            ("GitHub connector readiness", self.check_github_connector_readiness),
            ("Jobs list", self.check_jobs),
            ("Worker status", self.check_worker_status),
            ("Audit integrity status", self.check_audit_integrity),
            ("Audit integrity checkpoints", self.check_audit_integrity_checkpoints),
        ]

        if should_check_metrics(self.config.api_url, self.config.metrics_mode):
            steps.append(("Metrics", self.check_metrics))
        else:
            if self.config.metrics_mode == "never":
                detail = "Skipping /metrics because metrics validation was explicitly disabled."
            else:
                detail = "Skipping /metrics because metrics mode is auto and the API URL is not loopback."
            self.evidence["metrics"] = {
                "checked": False,
                "mode": self.config.metrics_mode,
                "access_note": "internal_path_review_required",
            }
            self.append_warning("Metrics were not fetched directly. Confirm /metrics is still available on an internal-only operator path.")
            self.print_status(
                "skip",
                "Metrics",
                detail,
            )

        steps.append(("Logout", self.check_logout))

        for label, handler in steps:
            handler(label)

        self.emit_evidence_summary()
        self.print_status("ok", "Summary", "Deployment validation completed successfully.")
        return EXIT_SUCCESS

    def request(
        self,
        *,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        token: str | None = None,
        csrf_token: str | None = None,
        expect_statuses: set[int] | None = None,
        allow_retry: bool = True,
    ) -> ResponsePayload:
        headers = {
            "Accept": "application/json, text/plain;q=0.9, */*;q=0.8",
            "User-Agent": "AgentGateDeploymentValidator/0.1",
        }
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if csrf_token:
            headers["X-CSRF-Token"] = csrf_token

        last_error: Exception | None = None
        attempts = max(1, self.config.retries + 1)
        for attempt in range(1, attempts + 1):
            request = urllib.request.Request(url=url, method=method.upper(), headers=headers, data=data)
            try:
                with self.opener.open(request, timeout=self.config.timeout_seconds) as response:
                    payload = ResponsePayload(
                        status_code=response.getcode(),
                        headers={key: value for key, value in response.headers.items()},
                        body=response.read(),
                        url=response.geturl(),
                    )
                    if expect_statuses and payload.status_code not in expect_statuses:
                        raise ValidationFailure(
                            f"Unexpected HTTP {payload.status_code} from {url}."
                        )
                    return payload
            except urllib.error.HTTPError as exc:
                if expect_statuses and exc.code in expect_statuses:
                    return ResponsePayload(
                        status_code=exc.code,
                        headers={key: value for key, value in exc.headers.items()},
                        body=exc.read(),
                        url=exc.geturl(),
                    )
                last_error = self.build_http_error(exc)
                retryable = allow_retry and exc.code >= 500 and attempt < attempts
                if retryable:
                    time.sleep(self.config.retry_delay_seconds)
                    continue
                raise last_error
            except urllib.error.URLError as exc:
                last_error = ValidationFailure(
                    redact_text(
                        f"Connection error while calling {url}: {exc.reason}",
                        self.secrets,
                    )
                )
                if allow_retry and attempt < attempts:
                    time.sleep(self.config.retry_delay_seconds)
                    continue
                raise last_error
            except TimeoutError:
                last_error = ValidationFailure(
                    redact_text(f"Timed out while calling {url}.", self.secrets)
                )
                if allow_retry and attempt < attempts:
                    time.sleep(self.config.retry_delay_seconds)
                    continue
                raise last_error
        if last_error is not None:
            raise last_error
        raise ValidationFailure(f"Failed to call {url}.")

    def build_http_error(self, exc: urllib.error.HTTPError) -> ValidationFailure:
        body = exc.read()
        request_id = exc.headers.get("X-Request-ID")
        detail = exc.reason
        payload = safe_json_loads(body)
        if isinstance(payload, dict):
            error_section = payload.get("error")
            if isinstance(error_section, dict):
                detail = str(error_section.get("detail") or detail)
                request_id = str(error_section.get("request_id") or request_id or "")
            elif payload.get("detail"):
                detail = str(payload.get("detail"))
        message = f"HTTP {exc.code} from {exc.geturl()}: {detail}"
        if request_id:
            message += f" (request_id={request_id})"
        return ValidationFailure(redact_text(message, self.secrets))

    def parse_json(self, payload: ResponsePayload, label: str) -> Any:
        try:
            return json.loads(payload.body.decode("utf-8"))
        except Exception as exc:
            raise ValidationFailure(
                redact_text(f"{label} returned invalid JSON: {exc}", self.secrets)
            ) from exc

    def check_health(self, label: str) -> None:
        payload = self.request(
            method="GET",
            url=build_url(self.config.api_url, "/health"),
            expect_statuses={200},
        )
        data = self.parse_json(payload, label)
        if not isinstance(data, dict) or data.get("status") != "ok":
            raise ValidationFailure(f"{label} did not report status=ok.")
        self.evidence["api"]["health"] = {
            "status": str(data.get("status") or "unknown"),
            "service": str(data.get("service") or "unknown"),
        }
        self.print_status("ok", label, "API health endpoint returned ok.")

    def check_ready(self, label: str) -> None:
        payload = self.request(
            method="GET",
            url=build_url(self.config.api_url, "/ready"),
            expect_statuses={200, 503},
        )
        data = self.parse_json(payload, label)
        if not isinstance(data, dict):
            raise ValidationFailure(f"{label} returned an unexpected shape.")
        checks = data.get("checks") or {}
        database_status = str(((checks.get("database") or {}).get("status")) or "unknown")
        keys_status = str(((checks.get("keys") or {}).get("status")) or "unknown")
        limiter_status = str(((checks.get("rate_limiter") or {}).get("status")) or "unknown")
        scheduler_status = str(((checks.get("scheduler") or {}).get("status")) or "unknown")
        if payload.status_code != 200 or data.get("status") != "ready":
            raise ValidationFailure(
                f"{label} reported {data.get('status', 'not_ready')} "
                f"(database={database_status}, keys={keys_status}, rate_limiter={limiter_status})."
            )
        self.evidence["api"]["ready"] = {
            "status": str(data.get("status") or "unknown"),
            "database": database_status,
            "keys": keys_status,
            "rate_limiter": limiter_status,
            "scheduler": scheduler_status,
        }
        self.print_status(
            "ok",
            label,
            f"API readiness is ready (database={database_status}, keys={keys_status}, rate_limiter={limiter_status}, scheduler={scheduler_status}).",
        )

    def check_web_login_page(self, label: str) -> None:
        payload = self.request(
            method="GET",
            url=build_url(self.config.web_url, "/login"),
            expect_statuses={200},
        )
        body = payload.body.decode("utf-8", errors="replace")
        if "AgentGate" not in body and "Access AgentGate" not in body:
            raise ValidationFailure("Web login page did not look like the AgentGate login surface.")
        self.print_status("ok", label, "Web login page is reachable.")

    def check_login(self, label: str) -> None:
        payload = self.request(
            method="POST",
            url=build_url(self.config.api_url, "/v1/auth/login"),
            json_body={
                "email": self.config.email,
                "password": self.config.password,
                "tenant_slug": self.config.tenant_slug,
            },
            expect_statuses={200},
        )
        data = self.parse_json(payload, label)
        if not isinstance(data, dict):
            raise ValidationFailure("Login response was not a JSON object.")
        session_mode = str(data.get("session_mode") or "")
        access_token = data.get("access_token")
        csrf_token = data.get("csrf_token")
        if session_mode not in {"token", "cookie"}:
            raise ValidationFailure("Login response did not include a recognized session_mode.")
        if session_mode == "token":
            if not isinstance(access_token, str) or not access_token:
                raise ValidationFailure("Token session mode did not return an access token.")
            self.secrets.append(access_token)
        if session_mode == "cookie" and len(list(self.cookie_jar)) == 0:
            raise ValidationFailure("Cookie session mode did not set a browser session cookie.")
        self.auth_session = AuthSession(
            session_mode=session_mode,
            access_token=access_token if isinstance(access_token, str) else None,
            csrf_token=csrf_token if isinstance(csrf_token, str) and csrf_token else None,
        )
        if self.auth_session.csrf_token:
            self.secrets.append(self.auth_session.csrf_token)
        if self.auth_session.session_mode == "cookie" and not self.auth_session.csrf_token:
            self.auth_session = AuthSession(
                session_mode=self.auth_session.session_mode,
                access_token=self.auth_session.access_token,
                csrf_token=self.fetch_csrf_token(),
            )
        self.evidence["operator"]["session_mode"] = self.auth_session.session_mode
        self.print_status("ok", label, f"Operator login succeeded using {self.auth_session.session_mode} session mode.")

    def fetch_csrf_token(self) -> str | None:
        payload = self.request(
            method="GET",
            url=build_url(self.config.api_url, "/v1/auth/csrf-token"),
            expect_statuses={200},
        )
        data = self.parse_json(payload, "CSRF token")
        if not isinstance(data, dict):
            return None
        token = data.get("csrf_token")
        if isinstance(token, str) and token:
            self.secrets.append(token)
            return token
        return None

    def auth_headers(self) -> tuple[str | None, str | None]:
        if self.auth_session is None:
            raise ValidationFailure("Authentication state is not initialized.")
        token = self.auth_session.access_token if self.auth_session.session_mode == "token" else None
        csrf_token = self.auth_session.csrf_token if self.auth_session.session_mode == "cookie" else None
        return token, csrf_token

    def authenticated_get(self, path: str, label: str) -> Any:
        token, _ = self.auth_headers()
        payload = self.request(
            method="GET",
            url=build_url(self.config.api_url, path),
            token=token,
            expect_statuses={200},
        )
        return self.parse_json(payload, label)

    def append_warning(self, message: str) -> None:
        warnings = self.evidence.setdefault("warnings", [])
        if isinstance(warnings, list) and message not in warnings:
            warnings.append(message)

    def emit_evidence_summary(self) -> None:
        summary = redact_text(
            json.dumps(self.evidence, sort_keys=True, separators=(",", ":")),
            self.secrets,
        )
        print(f"[evidence] {summary}")

    def get_tools_summary_data(self, label: str) -> list[dict[str, Any]]:
        if self.tools_summary_cache is None:
            data = self.authenticated_get("/v1/tools/summary", label)
            if not isinstance(data, list):
                raise ValidationFailure(f"{label} did not return a list.")
            self.tools_summary_cache = [item for item in data if isinstance(item, dict)]
        return self.tools_summary_cache

    def check_current_user(self, label: str) -> None:
        data = self.authenticated_get("/v1/auth/me", label)
        if not isinstance(data, dict):
            raise ValidationFailure(f"{label} returned an unexpected shape.")
        if not data.get("is_active"):
            raise ValidationFailure("Authenticated operator account is not active.")
        role = str(data.get("role") or "unknown")
        self.evidence["operator"] = {
            **(self.evidence.get("operator") or {}),
            "role": role,
            "tenant_id_present": bool(data.get("tenant_id")),
        }
        self.print_status("ok", label, f"Authenticated operator session is active (role={role}).")

    def check_settings_overview(self, label: str) -> None:
        data = self.authenticated_get("/v1/settings/overview", label)
        if not isinstance(data, dict) or not {"tenant", "keys", "rate_limiter"} <= set(data.keys()):
            raise ValidationFailure(f"{label} returned an unexpected shape.")
        github_connectors = data.get("github_connectors") or {}
        rate_limiter = data.get("rate_limiter") or {}
        self.evidence["api"]["settings_overview"] = {
            "tenant_status": str(((data.get("tenant") or {}).get("status")) or "unknown"),
            "github_connector_status": str(github_connectors.get("status") or "unknown"),
            "rate_limiter_status": str(rate_limiter.get("status") or "unknown"),
        }
        self.print_status("ok", label, "Settings overview is reachable.")

    def check_onboarding_status(self, label: str) -> None:
        data = self.authenticated_get("/v1/onboarding/status", label)
        if not isinstance(data, dict) or "recommended_next_step" not in data or "checklist" not in data:
            raise ValidationFailure(f"{label} returned an unexpected shape.")
        self.print_status("ok", label, "Onboarding status is reachable.")

    def check_tools_summary(self, label: str) -> None:
        data = self.get_tools_summary_data(label)
        github_count = sum(1 for item in data if str(item.get("type") or "") == "github")
        self.evidence["api"]["tools_summary"] = {
            "total_connectors": len(data),
            "github_connectors": github_count,
        }
        self.print_status("ok", label, f"Tools summary is reachable ({len(data)} connector record(s), github={github_count}).")

    def check_github_connector_readiness(self, label: str) -> None:
        data = self.get_tools_summary_data("Tools summary")
        github_tools = [item for item in data if str(item.get("type") or "") == "github"]
        if not github_tools:
            message = "No GitHub connectors are configured for this tenant, so live GitHub readiness checks were skipped."
            self.evidence["github_connectors"] = {
                "count": 0,
                "status": "skipped",
                "note": message,
            }
            self.print_status("skip", label, message)
            return

        connector_summaries: list[dict[str, Any]] = []
        for connector in github_tools:
            tool_id = str(connector.get("id") or "").strip()
            if not tool_id:
                continue
            detail = self.authenticated_get(f"/v1/tools/{tool_id}/safe-detail", label)
            if not isinstance(detail, dict):
                raise ValidationFailure(f"{label} safe detail returned an unexpected shape for tool {tool_id}.")
            health = self.authenticated_get(f"/v1/tools/{tool_id}/health?probe=true", label)
            if not isinstance(health, dict):
                raise ValidationFailure(f"{label} health probe returned an unexpected shape for tool {tool_id}.")
            connector_summaries.append(
                {
                    "name": str(detail.get("name") or tool_id),
                    "enabled": bool(detail.get("enabled")),
                    "connector_mode": str(detail.get("connector_mode") or "unknown"),
                    "live_execution_ready": bool(detail.get("live_execution_ready")),
                    "health_status": str(detail.get("health_status") or "unknown"),
                    "status_summary": str(detail.get("status_summary") or "").strip() or None,
                    "probe_status": str(health.get("status") or "unknown"),
                    "probe_performed": bool(health.get("probe_performed")),
                    "can_connect": health.get("can_connect") if isinstance(health.get("can_connect"), bool) else None,
                    "latest_probe_error": str((((detail.get("last_probe") or {}).get("error_summary")) or "")).strip() or None,
                }
            )
        ready_count = sum(1 for item in connector_summaries if item["live_execution_ready"])
        self.evidence["github_connectors"] = {
            "count": len(connector_summaries),
            "ready_connectors": ready_count,
            "connectors": connector_summaries,
        }
        if ready_count == 0:
            message = "GitHub connector detail and live probes are reachable, but no connector is fully live-ready yet."
            self.append_warning(message)
            self.print_status("warn", label, message)
            return
        self.print_status("ok", label, f"GitHub connector detail and live probe are reachable ({ready_count}/{len(connector_summaries)} live-ready).")

    def check_jobs(self, label: str) -> None:
        data = self.authenticated_get("/v1/jobs", label)
        if not isinstance(data, list):
            raise ValidationFailure(f"{label} did not return a list.")
        self.evidence["jobs"] = {
            "visible_jobs": len(data),
        }
        self.print_status("ok", label, f"Jobs API is reachable ({len(data)} job record(s) visible).")

    def check_worker_status(self, label: str) -> None:
        data = self.authenticated_get("/v1/workers/status", label)
        if not isinstance(data, dict):
            raise ValidationFailure(f"{label} returned an unexpected shape.")
        running_workers = int(data.get("running_workers") or 0)
        total_workers = int(data.get("total_workers") or 0)
        stale_workers = int(data.get("stale_workers") or 0)
        stopped_workers = int(data.get("stopped_workers") or 0)
        self.evidence["workers"] = {
            "total_workers": total_workers,
            "running_workers": running_workers,
            "stale_workers": stale_workers,
            "stopped_workers": stopped_workers,
            "latest_heartbeat_at": data.get("latest_heartbeat_at"),
        }
        if running_workers < 1:
            raise ValidationFailure(
                f"{label} did not report an active worker (total={total_workers}, running={running_workers}, stale={stale_workers}, stopped={stopped_workers})."
            )
        self.print_status(
            "ok",
            label,
            f"Worker status is healthy enough for operator review (running={running_workers}, stale={stale_workers}, stopped={stopped_workers}).",
        )

    def check_audit_integrity(self, label: str) -> None:
        data = self.authenticated_get("/v1/audit-integrity/status", label)
        if not isinstance(data, dict) or "status" not in data or "chain_scope" not in data:
            raise ValidationFailure(f"{label} returned an unexpected shape.")
        self.evidence["audit_integrity"]["status"] = {
            "status": str(data.get("status") or "unknown"),
            "chain_scope": str(data.get("chain_scope") or "unknown"),
            "total_events": int(data.get("total_events") or 0),
            "anchored_events": int(data.get("anchored_events") or 0),
            "latest_sequence_number": data.get("latest_sequence_number"),
        }
        self.print_status("ok", label, f"Audit integrity status is reachable (status={data['status']}).")

    def check_audit_integrity_checkpoints(self, label: str) -> None:
        data = self.authenticated_get("/v1/audit-integrity/checkpoints", label)
        if not isinstance(data, list):
            raise ValidationFailure(f"{label} did not return a list.")
        if not data:
            message = "Audit-integrity checkpoint history is reachable, but no checkpoint documents exist yet."
            self.evidence["audit_integrity"]["checkpoints"] = {
                "count": 0,
                "status": "none_recorded",
            }
            self.append_warning(message)
            self.print_status("warn", label, message)
            return
        latest = data[0] if isinstance(data[0], dict) else {}
        self.evidence["audit_integrity"]["checkpoints"] = {
            "count": len(data),
            "latest_status": str(latest.get("status") or "unknown"),
            "latest_type": str(latest.get("checkpoint_type") or "unknown"),
            "latest_range": {
                "from_sequence_number": latest.get("from_sequence_number"),
                "to_sequence_number": latest.get("to_sequence_number"),
            },
        }
        self.print_status(
            "ok",
            label,
            f"Audit-integrity checkpoint history is reachable ({len(data)} checkpoint record(s), latest={latest.get('status', 'unknown')}).",
        )

    def check_metrics(self, label: str) -> None:
        payload = self.request(
            method="GET",
            url=build_url(self.config.api_url, "/metrics"),
            expect_statuses={200},
        )
        body = payload.body.decode("utf-8", errors="replace")
        if "agentgate_http_requests_total" not in body:
            raise ValidationFailure("/metrics did not contain the expected AgentGate metric prefix.")
        hostname = (urllib.parse.urlparse(self.config.api_url).hostname or "").strip().lower()
        loopback = hostname in {"127.0.0.1", "localhost", "::1"}
        self.evidence["metrics"] = {
            "checked": True,
            "mode": self.config.metrics_mode,
            "access_note": "loopback_checked" if loopback else "non_loopback_checked",
        }
        if not loopback:
            message = "Metrics endpoint is reachable from a non-loopback path. Confirm this remains an internal or explicitly controlled operator route."
            self.append_warning(message)
            self.print_status("warn", label, message)
            return
        self.print_status("ok", label, "Metrics endpoint is reachable.")

    def check_logout(self, label: str) -> None:
        if self.auth_session is None:
            raise ValidationFailure("Authentication state is not initialized.")
        token, csrf_token = self.auth_headers()
        self.request(
            method="POST",
            url=build_url(self.config.api_url, "/v1/auth/logout"),
            token=token,
            csrf_token=csrf_token,
            json_body={},
            expect_statuses={200},
            allow_retry=False,
        )
        if self.auth_session.session_mode == "cookie":
            post_logout = self.request(
                method="GET",
                url=build_url(self.config.api_url, "/v1/auth/me"),
                expect_statuses={200, 401, 403},
                allow_retry=False,
            )
            if post_logout.status_code in {401, 403}:
                self.print_status("ok", label, "Logout cleared the browser session cookie.")
                return
            raise ValidationFailure("Cookie logout did not clear the browser session.")

        self.print_status(
            "ok",
            label,
            "Logout endpoint is reachable; token mode remains stateless and does not invalidate bearer tokens server-side.",
        )

    @staticmethod
    def print_status(level: str, label: str, detail: str) -> None:
        prefix = {
            "ok": "[ok]",
            "skip": "[skip]",
            "warn": "[warn]",
            "fail": "[fail]",
        }.get(level, "[info]")
        print(f"{prefix} {label}: {detail}")


def parse_args(argv: list[str]) -> ValidationConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Validate a running AgentGate deployment by checking health, readiness, "
            "web reachability, operator login, and a small set of safe control-plane APIs."
        ),
        epilog=(
            "Exit codes: 0=success, 1=validation failed, 2=invalid configuration, 3=unexpected runtime error."
        ),
    )
    parser.add_argument("--api-url", default=env_or_default("AGENTGATE_VALIDATE_API_URL"), help="Base API URL, for example https://api.agentgate.example.com")
    parser.add_argument("--web-url", default=env_or_default("AGENTGATE_VALIDATE_WEB_URL"), help="Base web URL, for example https://agentgate.example.com")
    parser.add_argument("--email", default=env_or_default("AGENTGATE_VALIDATE_EMAIL"), help="Operator email used for validation login")
    parser.add_argument("--password", default=env_or_default("AGENTGATE_VALIDATE_PASSWORD"), help="Operator password used for validation login")
    parser.add_argument("--tenant-slug", default=env_or_default("AGENTGATE_VALIDATE_TENANT_SLUG"), help="Tenant slug used for validation login")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=parse_float_setting("AGENTGATE_VALIDATE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        help="Per-request timeout in seconds",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=parse_int_setting("AGENTGATE_VALIDATE_RETRIES", DEFAULT_RETRIES),
        help="Retry count for transient connection and 5xx failures",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=parse_float_setting("AGENTGATE_VALIDATE_RETRY_DELAY_SECONDS", DEFAULT_RETRY_DELAY_SECONDS),
        help="Delay between retries in seconds",
    )
    parser.add_argument(
        "--metrics",
        default=env_or_default("AGENTGATE_VALIDATE_CHECK_METRICS", "auto"),
        help="Metrics validation mode: auto, true, false, always, or never",
    )
    args = parser.parse_args(argv)

    missing = [
        name
        for name, value in {
            "--api-url / AGENTGATE_VALIDATE_API_URL": args.api_url,
            "--web-url / AGENTGATE_VALIDATE_WEB_URL": args.web_url,
            "--email / AGENTGATE_VALIDATE_EMAIL": args.email,
            "--password / AGENTGATE_VALIDATE_PASSWORD": args.password,
            "--tenant-slug / AGENTGATE_VALIDATE_TENANT_SLUG": args.tenant_slug,
        }.items()
        if not value
    ]
    if missing:
        raise ConfigError(f"Missing required validation settings: {', '.join(missing)}")
    if args.timeout_seconds <= 0:
        raise ConfigError("timeout-seconds must be greater than zero.")
    if args.retries < 0:
        raise ConfigError("retries must be zero or greater.")
    if args.retry_delay_seconds < 0:
        raise ConfigError("retry-delay-seconds must be zero or greater.")

    return ValidationConfig(
        api_url=normalize_base_url(args.api_url, "API URL"),
        web_url=normalize_base_url(args.web_url, "Web URL"),
        email=str(args.email),
        password=str(args.password),
        tenant_slug=str(args.tenant_slug),
        timeout_seconds=float(args.timeout_seconds),
        retries=int(args.retries),
        retry_delay_seconds=float(args.retry_delay_seconds),
        metrics_mode=parse_metrics_mode(args.metrics),
    )


def main(argv: list[str] | None = None) -> int:
    try:
        config = parse_args(argv or sys.argv[1:])
        validator = DeploymentValidator(config)
        return validator.run()
    except ConfigError as exc:
        print(f"[fail] Configuration: {redact_text(str(exc), [])}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except ValidationFailure as exc:
        print(f"[fail] Validation: {redact_text(str(exc), [])}", file=sys.stderr)
        return EXIT_VALIDATION_FAILED
    except KeyboardInterrupt:
        print("[fail] Validation: interrupted by user.", file=sys.stderr)
        return EXIT_RUNTIME_ERROR
    except Exception as exc:
        print(f"[fail] Runtime: {redact_text(str(exc), [])}", file=sys.stderr)
        return EXIT_RUNTIME_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
