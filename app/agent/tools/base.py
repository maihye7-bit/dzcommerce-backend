import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None


class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(
        self,
        store_id: uuid.UUID,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> ToolResult: ...

    def validate_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return arguments
