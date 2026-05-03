from __future__ import annotations

from app.tools.base import ToolExecutionRequest
from app.tools.registry import ToolAdapterRegistry


class ToolExecutor:
    def __init__(self, registry: ToolAdapterRegistry | None = None) -> None:
        self.registry = registry or ToolAdapterRegistry()

    def supports(
        self,
        tool_name: str,
        action_name: str,
        arguments: dict,
        *,
        tool_type: str | None = None,
        base_url: str | None = None,
        config: dict | None = None,
    ) -> bool:
        return self.registry.supports(
            ToolExecutionRequest(
                tool_name=tool_name,
                action_name=action_name,
                arguments=arguments,
                tool_type=tool_type,
                base_url=base_url,
                config=config or {},
            )
        )

    def execute(
        self,
        tool_name: str,
        action_name: str,
        arguments: dict,
        *,
        tool_type: str | None = None,
        base_url: str | None = None,
        config: dict | None = None,
    ) -> dict:
        return self.registry.execute(
            ToolExecutionRequest(
                tool_name=tool_name,
                action_name=action_name,
                arguments=arguments,
                tool_type=tool_type,
                base_url=base_url,
                config=config or {},
            )
        )


MockToolExecutor = ToolExecutor
