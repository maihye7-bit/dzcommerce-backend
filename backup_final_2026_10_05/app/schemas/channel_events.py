"""
Normalized event schemas for channel-agnostic communication.
These are the ONLY structures the Conversation Engine sees.
The Agent never deals with platform-specific payloads.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class InboundEvent(BaseModel):
    """
    Normalized representation of ANY incoming social event.
    Whether it's a WhatsApp message, Facebook comment, or Instagram DM,
    it arrives here in this exact shape.
    """

    channel: str  # "facebook", "instagram", "whatsapp"
    event_type: str  # "message_received", "comment_created"
    external_message_id: str  # Platform's unique message/comment ID
    external_conversation_id: str  # Platform's conversation/thread ID
    external_user_id: str  # Platform's user/sender ID
    customer_name: Optional[str] = None  # Display name from platform
    message_text: str  # The actual text content (Unicode safe)
    metadata: dict[str, Any] = Field(default_factory=dict)  # Platform-specific extras
    received_at: datetime = Field(default_factory=datetime.utcnow)


class OutboundMessage(BaseModel):
    """
    Normalized representation of ANY outgoing response.
    The Agent produces this; the adapter converts it to platform format.
    """

    channel: str  # Target channel
    recipient_external_id: str  # Platform's user/conversation ID
    text: str  # Response text (Unicode safe)
    reply_to_external_id: Optional[str] = None  # For comment replies
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChannelIdentityCreate(BaseModel):
    """Schema for creating/linking a channel identity to a customer."""

    store_id: uuid.UUID
    customer_id: uuid.UUID
    channel: str
    external_user_id: str
    external_username: Optional[str] = None
