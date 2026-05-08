from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ToolType
from app.core.errors import AppError
from app.models import Tool
from app.models.base import utcnow
from app.schemas.tool import ToolSafeDetailResponse, ToolSafeSummaryResponse
from app.services.tool_health_service import ToolHealthService
from app.tools.github_adapter import ALLOWED_ACTIONS as GITHUB_ALLOWED_ACTIONS
from app.tools.github_auth import (
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
    ) -> ToolSafeSummaryResponse:
        tool = db.scalar(select(Tool).where(Tool.id == tool_id, Tool.tenant_id == tenant_id))
        if tool is None:
            raise AppError("Tool not found.", status_code=404, code="tool_not_found")
        return self._build_summary(tool=tool, probe=probe)

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
        return self._build_detail(tool=tool)

    def _build_summary(self, *, tool: Tool, probe: bool) -> ToolSafeSummaryResponse:
        health = self.tool_health_service.check(tool=tool, probe=probe)
        config = tool.config or {}
        trust_domain = str(config.get("trust_domain") or "").strip() or None

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
            health_status=health.status,
            health_can_connect=health.can_connect,
            health_probe_performed=health.probe_performed,
            health_checked_at=utcnow(),
            warning_flags=self._warning_flags(
                tool=tool,
                trust_domain=trust_domain,
                health_status=health.status,
            ),
            created_at=tool.created_at,
            updated_at=tool.updated_at,
        )

    def _build_detail(self, *, tool: Tool) -> ToolSafeDetailResponse:
        summary = self._build_summary(tool=tool, probe=False)
        config = dict(tool.config or {})
        safe_base_url = self._safe_base_url(tool.base_url)
        return ToolSafeDetailResponse(
            **summary.model_dump(),
            base_url=safe_base_url,
            documentation_path=DOCUMENTATION_PATH_BY_TYPE.get(tool.type),
            supported_auth_modes=list(SUPPORTED_AUTH_MODES_BY_TYPE.get(tool.type, [])),
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
        )

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
        return flags
