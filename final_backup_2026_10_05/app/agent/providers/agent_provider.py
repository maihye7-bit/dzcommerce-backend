"""
AgentProvider: Abstract base class for Agent Orchestration.
Allows swapping between Mock, Qwen-Agent, OpenAI, etc.
"""

import uuid
from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.orm import Session


class AgentProvider(ABC):

    @abstractmethod
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
        """
        Process a message and return response + tool calls.
        Must NOT execute tools directly; returns decision to caller.
        """
        pass
