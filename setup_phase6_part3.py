"""
Phase 6 Part 3 - Mock Channel Adapters
Run: python setup_phase6_part3.py
"""
import os

def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 6 Part 3: Mock Adapters ===\n")

# ============================================================
# 1. MOCK FACEBOOK ADAPTER
# ============================================================
write_file("app/channels/adapters/__init__.py", '''"""
Channel adapter implementations.
Currently mock/test adapters. Real adapters will be added in future phases.
"""
from app.channels.adapters.mock_facebook import MockFacebookAdapter
from app.channels.adapters.mock_instagram import MockInstagramAdapter
from app.channels.adapters.mock_whatsapp import MockWhatsAppAdapter

__all__ = [
    "MockFacebookAdapter",
    "MockInstagramAdapter",
    "MockWhatsAppAdapter",
]
''')

write_file("app/channels/adapters/mock_facebook.py", '''"""
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
''')

# ============================================================
# 2. MOCK INSTAGRAM ADAPTER
# ============================================================
write_file("app/channels/adapters/mock_instagram.py", '''"""
Mock Instagram Adapter for testing.
Supports DMs and Instagram comments.
Does NOT make real API calls.
"""
import uuid
from typing import Any

from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class MockInstagramAdapter(ChannelAdapter):
    """
    Test-only Instagram adapter.
    Simulates Direct Messages and post/reel comments.
    """

    @property
    def channel_name(self) -> str:
        return "instagram"

    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Normalize a simulated Instagram webhook payload.
        
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
            raise ValueError(f"Unsupported Instagram event type: {event_type}")

        message_text = raw_payload.get("message_text", "")
        if not message_text:
            raise ValueError("Instagram event missing message_text")

        return InboundEvent(
            channel=self.channel_name,
            event_type=event_type,
            external_message_id=raw_payload["external_message_id"],
            external_conversation_id=raw_payload["external_conversation_id"],
            external_user_id=raw_payload["external_user_id"],
            customer_name=raw_payload.get("customer_name"),
            message_text=message_text,
            metadata={
                "media_id": raw_payload.get("media_id"),
                "parent_comment_id": raw_payload.get("parent_comment_id"),
            },
        )

    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """Simulate sending an Instagram DM."""
        return {
            "status": "sent",
            "channel": self.channel_name,
            "recipient": message.recipient_external_id,
            "mock_message_id": str(uuid.uuid4()),
        }

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """Simulate replying to an Instagram comment."""
        if not message.reply_to_external_id:
            raise ValueError("reply_to_external_id is required for comment replies")
        return {
            "status": "sent",
            "channel": self.channel_name,
            "reply_to": message.reply_to_external_id,
            "mock_comment_id": str(uuid.uuid4()),
        }
''')

# ============================================================
# 3. MOCK WHATSAPP ADAPTER
# ============================================================
write_file("app/channels/adapters/mock_whatsapp.py", '''"""
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
''')

print("\n=== Part 3 Complete ===")
print("Created:")
print("  - app/channels/adapters/__init__.py")
print("  - app/channels/adapters/mock_facebook.py")
print("  - app/channels/adapters/mock_instagram.py")
print("  - app/channels/adapters/mock_whatsapp.py")
print("\nNext: Run tests to verify no regressions")
