"""
MockAgentProvider: Wraps MockLLMProvider to implement AgentProvider.
Uses message objects (with .role attribute) for MockLLMProvider compatibility.
"""

import asyncio
import inspect
import uuid

from sqlalchemy.orm import Session

from app.agent.providers.agent_provider import AgentProvider
from app.agent.providers.mock_provider import MockLLMProvider


class _Message:
    """Simple message object with .role and .content attributes."""

    def __init__(self, role: str, content: str):
        self.role = role
        self.content = content


class MockAgentProvider(AgentProvider):
    def __init__(self):
        self._mock_llm = MockLLMProvider()
        self._method = self._find_llm_method()

    def _find_llm_method(self):
        """Auto-detect the callable method on MockLLMProvider."""
        candidates = [
            "generate_response",
            "complete",
            "chat",
            "generate",
            "process",
            "run",
            "invoke",
            "call",
            "respond",
        ]
        for name in candidates:
            if hasattr(self._mock_llm, name):
                method = getattr(self._mock_llm, name)
                if callable(method):
                    return method
        # Fallback: find ANY public async method
        for name in dir(self._mock_llm):
            if name.startswith("_"):
                continue
            attr = getattr(self._mock_llm, name)
            if callable(attr) and asyncio.iscoroutinefunction(attr):
                return attr
        return None

    async def process_message(
        self,
        db: Session,
        store_id: uuid.UUID,
        customer_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_message: str,
        history: list[dict],
        tools_schema: list[dict],
    ) -> dict:
        if self._method is None:
            return {
                "response": f"Mock response to: {user_message}",
                "tool_calls": [],
                "handoff": False,
                "conversation_id": str(conversation_id),
            }

        # Build messages as OBJECTS (not dicts) for MockLLMProvider compatibility
        messages = [_Message(m["role"], m["content"]) for m in history]
        messages.append(_Message("user", user_message))

        # Build kwargs based on method signature
        try:
            sig = inspect.signature(self._method)
            params = set(sig.parameters.keys())
        except (ValueError, TypeError):
            params = set()

        kwargs = {}
        if "messages" in params:
            kwargs["messages"] = messages
        if "message" in params:
            kwargs["message"] = user_message
        if "tools" in params:
            kwargs["tools"] = tools_schema
        if "context" in params:
            kwargs["context"] = {
                "db": db,
                "store_id": str(store_id),
                "customer_id": str(customer_id),
            }
        if "store_id" in params:
            kwargs["store_id"] = store_id

        try:
            if asyncio.iscoroutinefunction(self._method):
                result = await self._method(**kwargs)
            else:
                result = self._method(**kwargs)
        except TypeError:
            try:
                if asyncio.iscoroutinefunction(self._method):
                    result = await self._method(messages)
                else:
                    result = self._method(messages)
            except Exception:
                return {
                    "response": f"Mock response to: {user_message}",
                    "tool_calls": [],
                    "handoff": False,
                    "conversation_id": str(conversation_id),
                }

        # Normalize result
        if isinstance(result, dict):
            result.setdefault("conversation_id", str(conversation_id))
            result.setdefault("handoff", False)
            result.setdefault("tool_calls", [])
            result.setdefault("response", "")
            return result

        return {
            "response": str(result) if result else "",
            "tool_calls": [],
            "handoff": False,
            "conversation_id": str(conversation_id),
        }
