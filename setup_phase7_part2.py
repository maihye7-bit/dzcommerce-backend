"""
Phase 7 Part 2 - Real Channel Adapters
Run: python setup_phase7_part2.py
"""
import os

def write_file(path, content):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  Created: {path}")

print("\n=== Phase 7 Part 2: Real Channel Adapters ===\n")

# ============================================================
# 1. BASE REAL ADAPTER
# ============================================================
write_file("app/channels/adapters/base_real.py", '''"""
Base class for real platform adapters.
Provides shared HTTP client, token management, and error handling.
"""
import os
from typing import Optional

import httpx


class BaseRealAdapter:
    """Shared infrastructure for all real Meta/WhatsApp adapters."""

    GRAPH_API_VERSION = "v25.0"
    GRAPH_API_BASE = "https://graph.facebook.com"

    def __init__(self, access_token: Optional[str] = None):
        self._access_token = access_token or os.environ.get("META_ACCESS_TOKEN", "")
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def graph_url(self) -> str:
        return f"{self.GRAPH_API_BASE}/{self.GRAPH_API_VERSION}"

    async def _post(self, endpoint: str, json_data: dict) -> dict:
        """Make authenticated POST request to Graph API."""
        url = f"{self.graph_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = await self._client.post(url, json=json_data, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """Make authenticated GET request to Graph API."""
        url = f"{self.graph_url}/{endpoint}"
        headers = {"Authorization": f"Bearer {self._access_token}"}
        resp = await self._client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.aclose()
''')

# ============================================================
# 2. FACEBOOK ADAPTER (REAL)
# ============================================================
write_file("app/channels/adapters/facebook_adapter.py", '''"""
Real Facebook Adapter using Meta Graph API v25.0.
Supports Messenger messages and Page comment replies.
Reference: https://developers.facebook.com/docs/messenger-platform/send-messages
"""
import uuid
from typing import Any

from app.channels.adapters.base_real import BaseRealAdapter
from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class FacebookAdapter(BaseRealAdapter, ChannelAdapter):
    """Real Facebook Messenger + Comments adapter."""

    @property
    def channel_name(self) -> str:
        return "facebook"

    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Normalize Facebook webhook payload.
        
        Supports two formats:
        1. Messenger message: entry[0].messaging[0].message
        2. Comment event: entry[0].changes[0].value (comment creation)
        """
        entry = raw_payload.get("entry", [{}])[0]

        # --- Messenger Message ---
        messaging = entry.get("messaging", [])
        if messaging:
            msg_event = messaging[0]
            message_data = msg_event.get("message", {})
            sender_id = msg_event.get("sender", {}).get("id", "")
            text = message_data.get("text", "")

            return InboundEvent(
                channel=self.channel_name,
                event_type="message_received",
                external_message_id=message_data.get("mid", str(uuid.uuid4())),
                external_conversation_id=sender_id,
                external_user_id=sender_id,
                message_text=text,
                metadata={"raw_type": "messenger"},
            )

        # --- Comment Event ---
        changes = entry.get("changes", [])
        if changes:
            change_value = changes[0].get("value", {})
            comment_text = change_value.get("message", "")
            comment_id = change_value.get("id", str(uuid.uuid4()))
            from_user = change_value.get("from", {})
            post_id = change_value.get("post_id", "")

            return InboundEvent(
                channel=self.channel_name,
                event_type="comment_created",
                external_message_id=comment_id,
                external_conversation_id=post_id,
                external_user_id=from_user.get("id", ""),
                customer_name=from_user.get("name"),
                message_text=comment_text,
                metadata={
                    "raw_type": "comment",
                    "post_id": post_id,
                    "parent_comment_id": change_value.get("parent_id"),
                },
            )

        raise ValueError("Unrecognized Facebook webhook payload format")

    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """Send a Messenger message via Send API."""
        page_id = message.metadata.get("page_id", "")
        if not page_id:
            raise ValueError("metadata.page_id is required for Facebook send")

        payload = {
            "recipient": {"id": message.recipient_external_id},
            "message": {"text": message.text},
        }
        return await self._post(f"{page_id}/messages", payload)

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """Reply to a Facebook comment."""
        if not message.reply_to_external_id:
            raise ValueError("reply_to_external_id required for comment reply")

        payload = {"message": message.text}
        return await self._post(f"{message.reply_to_external_id}/comments", payload)
''')

