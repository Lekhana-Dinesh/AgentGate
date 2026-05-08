from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.enums import ToolType
from app.core.errors import AppError
from app.security.secret_references import SecretResolutionError, get_secret_resolver
from app.tools.github_auth import (
    DEFAULT_GITHUB_API_BASE_URL,
    DEFAULT_GITHUB_TOKEN_ENV_VAR,
    GITHUB_AUTH_MODE_ENV_PAT,
    GITHUB_AUTH_MODE_ENV_TOKEN,
    GITHUB_AUTH_MODE_GITHUB_APP,
)
from app.tools.jira_auth import (
    DEFAULT_JIRA_API_TOKEN_ENV_VAR,
    DEFAULT_JIRA_EMAIL_ENV_VAR,
    DEFAULT_JIRA_TOKEN_ENV_VAR,
    JIRA_AUTH_MODE_BASIC_ENV,
    JIRA_AUTH_MODE_ENV_TOKEN,
    JIRA_SUPPORTED_AUTH_MODES,
)
from app.tools.mcp_auth import (
    DEFAULT_MCP_API_KEY_ENV_VAR,
    DEFAULT_MCP_TOKEN_ENV_VAR,
    MCP_AUTH_MODE_API_KEY_ENV,
    MCP_AUTH_MODE_BEARER_ENV,
    MCP_AUTH_MODE_NONE,
    MCP_SUPPORTED_AUTH_MODES,
)

GITHUB_SECRET_FIELDS = {
    "token",
    "access_token",
    "github_token",
    "pat",
    "personal_access_token",
    "private_key",
    "private_key_pem",
    "app_private_key",
}
ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GITHUB_LIST_FIELDS = {
    "repository_allowlist",
    "internal_repositories",
    "internal_owners",
    "public_repositories",
}
GITHUB_SUPPORTED_AUTH_MODES = {
    GITHUB_AUTH_MODE_ENV_PAT,
    GITHUB_AUTH_MODE_ENV_TOKEN,
    GITHUB_AUTH_MODE_GITHUB_APP,
}
JIRA_SECRET_FIELDS = {
    "token",
    "api_token",
    "password",
    "authorization",
    "auth_header",
    "basic_auth",
    "email",
}
JIRA_LIST_FIELDS = {
    "project_allowlist",
    "issue_type_allowlist",
    "external_project_keys",
    "transition_allowlist",
    "assignee_allowlist",
}
MCP_SECRET_FIELDS = {
    "token",
    "api_key",
    "authorization",
    "auth_header",
    "bearer_token",
    "headers",
}
MCP_LIST_FIELDS = {
    "allowed_tool_names",
    "blocked_tool_names",
}
MCP_SUPPORTED_TRANSPORTS = {"http"}
MCP_SUPPORTED_TRUST_DOMAINS = {"internal", "external", "unknown"}
PROJECT_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
SAFE_BROWSER_MANAGED_TOOL_TYPES = {
    ToolType.GITHUB,
    ToolType.JIRA,
    ToolType.MCP,
    ToolType.MOCK,
}
SAFE_BROWSER_SECRET_FIELD_MARKERS = (
    "token",
    "secret_ref",
    "private_key",
    "authorization",
    "auth_header",
    "headers",
    "api_key_env_var",
    "token_env_var",
    "email_env_var",
)
DEFAULT_GITHUB_APP_PRIVATE_KEY_ENV_VAR = "AGENTGATE_GITHUB_APP_PRIVATE_KEY"


