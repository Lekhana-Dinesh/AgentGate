from __future__ import annotations

from app.core.enums import ToolType
from app.schemas.tool import ToolHealthResponse
from app.tools.github_adapter import GitHubToolAdapter


class ToolHealthService:
    def __init__(self, github_adapter: GitHubToolAdapter | None = None) -> None:
        self.github_adapter = github_adapter or GitHubToolAdapter()

    def check(self, *, tool, probe: bool = False) -> ToolHealthResponse:
        if tool.type != ToolType.GITHUB:
            return ToolHealthResponse(
                tool_id=tool.id,
                tool_name=tool.name,
                tool_type=tool.type,
                status="unsupported",
                adapter=tool.type.value,
                details={"message": "Health checks are only implemented for GitHub tools in this build."},
            )

        result = self.github_adapter.health_check(
            base_url=tool.base_url,
            config=tool.config or {},
            probe=probe,
        )
        details = dict(result.get("details") or {})
        details["token_env_var"] = result.get("token_env_var")
        details["secret_reference"] = result.get("secret_reference")
        details["repository_allowlist_count"] = result.get("repository_allowlist_count")
        return ToolHealthResponse(
            tool_id=tool.id,
            tool_name=tool.name,
            tool_type=tool.type,
            status=result["status"],
            adapter=result["adapter"],
            auth_provider=result.get("auth_provider"),
            token_present=result.get("token_present"),
            probe_performed=result.get("probe_performed", False),
            can_connect=result.get("can_connect"),
            details=details,
        )