# ============================================================
# 3. INSTAGRAM ADAPTER (REAL)
# ============================================================
write_file("app/channels/adapters/instagram_adapter.py", '''"""
Real Instagram Adapter using Instagram Graph API.
Supports Direct Messages and Comment replies.
Reference: https://developers.facebook.com/docs/instagram-platform/messaging
"""
import uuid
from typing import Any

from app.channels.adapters.base_real import BaseRealAdapter
from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class InstagramAdapter(BaseRealAdapter, ChannelAdapter):
    """Real Instagram DM + Comments adapter."""

    @property
    def channel_name(self) -> str:
        return "instagram"

    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Normalize Instagram webhook payload.
        
        Supports:
        1. DM: entry[0].messaging[0].message
        2. Comment: entry[0].changes[0].value (comment event)
        """
        entry = raw_payload.get("entry", [{}])[0]

        # --- Instagram DM ---
        messaging = entry.get("messaging", [])
        if messaging:
            msg_event = messaging[0]
            message_data = msg_event.get("message", {})
            sender_id = msg_event.get("sender", {}).get("id", "")
            text = message_data.get("text", "")

            return InboundEvent(
                channel=self.channel_name,
                event_type="message_received",
                external_message_id=message_data.get("mid", str(uuid.uuid4())),
                external_conversation_id=sender_id,
                external_user_id=sender_id,
                message_text=text,
                metadata={"raw_type": "dm"},
            )

        # --- Comment Event ---
        changes = entry.get("changes", [])
        if changes:
            change_value = changes[0].get("value", {})
            comment_text = change_value.get("text", "")
            comment_id = change_value.get("id", str(uuid.uuid4()))
            user_id = change_value.get("user_id", "")
            media_id = change_value.get("media_id", "")

            return InboundEvent(
                channel=self.channel_name,
                event_type="comment_created",
                external_message_id=comment_id,
                external_conversation_id=media_id,
                external_user_id=user_id,
                message_text=comment_text,
                metadata={
                    "raw_type": "comment",
                    "media_id": media_id,
                    "parent_comment_id": change_value.get("parent_id"),
                },
            )

        raise ValueError("Unrecognized Instagram webhook payload format")

    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """Send an Instagram DM via Conversations API."""
        ig_account_id = message.metadata.get("ig_account_id", "")
        if not ig_account_id:
            raise ValueError("metadata.ig_account_id required for Instagram send")

        payload = {
            "recipient": {"id": message.recipient_external_id},
            "message": {"text": message.text},
        }
        return await self._post(f"{ig_account_id}/messages", payload)

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """Reply to an Instagram comment."""
        if not message.reply_to_external_id:
            raise ValueError("reply_to_external_id required for comment reply")

        payload = {"message": message.text}
        return await self._post(f"{message.reply_to_external_id}/replies", payload)
''')

# ============================================================
# 4. WHATSAPP ADAPTER (REAL)
# ============================================================
write_file("app/channels/adapters/whatsapp_adapter.py", '''"""
Real WhatsApp Adapter using WhatsApp Cloud API.
Supports text messages only (no media in this phase).
Reference: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/send-messages
"""
import os
import uuid
from typing import Any

import httpx

from app.channels.base import ChannelAdapter
from app.schemas.channel_events import InboundEvent, OutboundMessage


class WhatsAppAdapter(ChannelAdapter):
    """Real WhatsApp Cloud API adapter."""

    API_VERSION = "v25.0"
    API_BASE = "https://graph.facebook.com"

    def __init__(self):
        self._access_token = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
        self._phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
        self._client = httpx.AsyncClient(timeout=30.0)

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    def normalize_inbound_event(self, raw_payload: dict[str, Any]) -> InboundEvent:
        """
        Normalize WhatsApp Cloud API webhook payload.
        
        Structure: entry[0].changes[0].value.messages[0]
        """
        try:
            entry = raw_payload["entry"][0]
            change_value = entry["changes"][0]["value"]
            messages = change_value.get("messages", [])

            if not messages:
                raise ValueError("No messages in WhatsApp webhook payload")

            msg = messages[0]
            contacts = change_value.get("contacts", [{}])
            contact = contacts[0] if contacts else {}

            # Only text messages supported in this phase
            if msg.get("type") != "text":
                raise ValueError(f"Unsupported WhatsApp message type: {msg.get('type')}")

            text = msg.get("text", {}).get("body", "")
            wa_id = msg.get("from", "")
            msg_id = msg.get("id", str(uuid.uuid4()))

            return InboundEvent(
                channel=self.channel_name,
                event_type="message_received",
                external_message_id=msg_id,
                external_conversation_id=wa_id,
                external_user_id=wa_id,
                customer_name=contact.get("profile", {}).get("name"),
                message_text=text,
                metadata={
                    "raw_type": "text",
                    "phone_number": wa_id,
                },
            )
        except (KeyError, IndexError) as e:
            raise ValueError(f"Invalid WhatsApp webhook payload: {e}")

    async def send_message(self, message: OutboundMessage) -> dict[str, Any]:
        """Send a text message via WhatsApp Cloud API."""
        phone_number_id = message.metadata.get(
            "phone_number_id", self._phone_number_id
        )
        if not phone_number_id:
            raise ValueError("phone_number_id required for WhatsApp send")

        url = f"{self.API_BASE}/{self.API_VERSION}/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": message.recipient_external_id,
            "type": "text",
            "text": {"body": message.text},
        }
        resp = await self._client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """WhatsApp does not support comments."""
        raise NotImplementedError("WhatsApp does not support comment replies")

    async def close(self):
        await self._client.aclose()
''')

# ============================================================
# 5. UPDATE adapters/__init__.py
# ============================================================
write_file("app/channels/adapters/__init__.py", '''"""
Channel adapter implementations.
Mock adapters for testing, real adapters for production.
"""
# Mock adapters (testing)
from app.channels.adapters.mock_facebook import MockFacebookAdapter
from app.channels.adapters.mock_instagram import MockInstagramAdapter
from app.channels.adapters.mock_whatsapp import MockWhatsAppAdapter

# Real adapters (production)
from app.channels.adapters.facebook_adapter import FacebookAdapter
from app.channels.adapters.instagram_adapter import InstagramAdapter
from app.channels.adapters.whatsapp_adapter import WhatsAppAdapter

__all__ = [
    # Mock
    "MockFacebookAdapter",
    "MockInstagramAdapter",
    "MockWhatsAppAdapter",
    # Real
    "FacebookAdapter",
    "InstagramAdapter",
    "WhatsAppAdapter",
]
''')

print("\n=== Part 2 Complete ===")
print("Created:")
print("  - app/channels/adapters/base_real.py")
print("  - app/channels/adapters/facebook_adapter.py")
print("  - app/channels/adapters/instagram_adapter.py")
print("  - app/channels/adapters/whatsapp_adapter.py")
print("  - Updated app/channels/adapters/__init__.py")
print("\nNext: Run tests to verify no regressions")
