"""
Mock WhatsApp Adapter for testing.
Supports messages only (no comments).
Does NOT make real API calls.
"""

import uuid
from typing import Any

from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class MockWhatsAppAdapter(ChannelAdapter):
    """
    Test-only WhatsApp adapter.
    Simulates WhatsApp Cloud API message events.
    Comments are not supported on WhatsApp.
    """

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Normalize a simulated WhatsApp webhook payload.

        Expected raw_payload keys:
          - external_message_id: str
          - external_conversation_id: str (phone number or wa_id)
          - external_user_id: str (sender phone/wa_id)
          - customer_name: str (optional)
          - message_text: str
        """
        message_text = raw_payload.get("message_text", "")
        if not message_text:
            raise ValueError("WhatsApp event missing message_text")

        return InboundEvent(
            channel=self.channel_name,
            event_type="message_received",
            external_message_id=raw_payload["external_message_id"],
            external_conversation_id=raw_payload["external_conversation_id"],
            external_user_id=raw_payload["external_user_id"],
            customer_name=raw_payload.get("customer_name"),
            message_text=message_text,
            metadata={
                "phone_number": raw_payload.get("phone_number"),
            },
        )

    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """Simulate sending a WhatsApp message."""
        return {
            "status": "sent",
            "channel": self.channel_name,
            "recipient": message.recipient_external_id,
            "mock_message_id": str(uuid.uuid4()),
        }

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """WhatsApp does not support comments."""
        raise NotImplementedError("WhatsApp does not support comment replies")
