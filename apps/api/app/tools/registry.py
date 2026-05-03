from __future__ import annotations

from app.core.errors import AppError
from app.tools.base import ToolExecutionAdapter, ToolExecutionRequest
from app.tools.github_adapter import GitHubToolAdapter
from app.tools.mock_adapter import MockToolAdapter


class ToolAdapterRegistry:
    def __init__(self, adapters: list[ToolExecutionAdapter] | None = None) -> None:
        self.adapters = adapters or [MockToolAdapter(), GitHubToolAdapter()]

    def supports(self, request: ToolExecutionRequest) -> bool:
        return any(adapter.supports(request) for adapter in self.adapters)

    def execute(self, request: ToolExecutionRequest) -> dict:
        for adapter in self.adapters:
            if adapter.supports(request):
                return adapter.execute(request)
        raise AppError(
            f"No registered adapter can execute {request.tool_name}.{request.action_name}.",
            status_code=400,
            code="tool_adapter_not_supported",
        )
