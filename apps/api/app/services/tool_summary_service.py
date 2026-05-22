from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AuditActorType
from app.core.enums import ToolType
from app.core.errors import AppError
from app.models import Tool
from app.models.base import utcnow
from app.schemas.tool import (
    ToolCredentialReference,
    ToolProbeObservationResponse,
    ToolSafeDetailResponse,
    ToolSafeSummaryResponse,
)
from app.security.secret_references import SecretResolutionError, get_secret_resolver
from app.services.tool_health_service import ToolHealthService
from app.tools.github_adapter import ALLOWED_ACTIONS as GITHUB_ALLOWED_ACTIONS
from app.tools.github_auth import (
    DEFAULT_GITHUB_TOKEN_ENV_VAR,
    GITHUB_AUTH_MODE_ENV_PAT,
    GITHUB_AUTH_MODE_ENV_TOKEN,
    GITHUB_AUTH_MODE_GITHUB_APP,
)
from app.tools.jira_adapter import ALLOWED_ACTIONS as JIRA_ALLOWED_ACTIONS
from app.tools.jira_auth import JIRA_AUTH_MODE_BASIC_ENV, JIRA_AUTH_MODE_ENV_TOKEN
from app.tools.mcp_adapter import ALLOWED_ACTIONS as MCP_ALLOWED_ACTIONS
from app.tools.mcp_auth import MCP_AUTH_MODE_API_KEY_ENV, MCP_AUTH_MODE_BEARER_ENV, MCP_AUTH_MODE_NONE

SUPPORTED_ACTIONS_BY_TYPE: dict[ToolType, list[str]] = {
    ToolType.GITHUB: sorted(GITHUB_ALLOWED_ACTIONS),
    ToolType.JIRA: sorted(JIRA_ALLOWED_ACTIONS),
    ToolType.MCP: sorted(MCP_ALLOWED_ACTIONS),
}
SUPPORTED_AUTH_MODES_BY_TYPE: dict[ToolType, list[str]] = {
    ToolType.GITHUB: [GITHUB_AUTH_MODE_ENV_TOKEN, GITHUB_AUTH_MODE_ENV_PAT, GITHUB_AUTH_MODE_GITHUB_APP],
    ToolType.JIRA: [JIRA_AUTH_MODE_ENV_TOKEN, JIRA_AUTH_MODE_BASIC_ENV],
    ToolType.MCP: [MCP_AUTH_MODE_NONE, MCP_AUTH_MODE_BEARER_ENV, MCP_AUTH_MODE_API_KEY_ENV],
    ToolType.MOCK: [],
}
DOCUMENTATION_PATH_BY_TYPE: dict[ToolType, str] = {
    ToolType.GITHUB: "docs/connectors/github.md",
    ToolType.JIRA: "docs/connectors/jira.md",
    ToolType.MCP: "docs/connectors/mcp.md",
    ToolType.MOCK: "docs/operations/tool-management.md",
}


@dataclass(slots=True)
class _SafeToolGuidance:
    connector_mode: str = "not_applicable"
    live_execution_ready: bool = False
    status_summary: str | None = None
    credential_references: list[ToolCredentialReference] = field(default_factory=list)
    validation_messages: list[str] = field(default_factory=list)
    warning_flags: list[str] = field(default_factory=list)
    effective_health_status: str | None = None