def validate_tool_configuration(
    tool_type: ToolType,
    *,
    base_url: str | None,
    config: dict | None,
) -> tuple[str | None, dict]:
    normalized_base_url = _normalize_base_url(base_url)
    normalized_config = _normalize_config(config)

    if tool_type == ToolType.GITHUB:
        normalized_config = _validate_github_configuration(normalized_config)
    elif tool_type == ToolType.JIRA:
        if not normalized_base_url:
            raise AppError(
                "Jira tools require base_url.",
                status_code=422,
                code="jira_base_url_required",
            )
        normalized_config = _validate_jira_configuration(normalized_config)
    elif tool_type == ToolType.MCP:
        if not normalized_base_url:
            raise AppError(
                "MCP tools require base_url.",
                status_code=422,
                code="mcp_base_url_required",
            )
        normalized_config = _validate_mcp_configuration(normalized_config)

    return normalized_base_url, normalized_config


def validate_browser_safe_tool_fields(extra_fields: dict | None) -> None:
    if not extra_fields:
        return

    extra_keys = sorted(str(key).strip() for key in extra_fields.keys() if str(key).strip())
    if not extra_keys:
        return

    secret_like_fields = [
        key
        for key in extra_keys
        if any(marker in key.lower() for marker in SAFE_BROWSER_SECRET_FIELD_MARKERS)
    ]
    if secret_like_fields:
        raise AppError(
            "Browser connector metadata only accepts non-secret fields. Configure credentials outside AgentGate.",
            status_code=422,
            code="tool_safe_metadata_secret_fields_forbidden",
        )

    raise AppError(
        "Browser connector metadata contains unsupported fields.",
        status_code=422,
        code="tool_safe_metadata_fields_forbidden",
        extra={"fields": extra_keys},
    )


