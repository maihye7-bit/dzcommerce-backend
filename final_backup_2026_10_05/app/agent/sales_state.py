"""
SalesStateManager: Tracks the customer's journey through the buying process.
Keeps track of selected products, current draft order, and confirmation status.
This prevents the LLM from having to rediscover context from raw text every time.
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SalesState:
    """Holds the temporary state for a single conversation session."""

    selected_product_id: Optional[str] = None
    selected_quantity: int = 1
    current_draft_order_id: Optional[str] = None
    awaiting_confirmation: bool = False
    last_tool_result: Optional[dict] = None

    def reset_selection(self):
        self.selected_product_id = None
        self.selected_quantity = 1

    def reset_draft(self):
        self.current_draft_order_id = None
        self.awaiting_confirmation = False


class SalesStateManager:
    """Manages SalesState per conversation."""

    def __init__(self):
        # In a production system with multiple workers, this should use Redis.
        # For now, we use an in-memory dict keyed by conversation_id.
        self._states: dict[str, SalesState] = {}

    def get_state(self, conversation_id: str) -> SalesState:
        if conversation_id not in self._states:
            self._states[conversation_id] = SalesState()
        return self._states[conversation_id]

    def clear_state(self, conversation_id: str):
        if conversation_id in self._states:
            del self._states[conversation_id]


# Global instance for the agent
sales_manager = SalesStateManager()