class ToolSummaryService:
    def __init__(self, tool_health_service: ToolHealthService | None = None) -> None:
        self.tool_health_service = tool_health_service or ToolHealthService()

    def list_summaries(self, db: Session, *, tenant_id: str) -> list[ToolSafeSummaryResponse]:
        tools = list(
            db.scalars(
                select(Tool)
                .where(Tool.tenant_id == tenant_id)
                .order_by(Tool.created_at.desc())
            )
        )
        return [self._build_summary(tool=tool, probe=False) for tool in tools]

    def get_summary(
        self,
        db: Session,
        *,
        tenant_id: str,
        tool_id: str,
        probe: bool = False,
        actor_type: AuditActorType | None = None,
        actor_id: str | None = None,
        ip_address: str | None = None,
    ) -> ToolSafeSummaryResponse:
        tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id))
        if tool is None:
            raise AppError("Tool not found.", status_code=404, code="tool_not_found")
        health = self.tool_health_service.check(tool=tool, probe=probe)
        if probe and actor_type is not None:
            self.tool_health_service.record_probe_observation(
                db,
                tenant_id=tenant_id,
                tool=tool,
                response=health,
                actor_type=actor_type,
                actor_id=actor_id,
                ip_address=ip_address,
            )
            db.commit()
        return self._build_summary(tool=tool, probe=probe, health=health)

    def get_detail(
        self,
        db: Session,
        *,
        tenant_id: str,
        tool_id: str,
    ) -> ToolSafeDetailResponse:
        tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id))
        if tool is None:
            raise AppError("Tool not found.", status_code=404, code="tool_not_found")
        return self._build_detail(db=db, tool=tool)

    def _build_summary(self, *, tool: Tool, probe: bool, health=None) -> ToolSafeSummaryResponse:
        if health is None:
            health = self.tool_health_service.check(tool=tool, probe=probe)
        config = tool.config or {}
        trust_domain = str(config.get("trust_domain") or "").strip() or None
        guidance = self._build_guidance(tool=tool, config=config, health=health)
        effective_health_status = guidance.effective_health_status or health.status

        return ToolSafeSummaryResponse(
            id=tool.id,
            name=tool.name,
            type=tool.type,
            description=tool.description,
            enabled=tool.enabled,
            risk_level=tool.risk_level,
            base_url_host=self._safe_base_url_host(tool.base_url),
            auth_mode=str(config.get("auth_mode") or "").strip() or None,
            trust_domain=trust_domain,
            allowlist_counts=self._allowlist_counts(tool.type, config),
            supported_actions=list(SUPPORTED_ACTIONS_BY_TYPE.get(tool.type, [])),
            health_status=effective_health_status,
            health_can_connect=health.can_connect,
            health_probe_performed=health.probe_performed,
            health_checked_at=utcnow(),
            connector_mode=guidance.connector_mode,
            live_execution_ready=guidance.live_execution_ready,
            status_summary=guidance.status_summary,
            warning_flags=self._warning_flags(
                tool=tool,
                trust_domain=trust_domain,
                health_status=effective_health_status,
                extra_flags=guidance.warning_flags,
            ),
            created_at=tool.created_at,
            updated_at=tool.updated_at,
        )

    def _build_detail(self, *, db: Session, tool: Tool) -> ToolSafeDetailResponse:
        config = dict(tool.config or {})
        health = self.tool_health_service.check(tool=tool, probe=False)
        guidance = self._build_guidance(tool=tool, config=config, health=health)
        summary = self._build_summary(tool=tool, probe=False, health=health)
        latest_probe, latest_successful_probe_at, latest_failed_probe_at, latest_failed_probe_error_summary = (
            self.tool_health_service.get_latest_probe_observations(
                db,
                tenant_id=tool.tenant_id,
                tool_id=tool.id,
            )
        )
        safe_base_url = self._safe_base_url(tool.base_url)
        return ToolSafeDetailResponse(
            **summary.model_dump(),
            base_url=safe_base_url,
            documentation_path=DOCUMENTATION_PATH_BY_TYPE.get(tool.type),
            supported_auth_modes=list(SUPPORTED_AUTH_MODES_BY_TYPE.get(tool.type, [])),
            credential_references=guidance.credential_references,
            validation_messages=guidance.validation_messages,
            repository_allowlist=self._safe_list(config.get("repository_allowlist")),
            internal_repositories=self._safe_list(config.get("internal_repositories")),
            internal_owners=self._safe_list(config.get("internal_owners")),
            public_repositories=self._safe_list(config.get("public_repositories")),
            app_id=self._safe_string(config.get("app_id")),
            installation_id=self._safe_string(config.get("installation_id")),
            project_allowlist=self._safe_list(config.get("project_allowlist")),
            issue_type_allowlist=self._safe_list(config.get("issue_type_allowlist")),
            external_project_keys=self._safe_list(config.get("external_project_keys")),
            transition_allowlist=self._safe_list(config.get("transition_allowlist")),
            assignee_allowlist=self._safe_list(config.get("assignee_allowlist")),
            transport=self._safe_string(config.get("transport")),
            allowed_tool_names=self._safe_list(config.get("allowed_tool_names")),
            blocked_tool_names=self._safe_list(config.get("blocked_tool_names")),
            last_probe=(
                ToolProbeObservationResponse(
                    status=latest_probe.status,
                    checked_at=latest_probe.checked_at,
                    probe_performed=latest_probe.probe_performed,
                    can_connect=latest_probe.can_connect,
                    error_summary=latest_probe.error_summary,
                    source=latest_probe.source if latest_probe.source in {"manual_probe", "health_check_job"} else None,
                )
                if latest_probe is not None
                else None
            ),
            last_successful_probe_at=latest_successful_probe_at,
            last_failed_probe_at=latest_failed_probe_at,
            last_failed_probe_error_summary=latest_failed_probe_error_summary,
        )

    def _build_guidance(self, *, tool: Tool, config: dict, health) -> _SafeToolGuidance:
        if tool.type != ToolType.GITHUB:
            connector_mode = "not_applicable" if tool.type == ToolType.MOCK else "live_connector"
            return _SafeToolGuidance(
                connector_mode=connector_mode,
                live_execution_ready=bool(health.status == "ready"),
            )

        return self._build_github_guidance(config=config, health=health)

    def _build_github_guidance(self, *, config: dict, health) -> _SafeToolGuidance:
        auth_mode = str(config.get("auth_mode") or GITHUB_AUTH_MODE_ENV_PAT).strip().lower() or GITHUB_AUTH_MODE_ENV_PAT
        connector_mode = "demo_safe_mock" if bool(config.get("demo_safe_mock")) else "live_connector"
        allowlist = self._safe_list(config.get("repository_allowlist"))
        internal_repositories = self._safe_list(config.get("internal_repositories"))
        public_repositories = self._safe_list(config.get("public_repositories"))
        health_details = dict(health.details or {})
        credentials_configured = bool(health_details.get("credentials_configured"))

        guidance = _SafeToolGuidance(connector_mode=connector_mode)
        if connector_mode == "demo_safe_mock":
            guidance.validation_messages.append(
                "Demo-safe mock is active. The seeded governed GitHub workflow does not require a live GitHub call or live GitHub credentials."
            )
        else:
            guidance.validation_messages.append(
                "Live GitHub execution is selected. AgentGate still enforces governed policy and approval flow before side-effecting actions."
            )

        if auth_mode in {GITHUB_AUTH_MODE_ENV_PAT, GITHUB_AUTH_MODE_ENV_TOKEN}:
            token_env_var = str(config.get("token_env_var") or DEFAULT_GITHUB_TOKEN_ENV_VAR).strip() or DEFAULT_GITHUB_TOKEN_ENV_VAR
            guidance.credential_references.append(
                ToolCredentialReference(
                    key="token_env_var",
                    label="GitHub token env var",
                    reference_name=token_env_var,
                    reference_type="env",
                    configured=credentials_configured,
                )
            )
            if not credentials_configured:
                guidance.validation_messages.append(
                    f"Expected live credential binding {token_env_var} is not available in the current API environment."
                )
        elif auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
            app_id = self._safe_string(config.get("app_id"))
            installation_id = self._safe_string(config.get("installation_id"))
            if not app_id or not installation_id:
                guidance.validation_messages.append(
                    "GitHub App mode still needs both App ID and installation ID before live execution can be validated."
                )
            private_key_env_var = self._safe_string(config.get("private_key_env_var"))
            if private_key_env_var:
                guidance.credential_references.append(
                    ToolCredentialReference(
                        key="private_key_env_var",
                        label="GitHub App private key env var",
                        reference_name=private_key_env_var,
                        reference_type="env",
                        configured=credentials_configured,
                    )
                )
                if not credentials_configured:
                    guidance.validation_messages.append(
                        f"Expected GitHub App private key binding {private_key_env_var} is not available in the current API environment."
                    )
            else:
                private_key_secret_ref = self._safe_string(config.get("private_key_secret_ref"))
                if private_key_secret_ref:
                    guidance.credential_references.append(
                        self._build_secret_reference_item(
                            private_key_secret_ref,
                            configured=credentials_configured,
                        )
                    )
                    if not credentials_configured:
                        guidance.validation_messages.append(
                            "GitHub App private key wiring is still unavailable in the current API environment."
                        )
                else:
                    guidance.validation_messages.append(
                        "GitHub App mode requires external private key wiring outside the browser-safe metadata path."
                    )

        missing_allowlist = not allowlist
        if missing_allowlist:
            guidance.warning_flags.append("repository_allowlist_missing")
            guidance.validation_messages.append(
                "Repository allowlist is empty. Add at least one owner/repository before live GitHub pilot use."
            )

        scope_hint_mismatch = any(
            repository.lower() not in {item.lower() for item in allowlist}
            for repository in [*internal_repositories, *public_repositories]
            if allowlist
        )
        if scope_hint_mismatch:
            guidance.warning_flags.append("repository_scope_hint_mismatch")
            guidance.validation_messages.append(
                "Some internal/public repository hints are not present in the repository allowlist. Align the scope before live GitHub use."
            )

        effective_status = str(health.status)
        if effective_status == "ready" and (missing_allowlist or scope_hint_mismatch):
            effective_status = "degraded"
        guidance.effective_health_status = effective_status
        guidance.live_execution_ready = bool(
            credentials_configured
            and health.status == "ready"
            and not missing_allowlist
            and not scope_hint_mismatch
        )
        guidance.status_summary = self._github_status_summary(
            connector_mode=connector_mode,
            auth_mode=auth_mode,
            credentials_configured=credentials_configured,
            live_execution_ready=guidance.live_execution_ready,
            missing_allowlist=missing_allowlist,
            scope_hint_mismatch=scope_hint_mismatch,
            health_status=effective_status,
            credential_references=guidance.credential_references,
        )
        return guidance

    def _build_secret_reference_item(
        self,
        raw_reference: str,
        *,
        configured: bool | None,
    ) -> ToolCredentialReference:
        try:
            parsed = get_secret_resolver().parse(raw_reference, allow_bare_env=False)
        except SecretResolutionError:
            return ToolCredentialReference(
                key="private_key_reference",
                label="GitHub App private key reference",
                configured=False,
            )

        reference_type = parsed.reference_type if parsed.reference_type in {"env", "secret_ref", "vault"} else None

        return ToolCredentialReference(
            key="private_key_reference",
            label="GitHub App private key reference",
            reference_name=parsed.identifier if parsed.reference_type == "env" else None,
            reference_type=reference_type,
            configured=configured,
        )

    def _github_status_summary(
        self,
        *,
        connector_mode: str,
        auth_mode: str,
        credentials_configured: bool,
        live_execution_ready: bool,
        missing_allowlist: bool,
        scope_hint_mismatch: bool,
        health_status: str,
        credential_references: list[ToolCredentialReference],  # noqa: ARG002 - detail panel carries named references
    ) -> str:
        if connector_mode == "demo_safe_mock":
            if live_execution_ready:
                return (
                    "Demo-safe mock is active for the governed workflow, and live GitHub credentials are also ready if you later disable demo_safe_mock."
                )
            if auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
                return (
                    "Demo-safe mock is active, so the governed demo works without live GitHub credentials. Live GitHub still needs complete GitHub App wiring outside AgentGate."
                )
            return (
                "Demo-safe mock is active, so the governed demo works without live GitHub credentials. Live GitHub still needs external credential wiring and reviewed repository scope."
            )

        if live_execution_ready:
            return "Live GitHub is ready for a governed pilot within the configured repository allowlist."
        if missing_allowlist or scope_hint_mismatch:
            return "Live GitHub credentials are present, but repository scope still needs operator review before pilot use."
        if health_status == "unconfigured":
            if auth_mode == GITHUB_AUTH_MODE_GITHUB_APP:
                return "Live GitHub is not configured for this environment yet. Finish GitHub App private key wiring outside AgentGate."
            return "Live GitHub is not configured for this environment yet. Provide the required credential binding outside AgentGate."
        if credentials_configured:
            return "GitHub connector metadata is present, but validation still needs operator attention before pilot use."
        return "GitHub connector setup still needs external credential wiring and scope review before pilot use."

    def _safe_base_url_host(self, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        return parsed.hostname or None

    def _safe_base_url(self, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return None
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")

    def _safe_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [normalized for item in value if (normalized := str(item or "").strip())]

    def _safe_string(self, value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    def _allowlist_counts(self, tool_type: ToolType, config: dict) -> dict[str, int]:
        def _count(key: str) -> int:
            return len(config.get(key) or [])

        if tool_type == ToolType.GITHUB:
            return {
                "repository_allowlist": _count("repository_allowlist"),
                "internal_owners": _count("internal_owners"),
                "internal_repositories": _count("internal_repositories"),
                "public_repositories": _count("public_repositories"),
            }
        if tool_type == ToolType.JIRA:
            return {
                "project_allowlist": _count("project_allowlist"),
                "issue_type_allowlist": _count("issue_type_allowlist"),
                "transition_allowlist": _count("transition_allowlist"),
                "assignee_allowlist": _count("assignee_allowlist"),
                "external_project_keys": _count("external_project_keys"),
            }
        if tool_type == ToolType.MCP:
            return {
                "allowed_tool_names": _count("allowed_tool_names"),
                "blocked_tool_names": _count("blocked_tool_names"),
            }
        return {}

    def _warning_flags(
        self,
        *,
        tool: Tool,
        trust_domain: str | None,
        health_status: str,
        extra_flags: list[str] | None = None,
    ) -> list[str]:
        flags: list[str] = []
        if not tool.enabled:
            flags.append("disabled")
        if health_status != "ready":
            flags.append(f"health_{health_status}")
        if tool.type == ToolType.MCP and trust_domain == "external":
            flags.append("external_trust_domain")
        if tool.type == ToolType.MCP and trust_domain == "unknown":
            flags.append("unknown_trust_domain")
        if extra_flags:
            flags.extend(extra_flags)
        deduped: list[str] = []
        seen: set[str] = set()
        for flag in flags:
            if flag in seen:
                continue
            seen.add(flag)
            deduped.append(flag)
        return deduped