def build_safe_tool_configuration(
    tool_type: ToolType,
    *,
    existing_base_url: str | None,
    existing_config: dict | None,
    metadata: dict,
) -> tuple[str | None, dict]:
    if tool_type not in SAFE_BROWSER_MANAGED_TOOL_TYPES:
        raise AppError(
            "This tool type is not supported by the browser metadata workflow.",
            status_code=422,
            code="tool_safe_metadata_type_unsupported",
        )

    normalized_base_url = (
        _normalize_safe_browser_base_url(metadata.get("base_url"))
        if "base_url" in metadata
        else existing_base_url
    )
    config = dict(existing_config or {})

    if tool_type == ToolType.GITHUB:
        normalized_base_url = normalized_base_url or existing_base_url or DEFAULT_GITHUB_API_BASE_URL
        auth_mode = str(
            metadata.get("auth_mode") or config.get("auth_mode") or GITHUB_AUTH_MODE_ENV_TOKEN
        ).strip().lower()
        config["auth_mode"] = auth_mode
        for field in GITHUB_LIST_FIELDS:
            if field in metadata:
                config[field] = _normalize_string_list(metadata.get(field))
        if auth_mode in {GITHUB_AUTH_MODE_ENV_PAT, GITHUB_AUTH_MODE_ENV_TOKEN}:
            config["token_env_var"] = str(config.get("token_env_var") or DEFAULT_GITHUB_TOKEN_ENV_VAR).strip()
            for key in ("app_id", "installation_id", "private_key_env_var", "private_key_secret_ref"):
                config.pop(key, None)
        elif auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
            if "app_id" in metadata or "app_id" in config:
                config["app_id"] = str(metadata.get("app_id") or config.get("app_id") or "").strip()
            if "installation_id" in metadata or "installation_id" in config:
                config["installation_id"] = str(
                    metadata.get("installation_id") or config.get("installation_id") or ""
                ).strip()
            private_key_secret_ref = str(config.get("private_key_secret_ref") or "").strip()
            if private_key_secret_ref:
                config["private_key_secret_ref"] = private_key_secret_ref
                config.pop("private_key_env_var", None)
            else:
                config["private_key_env_var"] = str(
                    config.get("private_key_env_var") or DEFAULT_GITHUB_APP_PRIVATE_KEY_ENV_VAR
                ).strip()
                config.pop("private_key_secret_ref", None)
            config.pop("token_env_var", None)
        return validate_tool_configuration(tool_type, base_url=normalized_base_url, config=config)

    if tool_type == ToolType.JIRA:
        auth_mode = str(
            metadata.get("auth_mode") or config.get("auth_mode") or JIRA_AUTH_MODE_ENV_TOKEN
        ).strip().lower()
        config["auth_mode"] = auth_mode
        for field in JIRA_LIST_FIELDS:
            if field in metadata:
                config[field] = _normalize_string_list(metadata.get(field))
        if auth_mode == JIRA_AUTH_MODE_ENV_TOKEN:
            config["token_env_var"] = str(config.get("token_env_var") or DEFAULT_JIRA_TOKEN_ENV_VAR).strip()
            config.pop("api_token_env_var", None)
            config.pop("email_env_var", None)
        elif auth_mode == JIRA_AUTH_MODE_BASIC_ENV:
            config["api_token_env_var"] = str(
                config.get("api_token_env_var") or DEFAULT_JIRA_API_TOKEN_ENV_VAR
            ).strip()
            config["email_env_var"] = str(
                config.get("email_env_var") or DEFAULT_JIRA_EMAIL_ENV_VAR
            ).strip()
            config.pop("token_env_var", None)
        return validate_tool_configuration(tool_type, base_url=normalized_base_url, config=config)

    if tool_type == ToolType.MCP:
        config["transport"] = str(metadata.get("transport") or config.get("transport") or "http").strip().lower()
        auth_mode = str(metadata.get("auth_mode") or config.get("auth_mode") or MCP_AUTH_MODE_NONE).strip().lower()
        config["auth_mode"] = auth_mode
        for field in MCP_LIST_FIELDS:
            if field in metadata:
                config[field] = _normalize_string_list(metadata.get(field))
        if "trust_domain" in metadata or "trust_domain" in config:
            config["trust_domain"] = str(
                metadata.get("trust_domain") or config.get("trust_domain") or "unknown"
            ).strip().lower()
        if auth_mode == MCP_AUTH_MODE_BEARER_ENV:
            config["token_env_var"] = str(config.get("token_env_var") or DEFAULT_MCP_TOKEN_ENV_VAR).strip()
            config.pop("api_key_env_var", None)
        elif auth_mode == MCP_AUTH_MODE_API_KEY_ENV:
            config["api_key_env_var"] = str(
                config.get("api_key_env_var") or DEFAULT_MCP_API_KEY_ENV_VAR
            ).strip()
            config.pop("token_env_var", None)
        else:
            config.pop("token_env_var", None)
            config.pop("api_key_env_var", None)
        return validate_tool_configuration(tool_type, base_url=normalized_base_url, config=config)

    config["mock"] = True
    return validate_tool_configuration(tool_type, base_url=None, config=config)


def _normalize_base_url(base_url: str | None) -> str | None:
    if base_url is None:
        return None
    normalized = base_url.strip()
    if not normalized:
        return None

    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError(
            "Tool base_url must be a valid http or https URL.",
            status_code=422,
            code="tool_base_url_invalid",
        )
    return normalized.rstrip("/")


def _normalize_safe_browser_base_url(base_url: str | None) -> str | None:
    normalized = _normalize_base_url(base_url)
    if normalized is None:
        return None

    parsed = urlparse(normalized)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AppError(
            "Browser connector metadata only accepts clean http or https base_url values without embedded credentials, query strings, or fragments.",
            status_code=422,
            code="tool_safe_base_url_invalid",
        )
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")


def _normalize_config(config: dict | None) -> dict:
    if config is None:
        return {}
    if not isinstance(config, dict):
        raise AppError(
            "Tool config must be a JSON object.",
            status_code=422,
            code="tool_config_invalid",
        )
    return dict(config)


