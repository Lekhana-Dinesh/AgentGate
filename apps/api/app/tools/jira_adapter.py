from __future__ import annotations

import re
from time import sleep
from typing import Callable

import httpx

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.redaction import REDACTED_VALUE, redact_sensitive_string
from app.tools.base import ToolExecutionAdapter, ToolExecutionRequest
from app.tools.jira_auth import ConfiguredJiraAuthProvider, JiraAuthContext, JiraAuthProvider

DEFAULT_TIMEOUT_SECONDS = 15.0
DEFAULT_MAX_READ_RETRIES = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 0.2
READ_ACTIONS = {
    "get_issue",
    "search_issues",
}
WRITE_ACTIONS = {
    "create_issue",
    "add_comment",
    "transition_issue",
    "assign_issue",
}
ALLOWED_ACTIONS = READ_ACTIONS | WRITE_ACTIONS
DESTRUCTIVE_ACTION_KEYWORDS = {"delete", "remove", "destroy", "purge"}
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PROJECT_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
ISSUE_KEY_PATTERN = re.compile(r"^(?P<project>[A-Za-z][A-Za-z0-9_]*)-(?P<number>[1-9][0-9]*)$")
JIRA_BROWSE_PATH = "/browse"
logger = get_logger(__name__)


class JiraToolAdapter(ToolExecutionAdapter):
    adapter_name = "jira"

    def __init__(
        self,
        client_factory: Callable[..., httpx.Client] | None = None,
        auth_provider: JiraAuthProvider | None = None,
    ) -> None:
        self.client_factory = client_factory
        self.auth_provider = auth_provider or ConfiguredJiraAuthProvider()

    def supports(self, request: ToolExecutionRequest) -> bool:
        return request.tool_type == "jira"

    def execute(self, request: ToolExecutionRequest) -> dict:
        action = request.action_name.lower()
        self._assert_action_allowed(action)
        base_url = self._require_base_url(request.base_url)
        auth_context = self.auth_provider.get_auth_context(request.config, base_url=base_url)
        timeout = self._build_timeout(request.config)
        max_attempts, backoff_seconds = self._read_retry_config(request.config)

        with self._build_client(
            base_url=base_url,
            auth_headers=auth_context.auth_headers,
            timeout=timeout,
        ) as client:
            if action == "get_issue":
                issue_key = self._normalize_issue_key(request.arguments.get("issue_key"))
                self._assert_project_allowed(self._project_key_from_issue(issue_key), request.config)
                response = self._request(
                    client,
                    "GET",
                    f"/rest/api/3/issue/{issue_key}",
                    params={"fields": "summary,description,issuetype,status,assignee,reporter,project"},
                    retryable=True,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    action_name=action,
                    issue_key=issue_key,
                )
                return self._serialize_issue(response.json(), base_url=base_url)

            if action == "search_issues":
                search_payload = self._build_search_payload(request.arguments, request.config)
                response = self._request(
                    client,
                    "GET",
                    "/rest/api/3/search",
                    params=search_payload,
                    retryable=True,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    action_name=action,
                    issue_key=None,
                )
                payload = response.json()
                issues = [self._serialize_issue(item, base_url=base_url) for item in (payload.get("issues") or [])]
                return {
                    "count": len(issues),
                    "start_at": int(payload.get("startAt") or search_payload["startAt"]),
                    "max_results": int(payload.get("maxResults") or search_payload["maxResults"]),
                    "total": int(payload.get("total") or len(issues)),
                    "issues": issues,
                }

            if action == "create_issue":
                project_key = self._normalize_project_key(request.arguments.get("project_key"))
                self._assert_project_allowed(project_key, request.config)
                issue_type = self._resolve_issue_type(request.arguments.get("issue_type"), request.config)
                summary = str(request.arguments.get("summary") or "").strip()
                if not summary:
                    raise AppError(
                        "Jira issue summary is required.",
                        status_code=422,
                        code="jira_issue_summary_required",
                    )
                fields = {
                    "project": {"key": project_key},
                    "issuetype": {"name": issue_type},
                    "summary": summary,
                }
                description = str(request.arguments.get("description") or "").strip()
                if description:
                    fields["description"] = self._adf_document(description)
                labels = request.arguments.get("labels")
                if labels:
                    if not isinstance(labels, list):
                        raise AppError(
                            "Jira labels must be a list of strings.",
                            status_code=422,
                            code="jira_labels_invalid",
                        )
                    fields["labels"] = [str(item).strip() for item in labels if str(item).strip()]
                response = self._request(
                    client,
                    "POST",
                    "/rest/api/3/issue",
                    json_body={"fields": fields},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name=action,
                    issue_key=None,
                )
                payload = response.json()
                issue_key = str(payload.get("key") or "").strip() or None
                return {
                    "issue_id": str(payload.get("id") or "").strip() or None,
                    "issue_key": issue_key,
                    "browse_url": self._browse_url(base_url, issue_key) if issue_key else None,
                }

            if action == "add_comment":
                issue_key = self._normalize_issue_key(request.arguments.get("issue_key"))
                self._assert_project_allowed(self._project_key_from_issue(issue_key), request.config)
                body = str(request.arguments.get("body") or "").strip()
                if not body:
                    raise AppError(
                        "Jira comment body is required.",
                        status_code=422,
                        code="jira_comment_body_required",
                    )
                response = self._request(
                    client,
                    "POST",
                    f"/rest/api/3/issue/{issue_key}/comment",
                    json_body={"body": self._adf_document(body)},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name=action,
                    issue_key=issue_key,
                )
                payload = response.json()
                return {
                    "issue_key": issue_key,
                    "comment_id": str(payload.get("id") or "").strip() or None,
                    "created_at": payload.get("created"),
                }

            if action == "transition_issue":
                issue_key = self._normalize_issue_key(request.arguments.get("issue_key"))
                self._assert_project_allowed(self._project_key_from_issue(issue_key), request.config)
                transition = self._resolve_transition(request.arguments, request.config)
                self._request(
                    client,
                    "POST",
                    f"/rest/api/3/issue/{issue_key}/transitions",
                    json_body={"transition": transition},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name=action,
                    issue_key=issue_key,
                )
                return {
                    "issue_key": issue_key,
                    "transition": transition,
                    "status": "transition_requested",
                }

            if action == "assign_issue":
                issue_key = self._normalize_issue_key(request.arguments.get("issue_key"))
                self._assert_project_allowed(self._project_key_from_issue(issue_key), request.config)
                assignee_account_id = self._resolve_assignee(request.arguments, request.config)
                self._request(
                    client,
                    "PUT",
                    f"/rest/api/3/issue/{issue_key}/assignee",
                    json_body={"accountId": assignee_account_id},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name=action,
                    issue_key=issue_key,
                )
                return {
                    "issue_key": issue_key,
                    "assignee_account_id": assignee_account_id,
                    "status": "assignment_requested",
                }

        raise AppError(
            "Jira action is not allowed by this connector.",
            status_code=400,
            code="jira_action_not_allowed",
        )

    def health_check(
        self,
        *,
        base_url: str | None,
        config: dict,
        probe: bool = False,
    ) -> dict:
        resolved_base_url = self._require_base_url(base_url)
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
            with self._build_client(
                base_url=resolved_base_url,
                auth_headers=auth_context.auth_headers,
                timeout=timeout,
            ) as client:
                upstream_response = self._request(
                    client,
                    "GET",
                    "/rest/api/3/project/search",
                    params={"maxResults": 1},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    action_name="health_check",
                    issue_key=None,
                )
            payload = upstream_response.json()
            response.update(
                {
                    "probe_performed": True,
                    "can_connect": True,
                    "status": "ready",
                    "details": {
                        **(response.get("details") or {}),
                        "visible_projects": int(payload.get("total") or 0),
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
                        "error_detail": self._sanitize_upstream_message(exc.detail),
                    },
                }
            )
            return response

    def _assert_action_allowed(self, action_name: str) -> None:
        if action_name in ALLOWED_ACTIONS:
            return
        if any(keyword in action_name for keyword in DESTRUCTIVE_ACTION_KEYWORDS):
            raise AppError(
                "Destructive Jira actions are blocked by the connector.",
                status_code=403,
                code="jira_destructive_action_blocked",
            )
        raise AppError(
            "Jira action is not allowed by this connector.",
            status_code=400,
            code="jira_action_not_allowed",
        )

    def _require_base_url(self, base_url: str | None) -> str:
        normalized = str(base_url or "").strip().rstrip("/")
        if not normalized:
            raise AppError(
                "Jira base_url is required for this connector.",
                status_code=422,
                code="jira_base_url_required",
            )
        return normalized

    def _build_health_response(
        self,
        *,
        auth_context: JiraAuthContext,
        config: dict,
    ) -> dict:
        status = "ready" if auth_context.credentials_configured else "unconfigured"
        if auth_context.warnings:
            status = "degraded" if auth_context.credentials_configured else "unconfigured"
        return {
            "adapter": self.adapter_name,
            "auth_provider": auth_context.provider_name,
            "token_env_var": auth_context.token_env_var,
            "api_token_env_var": auth_context.api_token_env_var,
            "email_env_var": auth_context.email_env_var,
            "token_present": auth_context.token_present,
            "credentials_configured": auth_context.credentials_configured,
            "probe_performed": False,
            "can_connect": None,
            "status": status,
            "project_allowlist_count": len((config or {}).get("project_allowlist") or []),
            "issue_type_allowlist_count": len((config or {}).get("issue_type_allowlist") or []),
            "external_project_key_count": len((config or {}).get("external_project_keys") or []),
            "warnings": list(auth_context.warnings),
        }

    def _build_unhealthy_health_response(self, *, config: dict, exc: AppError) -> dict:
        return {
            "adapter": self.adapter_name,
            "auth_provider": str((config or {}).get("auth_mode") or "unknown"),
            "token_env_var": str((config or {}).get("token_env_var") or "").strip() or None,
            "api_token_env_var": str((config or {}).get("api_token_env_var") or "").strip() or None,
            "email_env_var": str((config or {}).get("email_env_var") or "").strip() or None,
            "token_present": False,
            "credentials_configured": False,
            "probe_performed": False,
            "can_connect": None,
            "status": self._health_status_from_error_code(exc.code),
            "project_allowlist_count": len((config or {}).get("project_allowlist") or []),
            "issue_type_allowlist_count": len((config or {}).get("issue_type_allowlist") or []),
            "external_project_key_count": len((config or {}).get("external_project_keys") or []),
            "warnings": [],
            "details": {
                "error_code": exc.code,
                "error_detail": self._sanitize_upstream_message(exc.detail),
            },
        }

    def _health_status_from_error_code(self, code: str | None) -> str:
        if code in {"jira_auth_mode_unsupported"}:
            return "unsupported"
        if code in {
            "jira_credentials_missing",
            "jira_base_url_required",
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
            "Accept": "application/json",
            "User-Agent": "AgentGate/0.1.0",
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

    def _request(
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
        issue_key: str | None,
    ) -> httpx.Response:
        attempts = max(1, max_attempts if retryable else 1)
        for attempt in range(1, attempts + 1):
            try:
                response = client.request(method, path, params=params, json=json_body)
            except httpx.TimeoutException as exc:
                if retryable and attempt < attempts:
                    self._sleep_before_retry(backoff_seconds, attempt)
                    continue
                raise AppError(
                    "Jira did not respond before the connector timeout elapsed.",
                    status_code=503,
                    code="jira_upstream_unavailable",
                ) from exc
            except httpx.RequestError as exc:
                if retryable and attempt < attempts:
                    self._sleep_before_retry(backoff_seconds, attempt)
                    continue
                raise AppError(
                    "Jira is temporarily unavailable.",
                    status_code=503,
                    code="jira_upstream_unavailable",
                ) from exc

            if response.status_code < 400:
                return response
            if retryable and attempt < attempts and response.status_code in RETRYABLE_STATUS_CODES:
                logger.info(
                    "jira_read_retry",
                    extra={
                        "event_type": "jira_read_retry",
                        "status_code": response.status_code,
                    },
                )
                self._sleep_before_retry(backoff_seconds, attempt)
                continue
            self._raise_upstream_error(response, action_name=action_name, issue_key=issue_key)

        raise AppError(
            "Jira request failed unexpectedly.",
            status_code=503,
            code="jira_upstream_unavailable",
        )

    def _raise_upstream_error(
        self,
        response: httpx.Response,
        *,
        action_name: str,
        issue_key: str | None,
    ) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        message = self._sanitize_upstream_message(str(payload.get("errorMessages") or payload.get("message") or ""))
        extra = {"jira_status_code": response.status_code, "action_name": action_name}
        if issue_key:
            extra["issue_key"] = issue_key

        if response.status_code == 401:
            raise AppError(
                "Jira authentication failed. Check the configured credentials.",
                status_code=502,
                code="jira_auth_failed",
                extra=extra,
            )
        if response.status_code == 403:
            raise AppError(
                "Jira rejected the request.",
                status_code=502,
                code="jira_forbidden",
                extra=extra,
            )
        if response.status_code == 404:
            raise AppError(
                "Jira issue or resource was not found.",
                status_code=404,
                code="jira_resource_not_found",
                extra=extra,
            )
        if response.status_code == 409:
            raise AppError(
                message or "Jira reported a conflict for this request.",
                status_code=409,
                code="jira_conflict",
                extra=extra,
            )
        if response.status_code in {400, 422}:
            raise AppError(
                message or "Jira rejected the request payload.",
                status_code=422,
                code="jira_validation_failed",
                extra=extra,
            )
        if response.status_code == 429:
            raise AppError(
                "Jira rate limited the connector request.",
                status_code=503,
                code="jira_rate_limited",
                extra=extra,
            )
        if response.status_code >= 500:
            raise AppError(
                "Jira is temporarily unavailable.",
                status_code=503,
                code="jira_upstream_unavailable",
                extra=extra,
            )
        raise AppError(
            message or "Jira request failed.",
            status_code=400,
            code="jira_request_failed",
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

    def _normalize_project_key(self, value: object) -> str:
        normalized = str(value or "").strip().upper()
        if not PROJECT_KEY_PATTERN.fullmatch(normalized):
            raise AppError(
                "Jira project_key must be a valid project key.",
                status_code=422,
                code="jira_project_key_invalid",
            )
        return normalized

    def _normalize_issue_key(self, value: object) -> str:
        normalized = str(value or "").strip().upper()
        match = ISSUE_KEY_PATTERN.fullmatch(normalized)
        if not match:
            raise AppError(
                "Jira issue_key must use the PROJECT-123 format.",
                status_code=422,
                code="jira_issue_key_invalid",
            )
        return normalized

    def _project_key_from_issue(self, issue_key: str) -> str:
        match = ISSUE_KEY_PATTERN.fullmatch(issue_key)
        if not match:
            raise AppError(
                "Jira issue_key must use the PROJECT-123 format.",
                status_code=422,
                code="jira_issue_key_invalid",
            )
        return str(match.group("project")).upper()

    def _assert_project_allowed(self, project_key: str, config: dict) -> None:
        allowlist = {
            self._normalize_project_key(item)
            for item in ((config or {}).get("project_allowlist") or [])
        }
        if not allowlist:
            raise AppError(
                "Jira project_allowlist must be configured for this connector.",
                status_code=422,
                code="jira_project_allowlist_required",
            )
        if project_key not in allowlist:
            raise AppError(
                "Project is not allowed for this Jira connector.",
                status_code=403,
                code="jira_project_forbidden",
                extra={"project_key": project_key},
            )

    def _resolve_issue_type(self, value: object, config: dict) -> str:
        issue_type = str(value or "").strip()
        if not issue_type:
            raise AppError(
                "Jira issue_type is required.",
                status_code=422,
                code="jira_issue_type_required",
            )
        allowlist = {
            str(item).strip().lower()
            for item in ((config or {}).get("issue_type_allowlist") or [])
            if str(item).strip()
        }
        if not allowlist:
            raise AppError(
                "Jira issue_type_allowlist must be configured before create_issue is allowed.",
                status_code=422,
                code="jira_issue_type_allowlist_required",
            )
        if issue_type.lower() not in allowlist:
            raise AppError(
                "Issue type is not allowed for this Jira connector.",
                status_code=403,
                code="jira_issue_type_forbidden",
                extra={"issue_type": issue_type.lower()},
            )
        return issue_type

    def _resolve_transition(self, arguments: dict, config: dict) -> dict[str, str]:
        allowlist = {
            str(item).strip().lower()
            for item in ((config or {}).get("transition_allowlist") or [])
            if str(item).strip()
        }
        if not allowlist:
            raise AppError(
                "Jira transition_allowlist must be configured before transition_issue is allowed.",
                status_code=422,
                code="jira_transition_allowlist_required",
            )

        transition_id = str(arguments.get("transition_id") or "").strip()
        transition_name = str(arguments.get("transition_name") or "").strip()
        if transition_id:
            if transition_id.lower() not in allowlist:
                raise AppError(
                    "Transition is not allowlisted for this Jira connector.",
                    status_code=403,
                    code="jira_transition_forbidden",
                )
            return {"id": transition_id}
        if transition_name:
            if transition_name.lower() not in allowlist:
                raise AppError(
                    "Transition is not allowlisted for this Jira connector.",
                    status_code=403,
                    code="jira_transition_forbidden",
                )
            return {"name": transition_name}
        raise AppError(
            "Jira transition_id or transition_name is required.",
            status_code=422,
            code="jira_transition_required",
        )

    def _resolve_assignee(self, arguments: dict, config: dict) -> str:
        allowlist = {
            str(item).strip().lower()
            for item in ((config or {}).get("assignee_allowlist") or [])
            if str(item).strip()
        }
        if not allowlist:
            raise AppError(
                "Jira assignee_allowlist must be configured before assign_issue is allowed.",
                status_code=422,
                code="jira_assignee_allowlist_required",
            )
        assignee = str(
            arguments.get("assignee_account_id")
            or arguments.get("account_id")
            or arguments.get("assignee")
            or ""
        ).strip()
        if not assignee:
            raise AppError(
                "Jira assignee_account_id is required.",
                status_code=422,
                code="jira_assignee_required",
            )
        if assignee.lower() not in allowlist:
            raise AppError(
                "Assignee is not allowlisted for this Jira connector.",
                status_code=403,
                code="jira_assignee_forbidden",
            )
        return assignee

    def _build_search_payload(self, arguments: dict, config: dict) -> dict[str, object]:
        max_results = self._bounded_int(arguments.get("max_results", 20), minimum=1, maximum=50, code="jira_max_results_invalid")
        start_at = self._bounded_int(arguments.get("start_at", 0), minimum=0, maximum=1000, code="jira_start_at_invalid")
        fields = "summary,description,issuetype,status,assignee,reporter,project"
        jql = self._build_search_jql(arguments, config)
        return {
            "jql": jql,
            "maxResults": max_results,
            "startAt": start_at,
            "fields": fields,
        }

    def _build_search_jql(self, arguments: dict, config: dict) -> str:
        allowlist = [
            self._normalize_project_key(item)
            for item in ((config or {}).get("project_allowlist") or [])
        ]
        if not allowlist:
            raise AppError(
                "Jira project_allowlist must be configured for search_issues.",
                status_code=422,
                code="jira_project_allowlist_required",
            )

        configured_projects = allowlist
        project_key = arguments.get("project_key")
        if project_key is not None:
            resolved_project = self._normalize_project_key(project_key)
            self._assert_project_allowed(resolved_project, config)
            configured_projects = [resolved_project]

        project_clause = (
            f"project = {configured_projects[0]}"
            if len(configured_projects) == 1
            else "project in (" + ",".join(configured_projects) + ")"
        )

        raw_jql = str(arguments.get("jql") or "").strip()
        if raw_jql:
            if len(raw_jql) > 512 or any(marker in raw_jql for marker in {"\n", "\r", ";"}):
                raise AppError(
                    "Jira jql must be a single safe expression no longer than 512 characters.",
                    status_code=422,
                    code="jira_jql_invalid",
                )
            return f"{project_clause} AND ({raw_jql})"

        clauses = [project_clause]

        status_value = str(arguments.get("status") or "").strip()
        if status_value:
            clauses.append(f"status = {self._quote_jql_value(status_value)}")

        issue_type_value = str(arguments.get("issue_type") or "").strip()
        if issue_type_value:
            resolved_issue_type = self._resolve_issue_type(issue_type_value, config)
            clauses.append(f"issuetype = {self._quote_jql_value(resolved_issue_type)}")

        assignee = str(arguments.get("assignee_account_id") or arguments.get("assignee") or "").strip()
        if assignee:
            clauses.append(f"assignee = {self._quote_jql_value(assignee)}")

        text_value = str(arguments.get("text") or "").strip()
        if text_value:
            clauses.append(f"text ~ {self._quote_jql_value(text_value)}")

        return " AND ".join(clauses)

    def _serialize_issue(self, payload: dict, *, base_url: str) -> dict:
        fields = payload.get("fields") or {}
        issue_key = str(payload.get("key") or "").strip() or None
        project = fields.get("project") or {}
        issue_type = fields.get("issuetype") or {}
        status = fields.get("status") or {}
        assignee = fields.get("assignee") or {}
        reporter = fields.get("reporter") or {}
        return {
            "issue_id": str(payload.get("id") or "").strip() or None,
            "issue_key": issue_key,
            "project_key": str((project.get("key") or "")).strip() or None,
            "summary": fields.get("summary"),
            "description": self._extract_adf_text(fields.get("description")),
            "issue_type": str((issue_type.get("name") or "")).strip() or None,
            "status": str((status.get("name") or "")).strip() or None,
            "assignee": {
                "account_id": str((assignee.get("accountId") or "")).strip() or None,
                "display_name": str((assignee.get("displayName") or "")).strip() or None,
            }
            if assignee
            else None,
            "reporter": {
                "account_id": str((reporter.get("accountId") or "")).strip() or None,
                "display_name": str((reporter.get("displayName") or "")).strip() or None,
            }
            if reporter
            else None,
            "browse_url": self._browse_url(base_url, issue_key) if issue_key else None,
        }

    def _browse_url(self, base_url: str, issue_key: str | None) -> str | None:
        if not issue_key:
            return None
        return f"{base_url}{JIRA_BROWSE_PATH}/{issue_key}"

    def _adf_document(self, text: str) -> dict:
        paragraphs = []
        for segment in [part.strip() for part in text.splitlines()]:
            if not segment:
                continue
            paragraphs.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": segment}],
                }
            )
        if not paragraphs:
            paragraphs = [{"type": "paragraph", "content": [{"type": "text", "text": text.strip()}]}]
        return {"type": "doc", "version": 1, "content": paragraphs}

    def _extract_adf_text(self, value) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if not isinstance(value, dict):
            return str(value)

        chunks: list[str] = []

        def _walk(node) -> None:
            if isinstance(node, dict):
                text_value = node.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    chunks.append(text_value.strip())
                for child in node.get("content") or []:
                    _walk(child)
            elif isinstance(node, list):
                for child in node:
                    _walk(child)

        _walk(value)
        return "\n".join(chunks) if chunks else None

    def _bounded_int(self, value: object, *, minimum: int, maximum: int, code: str) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "Jira numeric search parameter is invalid.",
                status_code=422,
                code=code,
            ) from exc
        if parsed < minimum or parsed > maximum:
            raise AppError(
                "Jira numeric search parameter is out of range.",
                status_code=422,
                code=code,
            )
        return parsed

    def _quote_jql_value(self, value: str) -> str:
        normalized = str(value or "").replace("\\", "\\\\").replace('"', '\\"').strip()
        return f'"{normalized}"'

    def _sanitize_upstream_message(self, value: str) -> str:
        redacted = redact_sensitive_string(str(value or ""))
        return EMAIL_PATTERN.sub(REDACTED_VALUE, redacted)
