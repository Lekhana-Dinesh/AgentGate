from __future__ import annotations

import json
from time import sleep
from typing import Callable

import httpx

from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_string
from app.tools.base import ToolExecutionAdapter, ToolExecutionRequest
from app.tools.mcp_auth import ConfiguredMCPAuthProvider, MCPAuthContext, MCPAuthProvider

DEFAULT_TIMEOUT_MS = 10000
DEFAULT_MAX_REQUEST_BYTES = 65536
DEFAULT_MAX_RESPONSE_BYTES = 262144
DEFAULT_MAX_READ_RETRIES = 1
DEFAULT_RETRY_BACKOFF_SECONDS = 0.2
READ_ACTIONS = {"list_tools"}
WRITE_ACTIONS = {"call_tool"}
ALLOWED_ACTIONS = READ_ACTIONS | WRITE_ACTIONS
DESTRUCTIVE_ACTION_KEYWORDS = {"delete", "remove", "destroy", "purge"}
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}
JSON_RPC_VERSION = "2.0"
LIST_TOOLS_METHOD = "tools/list"
CALL_TOOL_METHOD = "tools/call"
READ_REMOTE_TOOL_KEYWORDS = {"get", "list", "read", "search", "query", "lookup", "fetch"}
logger = get_logger(__name__)