def _normalize_string_list(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise AppError(
            "Browser connector metadata list fields must be arrays of strings.",
            status_code=422,
            code="tool_safe_metadata_list_invalid",
        )
    normalized_values: list[str] = []
    for item in value:
        normalized = str(item or "").strip()
        if normalized:
            normalized_values.append(normalized)
    return normalized_values


def _validate_github_configuration(config: dict) -> dict:
    secret_fields = sorted(field for field in GITHUB_SECRET_FIELDS if field in config)
    if secret_fields:
        raise AppError(
            "GitHub credentials and private keys must not be stored in tool config. Use token_env_var or a secret reference instead.",
            status_code=422,
            code="github_raw_token_forbidden",
            extra={"fields": secret_fields},
        )

    auth_mode = str(config.get("auth_mode") or GITHUB_AUTH_MODE_ENV_PAT).strip().lower()
    if auth_mode not in GITHUB_SUPPORTED_AUTH_MODES:
        raise AppError(
            "GitHub auth_mode is not supported in this build.",
            status_code=422,
            code="github_auth_mode_unsupported",
        )
    config["auth_mode"] = auth_mode

    token_env_var = str(config.get("token_env_var") or "").strip()
    if auth_mode in {GITHUB_AUTH_MODE_ENV_PAT, GITHUB_AUTH_MODE_ENV_TOKEN}:
        if not token_env_var:
            raise AppError(
                "GitHub tool config requires token_env_var for env_token auth.",
                status_code=422,
                code="github_token_env_var_required",
            )
        if not ENV_VAR_PATTERN.match(token_env_var):
            raise AppError(
                "GitHub token_env_var must be a valid environment variable name.",
                status_code=422,
                code="github_token_env_var_invalid",
            )
        config["token_env_var"] = token_env_var
    elif token_env_var:
        if not ENV_VAR_PATTERN.match(token_env_var):
            raise AppError(
                "GitHub token_env_var must be a valid environment variable name.",
                status_code=422,
                code="github_token_env_var_invalid",
            )
        config["token_env_var"] = token_env_var

    if auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
        config = _validate_github_app_configuration(config)

    timeout_seconds = config.get("timeout_seconds")
    if timeout_seconds is not None:
        try:
            parsed_timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "GitHub timeout_seconds must be numeric.",
                status_code=422,
                code="github_timeout_invalid",
            ) from exc
        if parsed_timeout <= 0 or parsed_timeout > 60:
            raise AppError(
                "GitHub timeout_seconds must be between 0 and 60 seconds.",
                status_code=422,
                code="github_timeout_out_of_range",
            )
        config["timeout_seconds"] = parsed_timeout

    max_read_retries = config.get("max_read_retries")
    if max_read_retries is not None:
        try:
            parsed_retries = int(max_read_retries)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "GitHub max_read_retries must be an integer.",
                status_code=422,
                code="github_retry_count_invalid",
            ) from exc
        if parsed_retries < 0 or parsed_retries > 3:
            raise AppError(
                "GitHub max_read_retries must be between 0 and 3.",
                status_code=422,
                code="github_retry_count_out_of_range",
            )
        config["max_read_retries"] = parsed_retries

    retry_backoff_seconds = config.get("retry_backoff_seconds")
    if retry_backoff_seconds is not None:
        try:
            parsed_backoff = float(retry_backoff_seconds)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "GitHub retry_backoff_seconds must be numeric.",
                status_code=422,
                code="github_retry_backoff_invalid",
            ) from exc
        if parsed_backoff < 0 or parsed_backoff > 5:
            raise AppError(
                "GitHub retry_backoff_seconds must be between 0 and 5 seconds.",
                status_code=422,
                code="github_retry_backoff_out_of_range",
            )
        config["retry_backoff_seconds"] = parsed_backoff

    for field in GITHUB_LIST_FIELDS:
        if field not in config or config[field] is None:
            continue
        if not isinstance(config[field], list):
            raise AppError(
                f"GitHub config field {field} must be a list of strings.",
                status_code=422,
                code="github_config_list_invalid",
                extra={"field": field},
            )
        normalized_values: list[str] = []
        for value in config[field]:
            normalized = str(value).strip().lower()
            if not normalized:
                raise AppError(
                    f"GitHub config field {field} contains an empty entry.",
                    status_code=422,
                    code="github_config_entry_invalid",
                    extra={"field": field},
                )
            normalized_values.append(normalized)
        config[field] = sorted(set(normalized_values))

    return config


