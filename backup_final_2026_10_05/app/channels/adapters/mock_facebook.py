"""
Mock Facebook Adapter for testing.
Supports Messenger messages and Facebook comments.
Does NOT make real API calls.
"""

import uuid
from typing import Any

from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class MockFacebookAdapter(ChannelAdapter):
    """
    Test-only Facebook adapter.
    Simulates Messenger messages and post/page comments.
    """

    @property
    def channel_name(self) -> str:
        return "facebook"

    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Normalize a simulated Facebook webhook payload.

        Expected raw_payload keys:
          - event_type: "message_received" | "comment_created"
          - external_message_id: str
          - external_conversation_id: str
          - external_user_id: str
          - customer_name: str (optional)
          - message_text: str
        """
        event_type = raw_payload.get("event_type", "message_received")
        if event_type not in ("message_received", "comment_created"):
            raise ValueError(f"Unsupported Facebook event type: {event_type}")

        message_text = raw_payload.get("message_text", "")
        if not message_text:
            raise ValueError("Facebook event missing message_text")

        return InboundEvent(
            channel=self.channel_name,
            event_type=event_type,
            external_message_id=raw_payload["external_message_id"],
            external_conversation_id=raw_payload["external_conversation_id"],
            external_user_id=raw_payload["external_user_id"],
            customer_name=raw_payload.get("customer_name"),
            message_text=message_text,
            metadata={
                "post_id": raw_payload.get("post_id"),
                "parent_comment_id": raw_payload.get("parent_comment_id"),
            },
        )

    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """Simulate sending a Messenger message."""
        return {
            "status": "sent",
            "channel": self.channel_name,
            "recipient": message.recipient_external_id,
            "mock_message_id": str(uuid.uuid4()),
        }

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """Simulate replying to a Facebook comment."""
        if not message.reply_to_external_id:
            raise ValueError("reply_to_external_id is required for comment replies")
        return {
            "status": "sent",
            "channel": self.channel_name,
            "reply_to": message.reply_to_external_id,
            "mock_comment_id": str(uuid.uuid4()),
        }