class MCPToolAdapter(ToolExecutionAdapter):
    adapter_name = "mcp"

    def __init__(
        self,
        client_factory: Callable[..., httpx.Client] | None = None,
        auth_provider: MCPAuthProvider | None = None,
    ) -> None:
        self.client_factory = client_factory
        self.auth_provider = auth_provider or ConfiguredMCPAuthProvider()

    def supports(self, request: ToolExecutionRequest) -> bool:
        return request.tool_type == "mcp"

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
            if action == "list_tools":
                payload = self._request_jsonrpc(
                    client,
                    method_name=LIST_TOOLS_METHOD,
                    params={},
                    retryable=True,
                    max_attempts=max_attempts,
                    backoff_seconds=backoff_seconds,
                    config=request.config,
                )
                tools = self._filter_visible_tools(payload.get("tools"), request.config)
                return {
                    "count": len(tools),
                    "tools": [
                        {
                            "name": tool["name"],
                            "description": tool.get("description"),
                            "input_schema": tool.get("inputSchema"),
                        }
                        for tool in tools
                    ],
                }

            if action == "call_tool":
                remote_tool_name = self._require_remote_tool_name(request.arguments)
                self._assert_remote_tool_allowed(remote_tool_name, request.config)
                tool_arguments = request.arguments.get("arguments")
                if tool_arguments is None:
                    tool_arguments = {}
                if not isinstance(tool_arguments, dict):
                    raise AppError(
                        "MCP tool arguments must be a JSON object.",
                        status_code=422,
                        code="mcp_tool_arguments_invalid",
                    )
                payload = self._request_jsonrpc(
                    client,
                    method_name=CALL_TOOL_METHOD,
                    params={"name": remote_tool_name, "arguments": tool_arguments},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    config=request.config,
                )
                return {
                    "tool_name": remote_tool_name,
                    "is_error": bool(payload.get("isError", False)),
                    "content": payload.get("content"),
                    "structured_content": payload.get("structuredContent"),
                }

        raise AppError(
            "MCP action is not allowed by this connector.",
            status_code=400,
            code="mcp_action_not_allowed",
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
        if not probe:
            return response

        timeout = self._build_timeout(config)
        try:
            with self._build_client(
                base_url=resolved_base_url,
                auth_headers=auth_context.auth_headers,
                timeout=timeout,
            ) as client:
                payload = self._request_jsonrpc(
                    client,
                    method_name=LIST_TOOLS_METHOD,
                    params={},
                    retryable=False,
                    max_attempts=1,
                    backoff_seconds=0.0,
                    config=config,
                )
            visible_tools = self._filter_visible_tools(payload.get("tools"), config)
            response.update(
                {
                    "probe_performed": True,
                    "can_connect": True,
                    "status": "ready",
                    "details": {
                        **(response.get("details") or {}),
                        "visible_tool_count": len(visible_tools),
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
                        "error_detail": self._sanitize_message(exc.detail),
                    },
                }
            )
            return response

    def _assert_action_allowed(self, action_name: str) -> None:
        if action_name in ALLOWED_ACTIONS:
            return
        if any(keyword in action_name for keyword in DESTRUCTIVE_ACTION_KEYWORDS):
            raise AppError(
                "Destructive MCP actions are blocked by the connector.",
                status_code=403,
                code="mcp_destructive_action_blocked",
            )
        raise AppError(
            "MCP action is not allowed by this connector.",
            status_code=400,
            code="mcp_action_not_allowed",
        )

    def _require_base_url(self, base_url: str | None) -> str:
        normalized = str(base_url or "").strip().rstrip("/")
        if not normalized:
            raise AppError(
                "MCP base_url is required for this connector.",
                status_code=422,
                code="mcp_base_url_required",
            )
        return normalized

    def _build_health_response(
        self,
        *,
        auth_context: MCPAuthContext,
        config: dict,
    ) -> dict:
        status = "ready" if auth_context.credentials_configured else "unconfigured"
        if auth_context.provider_name == "none":
            status = "ready"
        if auth_context.warnings:
            status = "degraded" if auth_context.credentials_configured else "unconfigured"
        return {
            "adapter": self.adapter_name,
            "auth_provider": auth_context.provider_name,
            "token_env_var": auth_context.token_env_var,
            "api_key_env_var": auth_context.api_key_env_var,
            "token_present": auth_context.token_present,
            "credentials_configured": auth_context.credentials_configured,
            "probe_performed": False,
            "can_connect": None,
            "status": status,
            "transport": str((config or {}).get("transport") or "http"),
            "trust_domain": str((config or {}).get("trust_domain") or "unknown"),
            "allowed_tool_count": len((config or {}).get("allowed_tool_names") or []),
            "blocked_tool_count": len((config or {}).get("blocked_tool_names") or []),
            "max_request_bytes": int((config or {}).get("max_request_bytes") or DEFAULT_MAX_REQUEST_BYTES),
            "max_response_bytes": int((config or {}).get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES),
            "timeout_ms": int((config or {}).get("timeout_ms") or DEFAULT_TIMEOUT_MS),
            "warnings": list(auth_context.warnings),
        }

    def _build_unhealthy_health_response(self, *, config: dict, exc: AppError) -> dict:
        return {
            "adapter": self.adapter_name,
            "auth_provider": str((config or {}).get("auth_mode") or "unknown"),
            "token_env_var": str((config or {}).get("token_env_var") or "").strip() or None,
            "api_key_env_var": str((config or {}).get("api_key_env_var") or "").strip() or None,
            "token_present": False,
            "credentials_configured": False,
            "probe_performed": False,
            "can_connect": None,
            "status": self._health_status_from_error_code(exc.code),
            "transport": str((config or {}).get("transport") or "http"),
            "trust_domain": str((config or {}).get("trust_domain") or "unknown"),
            "allowed_tool_count": len((config or {}).get("allowed_tool_names") or []),
            "blocked_tool_count": len((config or {}).get("blocked_tool_names") or []),
            "max_request_bytes": int((config or {}).get("max_request_bytes") or DEFAULT_MAX_REQUEST_BYTES),
            "max_response_bytes": int((config or {}).get("max_response_bytes") or DEFAULT_MAX_RESPONSE_BYTES),
            "timeout_ms": int((config or {}).get("timeout_ms") or DEFAULT_TIMEOUT_MS),
            "warnings": [],
            "details": {
                "error_code": exc.code,
                "error_detail": self._sanitize_message(exc.detail),
            },
        }

    def _health_status_from_error_code(self, code: str | None) -> str:
        if code == "mcp_auth_mode_unsupported":
            return "unsupported"
        if code in {"mcp_credentials_missing", "mcp_base_url_required"}:
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
            "Content-Type": "application/json",
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

    def _request_jsonrpc(
        self,
        client: httpx.Client,
        *,
        method_name: str,
        params: dict,
        retryable: bool,
        max_attempts: int,
        backoff_seconds: float,
        config: dict,
    ) -> dict:
        request_body = self._build_rpc_request(method_name=method_name, params=params)
        self._assert_request_size_allowed(request_body, config)

        attempts = max(1, max_attempts if retryable else 1)
        for attempt in range(1, attempts + 1):
            try:
                response = client.request("POST", "", json=request_body)
            except httpx.TimeoutException as exc:
                if retryable and attempt < attempts:
                    self._sleep_before_retry(backoff_seconds, attempt)
                    continue
                raise AppError(
                    "MCP server did not respond before the connector timeout elapsed.",
                    status_code=503,
                    code="mcp_upstream_unavailable",
                ) from exc
            except httpx.RequestError as exc:
                if retryable and attempt < attempts:
                    self._sleep_before_retry(backoff_seconds, attempt)
                    continue
                raise AppError(
                    "MCP server is temporarily unavailable.",
                    status_code=503,
                    code="mcp_upstream_unavailable",
                ) from exc

            self._assert_response_size_allowed(response, config)
            if response.status_code < 400:
                return self._parse_rpc_response(response)
            if retryable and attempt < attempts and response.status_code in RETRYABLE_STATUS_CODES:
                logger.info(
                    "mcp_read_retry",
                    extra={
                        "event_type": "mcp_read_retry",
                        "status_code": response.status_code,
                    },
                )
                self._sleep_before_retry(backoff_seconds, attempt)
                continue
            self._raise_upstream_error(response)

        raise AppError(
            "MCP request failed unexpectedly.",
            status_code=503,
            code="mcp_upstream_unavailable",
        )

    def _build_rpc_request(self, *, method_name: str, params: dict) -> dict:
        return {
            "jsonrpc": JSON_RPC_VERSION,
            "id": f"agentgate-{method_name.replace('/', '-')}",
            "method": method_name,
            "params": params,
        }

    def _parse_rpc_response(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AppError(
                "MCP server returned an invalid JSON response.",
                status_code=502,
                code="mcp_response_invalid",
            ) from exc

        if not isinstance(payload, dict):
            raise AppError(
                "MCP server returned an invalid JSON response.",
                status_code=502,
                code="mcp_response_invalid",
            )
        if payload.get("error"):
            raise AppError(
                "MCP server reported a tool-call error.",
                status_code=502,
                code="mcp_request_failed",
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise AppError(
                "MCP server returned an invalid result payload.",
                status_code=502,
                code="mcp_response_invalid",
            )
        return result

    def _raise_upstream_error(self, response: httpx.Response) -> None:
        extra = {"mcp_status_code": response.status_code}

        if response.status_code == 401:
            raise AppError(
                "MCP authentication failed. Check the configured credentials.",
                status_code=502,
                code="mcp_auth_failed",
                extra=extra,
            )
        if response.status_code == 403:
            raise AppError(
                "MCP server rejected the request.",
                status_code=502,
                code="mcp_forbidden",
                extra=extra,
            )
        if response.status_code == 404:
            raise AppError(
                "MCP server or tool resource was not found.",
                status_code=404,
                code="mcp_resource_not_found",
                extra=extra,
            )
        if response.status_code == 408:
            raise AppError(
                "MCP server did not complete the request before timing out.",
                status_code=503,
                code="mcp_upstream_timeout",
                extra=extra,
            )
        if response.status_code == 413:
            raise AppError(
                "MCP server rejected the request as too large.",
                status_code=413,
                code="mcp_upstream_payload_too_large",
                extra=extra,
            )
        if response.status_code == 429:
            raise AppError(
                "MCP server rate limited the connector request.",
                status_code=503,
                code="mcp_rate_limited",
                extra=extra,
            )
        if response.status_code >= 500:
            raise AppError(
                "MCP server is temporarily unavailable.",
                status_code=503,
                code="mcp_upstream_unavailable",
                extra=extra,
            )
        raise AppError(
            "MCP server rejected the request.",
            status_code=400,
            code="mcp_request_failed",
            extra=extra,
        )

    def _build_timeout(self, config: dict) -> httpx.Timeout:
        timeout_ms = int((config or {}).get("timeout_ms", DEFAULT_TIMEOUT_MS))
        timeout_seconds = timeout_ms / 1000.0
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

    def _require_remote_tool_name(self, arguments: dict) -> str:
        remote_tool_name = str(arguments.get("tool_name") or "").strip()
        if not remote_tool_name:
            raise AppError(
                "MCP tool_name is required.",
                status_code=422,
                code="mcp_tool_name_required",
            )
        return remote_tool_name

    def _assert_remote_tool_allowed(self, remote_tool_name: str, config: dict) -> None:
        allowlist = self._normalized_name_set((config or {}).get("allowed_tool_names") or [])
        blocked = self._normalized_name_set((config or {}).get("blocked_tool_names") or [])
        normalized_name = remote_tool_name.casefold()
        if not allowlist:
            raise AppError(
                "MCP allowed_tool_names must be configured before call_tool is allowed.",
                status_code=422,
                code="mcp_allowed_tool_names_required",
            )
        if normalized_name in blocked:
            raise AppError(
                "MCP tool is blocked by connector policy.",
                status_code=403,
                code="mcp_tool_blocked",
            )
        if normalized_name not in allowlist:
            raise AppError(
                "MCP tool is not allowlisted for this connector.",
                status_code=403,
                code="mcp_tool_not_allowed",
            )

    def _filter_visible_tools(self, raw_tools, config: dict) -> list[dict]:
        if not isinstance(raw_tools, list):
            return []
        allowlist = self._normalized_name_set((config or {}).get("allowed_tool_names") or [])
        blocked = self._normalized_name_set((config or {}).get("blocked_tool_names") or [])
        visible: list[dict] = []
        seen: set[str] = set()
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            normalized_name = name.casefold()
            if normalized_name in seen:
                continue
            if allowlist and normalized_name not in allowlist:
                continue
            if normalized_name in blocked:
                continue
            seen.add(normalized_name)
            visible.append(item)
        return visible

    def _assert_request_size_allowed(self, request_body: dict, config: dict) -> None:
        max_request_bytes = int((config or {}).get("max_request_bytes", DEFAULT_MAX_REQUEST_BYTES))
        encoded = json.dumps(request_body, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if len(encoded) > max_request_bytes:
            raise AppError(
                "MCP request payload exceeds the configured size limit.",
                status_code=413,
                code="mcp_request_too_large",
            )

    def _assert_response_size_allowed(self, response: httpx.Response, config: dict) -> None:
        max_response_bytes = int((config or {}).get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES))
        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                if int(content_length) > max_response_bytes:
                    raise AppError(
                        "MCP response payload exceeds the configured size limit.",
                        status_code=502,
                        code="mcp_response_too_large",
                    )
            except ValueError:
                pass
        if len(response.content) > max_response_bytes:
            raise AppError(
                "MCP response payload exceeds the configured size limit.",
                status_code=502,
                code="mcp_response_too_large",
            )

    def _normalized_name_set(self, values: list[object]) -> set[str]:
        return {
            str(value).strip().casefold()
            for value in values
            if str(value).strip()
        }

    def _sanitize_message(self, value: str) -> str:
        return redact_sensitive_string(str(value or ""))