def _validate_github_app_configuration(config: dict) -> dict:
    app_id = _normalize_positive_identifier(config.get("app_id"), field="app_id")
    installation_id = _normalize_positive_identifier(config.get("installation_id"), field="installation_id")
    private_key_env_var = str(config.get("private_key_env_var") or "").strip() or None
    private_key_secret_ref = str(config.get("private_key_secret_ref") or "").strip() or None

    if bool(private_key_env_var) == bool(private_key_secret_ref):
        raise AppError(
            "GitHub App auth requires exactly one of private_key_env_var or private_key_secret_ref.",
            status_code=422,
            code="github_app_private_key_reference_required",
        )
    if private_key_env_var:
        if not ENV_VAR_PATTERN.match(private_key_env_var):
            raise AppError(
                "GitHub private_key_env_var must be a valid environment variable name.",
                status_code=422,
                code="github_app_private_key_env_var_invalid",
            )
        config["private_key_env_var"] = private_key_env_var
    if private_key_secret_ref:
        try:
            parsed_reference = get_secret_resolver().parse(private_key_secret_ref, allow_bare_env=False)
        except SecretResolutionError as exc:
            raise AppError(
                "GitHub private_key_secret_ref must use a valid secret reference.",
                status_code=422,
                code="github_app_private_key_secret_ref_invalid",
            ) from exc
        config["private_key_secret_ref"] = parsed_reference.display_ref

    token_cache_ttl_seconds = config.get("token_cache_ttl_seconds")
    if token_cache_ttl_seconds is not None:
        try:
            parsed_ttl = int(token_cache_ttl_seconds)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "GitHub token_cache_ttl_seconds must be an integer.",
                status_code=422,
                code="github_app_token_cache_ttl_invalid",
            ) from exc
        if parsed_ttl < 1 or parsed_ttl > 3600:
            raise AppError(
                "GitHub token_cache_ttl_seconds must be between 1 and 3600 seconds.",
                status_code=422,
                code="github_app_token_cache_ttl_out_of_range",
            )
        config["token_cache_ttl_seconds"] = parsed_ttl

    config["app_id"] = app_id
    config["installation_id"] = installation_id
    return config


