"""
ChannelAdapter abstract base class.
Every platform adapter (Facebook, Instagram, WhatsApp) MUST implement this.
The Agent and Conversation Engine depend ONLY on this interface.
"""

from abc import ABC, abstractmethod
from typing import Any

from app.schemas.channel_events import InboundEvent, OutboundMessage


class ChannelAdapter(ABC):
    """
    Contract that all channel adapters must fulfill.

    Responsibilities:
    1. Convert raw platform payload → normalized InboundEvent
    2. Convert normalized OutboundMessage → platform-specific API call
    3. Handle platform-specific authentication/validation

    The Agent NEVER calls these methods directly.
    The ChannelRouter dispatches to the correct adapter.
    """

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Return the channel identifier (e.g., 'facebook', 'whatsapp')."""
        ...

    @abstractmethod
    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Convert a raw platform webhook payload into a normalized InboundEvent.

        Args:
            raw_payload: The raw JSON dict from the platform webhook

        Returns:
            Normalized InboundEvent ready for the Conversation Engine

        Raises:
            ValueError: If the payload cannot be parsed or is invalid
        """
        ...

    @abstractmethod
    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """
        Send a normalized outbound message through the platform.

        Args:
            message: Normalized OutboundMessage

        Returns:
            Platform response (e.g., sent message ID, status)

        Raises:
            Exception: If sending fails
        """
        ...

    @abstractmethod
    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """
        Reply to a comment on the platform.

        Args:
            message: OutboundMessage with reply_to_external_id set

        Returns:
            Platform response

        Raises:
            NotImplementedError: If the platform doesn't support comments
        """
        ...
