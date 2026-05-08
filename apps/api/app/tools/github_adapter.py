from __future__ import annotations

from time import sleep
from typing import Callable

import httpx

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_string
from app.tools.base import ToolExecutionAdapter, ToolExecutionRequest
from app.tools.github_auth import (
    ConfiguredGitHubAuthProvider,
    GITHUB_AUTH_MODE_ENV_PAT,
    GITHUB_AUTH_MODE_ENV_TOKEN,
    GITHUB_AUTH_MODE_GITHUB_APP,
    GitHubAuthContext,
    GitHubAuthProvider,
)

DEFAULT_GITHUB_API_BASE_URL = "https://api.github.com"
DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_READ_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.2
READ_ACTIONS = {
    "get_repository_metadata",
    "list_pull_requests",
    "get_pull_request_details",
}
WRITE_ACTIONS = {
    "create_issue",
    "comment_on_issue_or_pr",
}
ALLOWED_ACTIONS = READ_ACTIONS | WRITE_ACTIONS
DESTRUCTIVE_ACTION_KEYWORDS = {"delete", "remove", "destroy", "merge", "close", "reopen"}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
logger = get_logger(__name__)


class GitHubToolAdapter(ToolExecutionAdapter):
    adapter_name = "github"

    def __init__(
        self,
        client_factory: Callable[..., httpx.Client] | None = None,
        auth_provider: GitHubAuthProvider | None = None,
    ) -> None:
        self.client_factory = client_factory
        self.auth_provider = auth_provider or ConfiguredGitHubAuthProvider()

    def supports(self, request: ToolExecutionRequest) -> bool:
        return request.tool_type == "github"

    def execute(self, request: ToolExecutionRequest) -> dict:
        action = request.action_name.lower()
        self._assert_action_allowed(action)
        owner, repo = self._resolve_repository(request.arguments)
        repository = f"{owner}/{repo}"
        self._assert_repository_allowed(repository, request.config)
        base_url = request.base_url or DEFAULT_GITHUB_API_BASE_URL
        auth_context = self.auth_provider.get_auth_context(request.config, base_url=base_url)
        timeout = self._build_timeout(request.config)
        max_attempts, backoff_seconds = self._read_retry_config(request.config)

        with self._build_client(
            base_url=base_url,
            auth_headers=auth_context.auth_headers,
            timeout=timeout,
        ) as client:
            if action == "get_repository_metadata":
                payload = self._request_json(
                    client,
                    "GET",
                    f"/repos/{owner}/{repo}",
                    retryable=True,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    action_name=action,
                    repository=repository,
                )
                visibility = payload.get("visibility") or ("private" if payload.get("private") else "public")
                return {
                    "full_name": payload["full_name"],
                    "private": payload["private"],
                    "visibility": visibility,
                    "default_branch": payload["default_branch"],
                    "open_issues_count": payload.get("open_issues_count", 0),
                    "stargazers_count": payload.get("stargazers_count", 0),
                    "html_url": payload["html_url"],
                    "archived": payload.get("archived", False),
                }

            if action == "list_pull_requests":
                params = {
                    "state": request.arguments.get("state", "open"),
                    "per_page": int(request.arguments.get("per_page", 20)),
                }
                payload = self._request_json(
                    client,
                    "GET",
                    f"/repos/{owner}/{repo}/pulls",
                    params=params,
                    retryable=True,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    action_name=action,
                    repository=repository,
                )
                return {
                    "repository": repository,
                    "count": len(payload),
                    "pull_requests": [
                        {
                            "number": item["number"],
                            "title": item["title"],
                            "state": item["state"],
                            "draft": item.get("draft", False),
                            "html_url": item["html_url"],
                        }
                        for item in payload
                    ],
                }

            if action == "get_pull_request_details":
                pull_number = self._require_positive_integer(request.arguments, "pull_number")
                payload = self._request_json(
                    client,
                    "GET",
                    f"/repos/{owner}/{repo}/pulls/{pull_number}",
                    retryable=True,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    action_name=action,
                    repository=repository,
                )
                return {
                    "repository": repository,
                    "number": payload["number"],
                    "title": payload["title"],
                    "state": payload["state"],
                    "draft": payload.get("draft", False),
                    "merged": payload.get("merged", False),
                    "html_url": payload["html_url"],
                    "head_ref": payload["head"]["ref"],
                    "base_ref": payload["base"]["ref"],
                }

            if action == "create_issue":
                title = str(request.arguments.get("title", "")).strip()
                if not title:
                    raise AppError(
                        "GitHub issue title is required.",
                        status_code=422,
                        code="github_issue_title_required",
                    )
                body = {
                    "title": title,
                    "body": str(request.arguments.get("body", "")).strip() or None,
                    "labels": request.arguments.get("labels") or None,
                    "assignees": request.arguments.get("assignees") or None,
                }
                payload = self._request_json(
                    client,
                    "POST",
                    f"/repos/{owner}/{repo}/issues",
                    json_body=body,
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name=action,
                    repository=repository,
                )
                return {
                    "repository": repository,
                    "number": payload["number"],
                    "title": payload["title"],
                    "state": payload["state"],
                    "html_url": payload["html_url"],
                }

            if action == "comment_on_issue_or_pr":
                number = self._require_positive_integer(request.arguments, "number")
                comment_body = str(request.arguments.get("body", "")).strip()
                if not comment_body:
                    raise AppError(
                        "GitHub comment body is required.",
                        status_code=422,
                        code="github_comment_body_required",
                    )
                payload = self._request_json(
                    client,
                    "POST",
                    f"/repos/{owner}/{repo}/issues/{number}/comments",
                    json_body={"body": comment_body},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name=action,
                    repository=repository,
                )
                return {
                    "repository": repository,
                    "number": number,
                    "comment_id": payload["id"],
                    "html_url": payload["html_url"],
                    "created_at": payload["created_at"],
                }

        raise AppError(
            "GitHub action is not allowed by this connector.",
            status_code=400,
            code="github_action_not_allowed",
        )

    def health_check(
        self,
        *,
        base_url: str | None,
        config: dict,
        probe: bool = False,
    ) -> dict:
        resolved_base_url = base_url or DEFAULT_GITHUB_API_BASE_URL
        try:
            auth_context = self.auth_provider.get_auth_context(
                config,
                require_token=False,
                base_url=resolved_base_url,
            )
        except AppError as exc:
            return self._build_unhealthy_health_response(config=config, exc=exc)

        response = self._build_health_response(auth_context=auth_context, config=config)
        if not probe or not auth_context.credentials_configured:
            return response

        timeout = self._build_timeout(config)
        try:
            probe_auth_context = auth_context
            if not probe_auth_context.token_present:
                probe_auth_context = self.auth_provider.get_auth_context(
                    config,
                    require_token=True,
                    base_url=resolved_base_url,
                )
                response.update(
                    {
                        "token_present": probe_auth_context.token_present,
                        "token_expires_at": probe_auth_context.token_expires_at,
                        "cache_hit": probe_auth_context.cache_hit,
                    }
                )
            with self._build_client(
                base_url=resolved_base_url,
                auth_headers=probe_auth_context.auth_headers,
                timeout=timeout,
            ) as client:
                payload = self._request_json(
                    client,
                    "GET",
                    "/rate_limit",
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name="health_check",
                    repository=None,
                )
            response.update(
                {
                    "probe_performed": True,
                    "can_connect": True,
                    "status": "ready",
                    "details": {
                        "core_rate_limit_remaining": (
                            (((payload.get("resources") or {}).get("core") or {}).get("remaining"))
                        ),
                    },
                }
            )
            return response
        except AppError as exc:
            response.update(
                {
                    "probe_performed": True,
                    "can_connect": False,
                    "status": self._health_status_from_error_code(exc.code),
                    "details": {
                        **(response.get("details") or {}),
                        "error_code": exc.code,
                        "error_detail": redact_sensitive_string(exc.detail),
                    },
                }
            )
            return response

    def _assert_action_allowed(self, action_name: str) -> None:
        if action_name in ALLOWED_ACTIONS:
            return
        if any(keyword in action_name for keyword in DESTRUCTIVE_ACTION_KEYWORDS):
            raise AppError(
                "Destructive GitHub actions are blocked by the connector.",
                status_code=403,
                code="github_destructive_action_blocked",
            )
        raise AppError(
            "GitHub action is not allowed by this connector.",
            status_code=400,
            code="github_action_not_allowed",
        )

    def _build_health_response(
        self,
        *,
        auth_context: GitHubAuthContext,
        config: dict,
    ) -> dict:
        status = "ready" if auth_context.credentials_configured else "unconfigured"
        if auth_context.warnings:
            status = "degraded" if auth_context.credentials_configured else "unconfigured"
        return {
            "adapter": self.adapter_name,
            "auth_provider": auth_context.provider_name,
            "token_env_var": auth_context.token_env_var,
            "secret_reference": auth_context.secret_reference,
            "token_present": auth_context.token_present,
            "credentials_configured": auth_context.credentials_configured,
            "probe_performed": False,
            "can_connect": None,
            "status": status,
            "repository_allowlist_count": len((config or {}).get("repository_allowlist") or []),
            "app_id": auth_context.app_id,
            "installation_id": auth_context.installation_id,
            "private_key_env_var": auth_context.private_key_env_var,
            "private_key_reference_type": auth_context.private_key_reference_type,
            "token_expires_at": auth_context.token_expires_at,
            "cache_hit": auth_context.cache_hit,
            "warnings": list(auth_context.warnings),
        }

    def _build_unhealthy_health_response(self, *, config: dict, exc: AppError) -> dict:
        return {
            "adapter": self.adapter_name,
            "auth_provider": self._configured_auth_provider_name(config),
            "token_env_var": str((config or {}).get("token_env_var") or "").strip() or None,
            "secret_reference": None,
            "token_present": False,
            "credentials_configured": False,
            "probe_performed": False,
            "can_connect": None,
            "status": self._health_status_from_error_code(exc.code),
            "repository_allowlist_count": len((config or {}).get("repository_allowlist") or []),
            "app_id": str((config or {}).get("app_id") or "").strip() or None,
            "installation_id": str((config or {}).get("installation_id") or "").strip() or None,
            "private_key_env_var": str((config or {}).get("private_key_env_var") or "").strip() or None,
            "private_key_reference_type": None,
            "token_expires_at": None,
            "cache_hit": False,
            "warnings": [],
            "details": {
                "error_code": exc.code,
                "error_detail": redact_sensitive_string(exc.detail),
            },
        }

    def _configured_auth_provider_name(self, config: dict) -> str:
        auth_mode = str((config or {}).get("auth_mode") or GITHUB_AUTH_MODE_ENV_PAT).strip().lower()
        if auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
            return GITHUB_AUTH_MODE_GITHUB_APP
        if auth_mode in {GITHUB_AUTH_MODE_ENV_PAT, GITHUB_AUTH_MODE_ENV_TOKEN}:
            return GITHUB_AUTH_MODE_ENV_TOKEN
        return auth_mode or "unknown"

    def _health_status_from_error_code(self, code: str | None) -> str:
        if code == "github_auth_mode_unsupported":
            return "unsupported"
        if code in {
            "github_credentials_missing",
            "github_app_credentials_missing",
        }:
            return "unconfigured"
        return "degraded"

    def _build_client(
        self,
        *,
        base_url: str,
        auth_headers: dict[str, str],
        timeout: httpx.Timeout,
    ) -> httpx.Client:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "AgentGate/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
            **auth_headers,
        }
        if self.client_factory:
            return self.client_factory(base_url=base_url, headers=headers, timeout=timeout)
        return httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def _request_json(
        self,
        client: httpx.Client,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        retryable: bool,
        max_attempts: int,
        backoff_seconds: float,
        action_name: str,
        repository: str | None,
    ):
        attempts = max(1, max_attempts if retryable else 1)
        for attempt in range(1, attempts + 1):
            try:
                response = client.request(method, path, params=params, json=json_body)
            except httpx.TimeoutException as exc:
                if retryable and attempt < attempts:
                    self._sleep_before_retry(backoff_seconds, attempt)
                    continue
                raise AppError(
                    "GitHub did not respond before the connector timeout elapsed.",
                    status_code=503,
                    code="github_upstream_unavailable",
                ) from exc
            except httpx.RequestError as exc:
                if retryable and attempt < attempts:
                    self._sleep_before_retry(backoff_seconds, attempt)
                    continue
                raise AppError(
                    "GitHub is temporarily unavailable.",
                    status_code=503,
                    code="github_upstream_unavailable",
                ) from exc

            if response.status_code < 400:
                return response.json()
            if retryable and attempt < attempts and response.status_code in RETRYABLE_STATUS_CODES:
                logger.info(
                    "github_read_retry",
                    extra={
                        "event_type": "github_read_retry",
                        "status_code": response.status_code,
                    },
                )
                self._sleep_before_retry(backoff_seconds, attempt)
                continue
            self._raise_upstream_error(response, action_name=action_name, repository=repository)

    def _raise_upstream_error(
        self,
        response: httpx.Response,
        *,
        action_name: str,
        repository: str | None,
    ) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = redact_sensitive_string(str(payload.get("message") or "GitHub request failed."))
        extra = {"github_status_code": response.status_code}
        if repository:
            extra["repository"] = repository
        extra["action_name"] = action_name

        if response.status_code == 401:
            raise AppError(
                "GitHub authentication failed. Check the configured credentials.",
                status_code=502,
                code="github_auth_failed",
                extra=extra,
            )
        if response.status_code == 403:
            raise AppError(
                message or "GitHub rejected the request.",
                status_code=502,
                code="github_forbidden",
                extra=extra,
            )
        if response.status_code == 404:
            raise AppError(
                "GitHub repository or resource was not found.",
                status_code=404,
                code="github_resource_not_found",
                extra=extra,
            )
        if response.status_code == 409:
            raise AppError(
                message or "GitHub reported a conflict for this request.",
                status_code=409,
                code="github_conflict",
                extra=extra,
            )
        if response.status_code == 422:
            raise AppError(
                message or "GitHub rejected the request payload.",
                status_code=422,
                code="github_validation_failed",
                extra=extra,
            )
        if response.status_code == 429:
            raise AppError(
                "GitHub rate limited the connector request.",
                status_code=503,
                code="github_rate_limited",
                extra=extra,
            )
        if response.status_code >= 500:
            raise AppError(
                "GitHub is temporarily unavailable.",
                status_code=503,
                code="github_upstream_unavailable",
                extra=extra,
            )
        raise AppError(
            message or "GitHub request failed.",
            status_code=400,
            code="github_request_failed",
            extra=extra,
        )

    def _build_timeout(self, config: dict) -> httpx.Timeout:
        timeout_seconds = float((config or {}).get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        return httpx.Timeout(
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )

    def _read_retry_config(self, config: dict) -> tuple[int, float]:
        max_retries = int((config or {}).get("max_read_retries", DEFAULT_MAX_READ_RETRIES))
        backoff_seconds = float((config or {}).get("retry_backoff_seconds", DEFAULT_RETRY_BACKOFF_SECONDS))
        return max(0, max_retries) + 1, max(0.0, backoff_seconds)

    def _sleep_before_retry(self, backoff_seconds: float, attempt: int) -> None:
        sleep(backoff_seconds * (2 ** (attempt - 1)))

    def _resolve_repository(self, arguments: dict) -> tuple[str, str]:
        repository = str(arguments.get("repository", "")).strip()
        if repository and "/" in repository:
            owner, repo = repository.split("/", 1)
            owner = owner.strip()
            repo = repo.strip()
            if owner and repo:
                return owner, repo

        owner = str(arguments.get("owner", "")).strip()
        repo = str(arguments.get("repo", "")).strip()
        if owner and repo:
            return owner, repo

        raise AppError(
            "GitHub repository must be provided as repository='owner/name' or owner + repo.",
            status_code=422,
            code="github_repository_required",
        )

    def _assert_repository_allowed(self, repository: str, config: dict) -> None:
        allowlist = {str(item).strip().lower() for item in ((config or {}).get("repository_allowlist") or [])}
        if allowlist and repository.lower() not in allowlist:
            raise AppError(
                "Repository is not allowed for this GitHub connector.",
                status_code=403,
                code="github_repository_forbidden",
                extra={"repository": repository},
            )

    def _require_positive_integer(self, arguments: dict, key: str) -> int:
        value = arguments.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise AppError(
                f"GitHub argument {key} must be a positive integer.",
                status_code=422,
                code="github_invalid_integer_argument",
            ) from exc
        if parsed <= 0:
            raise AppError(
                f"GitHub argument {key} must be a positive integer.",
                status_code=422,
                code="github_invalid_integer_argument",
            )
        return parsed