def _validate_jira_configuration(config: dict) -> dict:
    secret_fields = sorted(field for field in JIRA_SECRET_FIELDS if field in config)
    if secret_fields:
        raise AppError(
            "Jira credentials must not be stored in tool config. Use environment variable references instead.",
            status_code=422,
            code="jira_raw_credentials_forbidden",
            extra={"fields": secret_fields},
        )

    auth_mode = str(config.get("auth_mode") or JIRA_AUTH_MODE_ENV_TOKEN).strip().lower()
    if auth_mode not in JIRA_SUPPORTED_AUTH_MODES:
        raise AppError(
            "Jira auth_mode is not supported in this build.",
            status_code=422,
            code="jira_auth_mode_unsupported",
        )
    config["auth_mode"] = auth_mode

    token_env_var = str(config.get("token_env_var") or "").strip()
    api_token_env_var = str(config.get("api_token_env_var") or "").strip()
    email_env_var = str(config.get("email_env_var") or "").strip()

    if auth_mode == JIRA_AUTH_MODE_ENV_TOKEN:
        if not token_env_var:
            raise AppError(
                "Jira env_token auth requires token_env_var.",
                status_code=422,
                code="jira_token_env_var_required",
            )
        if not ENV_VAR_PATTERN.match(token_env_var):
            raise AppError(
                "Jira token_env_var must be a valid environment variable name.",
                status_code=422,
                code="jira_token_env_var_invalid",
            )
        config["token_env_var"] = token_env_var
    if auth_mode == JIRA_AUTH_MODE_BASIC_ENV:
        if not api_token_env_var:
            raise AppError(
                "Jira basic_env auth requires api_token_env_var.",
                status_code=422,
                code="jira_api_token_env_var_required",
            )
        if not ENV_VAR_PATTERN.match(api_token_env_var):
            raise AppError(
                "Jira api_token_env_var must be a valid environment variable name.",
                status_code=422,
                code="jira_api_token_env_var_invalid",
            )
        if not email_env_var:
            raise AppError(
                "Jira basic_env auth requires email_env_var.",
                status_code=422,
                code="jira_email_env_var_required",
            )
        if not ENV_VAR_PATTERN.match(email_env_var):
            raise AppError(
                "Jira email_env_var must be a valid environment variable name.",
                status_code=422,
                code="jira_email_env_var_invalid",
            )
        config["api_token_env_var"] = api_token_env_var
        config["email_env_var"] = email_env_var
    else:
        if api_token_env_var or email_env_var:
            raise AppError(
                "Jira basic_env-only fields are not allowed when auth_mode=env_token.",
                status_code=422,
                code="jira_basic_env_fields_forbidden",
            )

    timeout_seconds = config.get("timeout_seconds")
    if timeout_seconds is not None:
        try:
            parsed_timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "Jira timeout_seconds must be numeric.",
                status_code=422,
                code="jira_timeout_invalid",
            ) from exc
        if parsed_timeout <= 0 or parsed_timeout > 60:
            raise AppError(
                "Jira timeout_seconds must be between 0 and 60 seconds.",
                status_code=422,
                code="jira_timeout_out_of_range",
            )
        config["timeout_seconds"] = parsed_timeout

    max_read_retries = config.get("max_read_retries")
    if max_read_retries is not None:
        try:
            parsed_retries = int(max_read_retries)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "Jira max_read_retries must be an integer.",
                status_code=422,
                code="jira_retry_count_invalid",
            ) from exc
        if parsed_retries < 0 or parsed_retries > 3:
            raise AppError(
                "Jira max_read_retries must be between 0 and 3.",
                status_code=422,
                code="jira_retry_count_out_of_range",
            )
        config["max_read_retries"] = parsed_retries

    retry_backoff_seconds = config.get("retry_backoff_seconds")
    if retry_backoff_seconds is not None:
        try:
            parsed_backoff = float(retry_backoff_seconds)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "Jira retry_backoff_seconds must be numeric.",
                status_code=422,
                code="jira_retry_backoff_invalid",
            ) from exc
        if parsed_backoff < 0 or parsed_backoff > 5:
            raise AppError(
                "Jira retry_backoff_seconds must be between 0 and 5 seconds.",
                status_code=422,
                code="jira_retry_backoff_out_of_range",
            )
        config["retry_backoff_seconds"] = parsed_backoff

    for field in JIRA_LIST_FIELDS:
        if field not in config or config[field] is None:
            continue
        if not isinstance(config[field], list):
            raise AppError(
                f"Jira config field {field} must be a list of strings.",
                status_code=422,
                code="jira_config_list_invalid",
                extra={"field": field},
            )
        normalized_values: list[str] = []
        for value in config[field]:
            normalized = str(value).strip()
            if not normalized:
                raise AppError(
                    f"Jira config field {field} contains an empty entry.",
                    status_code=422,
                    code="jira_config_entry_invalid",
                    extra={"field": field},
                )
            if field in {"project_allowlist", "external_project_keys"}:
                normalized = normalized.upper()
                if not PROJECT_KEY_PATTERN.fullmatch(normalized):
                    raise AppError(
                        f"Jira config field {field} must contain valid project keys.",
                        status_code=422,
                        code="jira_project_key_invalid",
                        extra={"field": field},
                    )
            else:
                normalized = normalized.lower()
            normalized_values.append(normalized)
        config[field] = sorted(set(normalized_values))

    if not config.get("project_allowlist"):
        raise AppError(
            "Jira project_allowlist must contain at least one project key.",
            status_code=422,
            code="jira_project_allowlist_required",
        )

    return config


