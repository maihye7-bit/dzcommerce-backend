from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMMessage:
    role: str
    content: str | None = None
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict] | None = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        system_prompt: str | None = None,
        session_id: str | None = None,
    ) -> LLMResponse: ...
