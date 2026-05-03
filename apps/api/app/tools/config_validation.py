from __future__ import annotations

import re
from urllib.parse import urlparse

from app.core.enums import ToolType
from app.core.errors import AppError

GITHUB_SECRET_FIELDS = {
    "token",
    "access_token",
    "github_token",
    "pat",
    "personal_access_token",
}
ENV_VAR_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
GITHUB_LIST_FIELDS = {
    "repository_allowlist",
    "internal_repositories",
    "internal_owners",
    "public_repositories",
}
GITHUB_SUPPORTED_AUTH_MODES = {"env_pat"}


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

    return normalized_base_url, normalized_config


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


def _validate_github_configuration(config: dict) -> dict:
    secret_fields = sorted(field for field in GITHUB_SECRET_FIELDS if field in config)
    if secret_fields:
        raise AppError(
            "GitHub tokens must not be stored in tool config. Use token_env_var and an environment-backed secret instead.",
            status_code=422,
            code="github_raw_token_forbidden",
            extra={"fields": secret_fields},
        )

    token_env_var = str(config.get("token_env_var") or "").strip()
    if not token_env_var:
        raise AppError(
            "GitHub tool config requires token_env_var.",
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

    auth_mode = str(config.get("auth_mode") or "env_pat").strip().lower()
    if auth_mode not in GITHUB_SUPPORTED_AUTH_MODES:
        raise AppError(
            "GitHub auth_mode is not supported in this build.",
            status_code=422,
            code="github_auth_mode_unsupported",
        )
    config["auth_mode"] = auth_mode

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
