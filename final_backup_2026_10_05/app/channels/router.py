"""
ChannelRouter: Dispatches events to the correct adapter.
Simple registry pattern - no magic, no framework dependencies.
"""

from typing import Any

from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class ChannelRouter:
    """
    Routes inbound events to the correct ChannelAdapter
    and sends outbound messages through the correct adapter.

    Usage:
        router = ChannelRouter()
        router.register(FacebookAdapter())
        router.register(WhatsAppAdapter())

        event = router.normalize("facebook", raw_webhook_payload)
        await router.send(outbound_message)
    """

    def __init__(self):
        self._adapters: dict[str, ChannelAdapter] = {}

    def register(self, adapter: ChannelAdapter) -> None:
        """Register a channel adapter by its channel_name."""
        name = adapter.channel_name
        if name in self._adapters:
            raise ValueError(f"Adapter for channel '{name}' already registered")
        self._adapters[name] = adapter

    def get_adapter(self, channel: str) -> ChannelAdapter:
        """Get the adapter for a specific channel."""
        adapter = self._adapters.get(channel)
        if adapter is None:
            raise ValueError(
                f"No adapter registered for channel '{channel}'. "
                f"Available: {list(self._adapters.keys())}"
            )
        return adapter

    def normalize(self, channel: str, raw_payload: dict[str, Any]) -> InboundEvent:
        """Normalize a raw platform payload into an InboundEvent."""
        adapter = self.get_adapter(channel)
        return adapter.normalize_inbound_event(raw_payload)

    async def send(self, message: OutboundMessage) -> dict[str, Any]:
        """Send an outbound message through the correct adapter."""
        adapter = self.get_adapter(message.channel)
        return await adapter.send_message(message)

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """Reply to a comment through the correct adapter."""
        adapter = self.get_adapter(message.channel)
        return await adapter.reply_to_comment(message)

    @property
    def registered_channels(self) -> list[str]:
        """List all registered channel names."""
        return list(self._adapters.keys())
