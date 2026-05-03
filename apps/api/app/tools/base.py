from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class ToolExecutionRequest:
    tool_name: str
    action_name: str
    arguments: dict
    tool_type: str | None = None
    base_url: str | None = None
    config: dict = field(default_factory=dict)


class ToolExecutionAdapter(ABC):
    adapter_name = "base"

    @abstractmethod
    def supports(self, request: ToolExecutionRequest) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(self, request: ToolExecutionRequest) -> dict:
        raise NotImplementedError
