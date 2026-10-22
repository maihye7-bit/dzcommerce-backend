"""
Phase 6 Part 2 - Channel Abstraction Layer
Run: python setup_phase6_part2.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 6 Part 2: Abstraction Layer ===\n")

# ============================================================
# 1. INBOUND EVENT SCHEMA
# ============================================================
write_file("app/schemas/channel_events.py", '''"""
Normalized event schemas for channel-agnostic communication.
These are the ONLY structures the Conversation Engine sees.
The Agent never deals with platform-specific payloads.
"""
import uuid
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field


class InboundEvent(BaseModel):
    """
    Normalized representation of ANY incoming social event.
    Whether it's a WhatsApp message, Facebook comment, or Instagram DM,
    it arrives here in this exact shape.
    """
    channel: str                          # "facebook", "instagram", "whatsapp"
    event_type: str                       # "message_received", "comment_created"
    external_message_id: str              # Platform's unique message/comment ID
    external_conversation_id: str         # Platform's conversation/thread ID
    external_user_id: str                 # Platform's user/sender ID
    customer_name: Optional[str] = None   # Display name from platform
    message_text: str                     # The actual text content (Unicode safe)
    metadata: dict[str, Any] = Field(default_factory=dict)  # Platform-specific extras
    received_at: datetime = Field(default_factory=datetime.utcnow)


class OutboundMessage(BaseModel):
    """
    Normalized representation of ANY outgoing response.
    The Agent produces this; the adapter converts it to platform format.
    """
    channel: str                          # Target channel
    recipient_external_id: str            # Platform's user/conversation ID
    text: str                             # Response text (Unicode safe)
    reply_to_external_id: Optional[str] = None  # For comment replies
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelIdentityCreate(BaseModel):
    """Schema for creating/linking a channel identity to a customer."""
    store_id: uuid.UUID
    customer_id: uuid.UUID
    channel: str
    external_user_id: str
    external_username: Optional[str] = None
''')

# ============================================================
# 2. CHANNEL ADAPTER INTERFACE
# ============================================================
write_file("app/channels/base.py", '''"""
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
''')

# ============================================================
# 3. CHANNEL ROUTER
# ============================================================
write_file("app/channels/router.py", '''"""
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
''')

# ============================================================
# 4. CREATE channels __init__.py
# ============================================================
write_file("app/channels/__init__.py", '''"""
Channel abstraction layer for social commerce.
This package contains the channel-agnostic interfaces and router.
Platform-specific adapters live in app.channels.adapters.*
"""
from app.channels.base import ChannelAdapter
from app.channels.router import ChannelRouter

__all__ = ["ChannelAdapter", "ChannelRouter"]
''')

print("\n=== Part 2 Complete ===")
print("Created:")
print("  - app/schemas/channel_events.py (InboundEvent, OutboundMessage)")
print("  - app/channels/base.py (ChannelAdapter ABC)")
print("  - app/channels/router.py (ChannelRouter)")
print("  - app/channels/__init__.py")
print("\nNext: Run tests to verify no regressions")