def _validate_mcp_configuration(config: dict) -> dict:
    secret_fields = sorted(field for field in MCP_SECRET_FIELDS if field in config)
    if secret_fields:
        raise AppError(
            "MCP credentials must not be stored in tool config. Use environment variable references instead.",
            status_code=422,
            code="mcp_raw_credentials_forbidden",
            extra={"fields": secret_fields},
        )

    transport = str(config.get("transport") or "http").strip().lower()
    if transport not in MCP_SUPPORTED_TRANSPORTS:
        raise AppError(
            "MCP transport is not supported in this build.",
            status_code=422,
            code="mcp_transport_unsupported",
        )
    config["transport"] = transport

    auth_mode = str(config.get("auth_mode") or MCP_AUTH_MODE_NONE).strip().lower()
    if auth_mode not in MCP_SUPPORTED_AUTH_MODES:
        raise AppError(
            "MCP auth_mode is not supported in this build.",
            status_code=422,
            code="mcp_auth_mode_unsupported",
        )
    config["auth_mode"] = auth_mode

    token_env_var = str(config.get("token_env_var") or "").strip()
    api_key_env_var = str(config.get("api_key_env_var") or "").strip()

    if auth_mode == MCP_AUTH_MODE_BEARER_ENV:
        if not token_env_var:
            raise AppError(
                "MCP bearer_env auth requires token_env_var.",
                status_code=422,
                code="mcp_token_env_var_required",
            )
        if not ENV_VAR_PATTERN.match(token_env_var):
            raise AppError(
                "MCP token_env_var must be a valid environment variable name.",
                status_code=422,
                code="mcp_token_env_var_invalid",
            )
        config["token_env_var"] = token_env_var
        if api_key_env_var:
            raise AppError(
                "MCP api_key_env_var is not allowed when auth_mode=bearer_env.",
                status_code=422,
                code="mcp_auth_fields_forbidden",
            )
    elif auth_mode == MCP_AUTH_MODE_API_KEY_ENV:
        if not api_key_env_var:
            raise AppError(
                "MCP api_key_env auth requires api_key_env_var.",
                status_code=422,
                code="mcp_api_key_env_var_required",
            )
        if not ENV_VAR_PATTERN.match(api_key_env_var):
            raise AppError(
                "MCP api_key_env_var must be a valid environment variable name.",
                status_code=422,
                code="mcp_api_key_env_var_invalid",
            )
        config["api_key_env_var"] = api_key_env_var
        if token_env_var:
            raise AppError(
                "MCP token_env_var is not allowed when auth_mode=api_key_env.",
                status_code=422,
                code="mcp_auth_fields_forbidden",
            )
    else:
        if token_env_var or api_key_env_var:
            raise AppError(
                "MCP auth env-var fields are not allowed when auth_mode=none.",
                status_code=422,
                code="mcp_auth_fields_forbidden",
            )

    for field in MCP_LIST_FIELDS:
        if field not in config or config[field] is None:
            continue
        if not isinstance(config[field], list):
            raise AppError(
                f"MCP config field {field} must be a list of strings.",
                status_code=422,
                code="mcp_config_list_invalid",
                extra={"field": field},
            )
        normalized_values: list[str] = []
        seen: set[str] = set()
        for value in config[field]:
            normalized = str(value).strip()
            if not normalized or "\n" in normalized or "\r" in normalized:
                raise AppError(
                    f"MCP config field {field} contains an invalid entry.",
                    status_code=422,
                    code="mcp_config_entry_invalid",
                    extra={"field": field},
                )
            fingerprint = normalized.casefold()
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            normalized_values.append(normalized)
        config[field] = normalized_values

    if not config.get("allowed_tool_names"):
        raise AppError(
            "MCP allowed_tool_names must contain at least one tool name.",
            status_code=422,
            code="mcp_allowed_tool_names_required",
        )
    allowed = {item.casefold() for item in config.get("allowed_tool_names") or []}
    blocked = {item.casefold() for item in config.get("blocked_tool_names") or []}
    overlap = sorted(allowed & blocked)
    if overlap:
        raise AppError(
            "MCP allowed_tool_names and blocked_tool_names must not overlap.",
            status_code=422,
            code="mcp_tool_allowlist_conflict",
        )

    max_request_bytes = config.get("max_request_bytes")
    if max_request_bytes is not None:
        config["max_request_bytes"] = _bounded_integer_config(
            max_request_bytes,
            minimum=1024,
            maximum=1048576,
            detail="MCP max_request_bytes must be between 1024 and 1048576.",
            code="mcp_max_request_bytes_invalid",
        )

    max_response_bytes = config.get("max_response_bytes")
    if max_response_bytes is not None:
        config["max_response_bytes"] = _bounded_integer_config(
            max_response_bytes,
            minimum=1024,
            maximum=1048576,
            detail="MCP max_response_bytes must be between 1024 and 1048576.",
            code="mcp_max_response_bytes_invalid",
        )

    timeout_ms = config.get("timeout_ms")
    if timeout_ms is not None:
        config["timeout_ms"] = _bounded_integer_config(
            timeout_ms,
            minimum=100,
            maximum=60000,
            detail="MCP timeout_ms must be between 100 and 60000.",
            code="mcp_timeout_invalid",
        )

    max_read_retries = config.get("max_read_retries")
    if max_read_retries is not None:
        config["max_read_retries"] = _bounded_integer_config(
            max_read_retries,
            minimum=0,
            maximum=3,
            detail="MCP max_read_retries must be between 0 and 3.",
            code="mcp_retry_count_invalid",
        )

    retry_backoff_seconds = config.get("retry_backoff_seconds")
    if retry_backoff_seconds is not None:
        try:
            parsed_backoff = float(retry_backoff_seconds)
        except (TypeError, ValueError) as exc:
            raise AppError(
                "MCP retry_backoff_seconds must be numeric.",
                status_code=422,
                code="mcp_retry_backoff_invalid",
            ) from exc
        if parsed_backoff < 0 or parsed_backoff > 5:
            raise AppError(
                "MCP retry_backoff_seconds must be between 0 and 5 seconds.",
                status_code=422,
                code="mcp_retry_backoff_invalid",
            )
        config["retry_backoff_seconds"] = parsed_backoff

    trust_domain = str(config.get("trust_domain") or "unknown").strip().lower()
    if trust_domain not in MCP_SUPPORTED_TRUST_DOMAINS:
        raise AppError(
            "MCP trust_domain must be internal, external, or unknown.",
            status_code=422,
            code="mcp_trust_domain_invalid",
        )
    config["trust_domain"] = trust_domain

    return config


def _normalize_positive_identifier(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise AppError(
            f"GitHub {field} is required for github_app auth.",
            status_code=422,
            code=f"github_app_{field}_required",
        )
    if not normalized.isdigit() or int(normalized) <= 0:
        raise AppError(
            f"GitHub {field} must be a positive integer.",
            status_code=422,
            code=f"github_app_{field}_invalid",
        )
    return normalized


def _bounded_integer_config(
    value: object,
    *,
    minimum: int,
    maximum: int,
    detail: str,
    code: str,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AppError(
            detail,
            status_code=422,
            code=code,
        ) from exc
    if parsed < minimum or parsed > maximum:
        raise AppError(
            detail,
            status_code=422,
            code=code,
        )
    return parsed
