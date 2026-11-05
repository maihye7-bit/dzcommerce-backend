"""
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
                metadata={
                    "raw_type": "dm",
                    "external_account_id": str(entry.get("id") or ""),
                },
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
        self.require_account_credentials(ig_account_id)

        payload = {
            "recipient": {"id": message.recipient_external_id},
            "message": {"text": message.text},
        }
        return await self._post(f"{ig_account_id}/messages", payload)

    async def reply_to_comment(self, message: OutboundMessage) -> dict[str, Any]:
        """Reply to an Instagram comment."""
        if not message.reply_to_external_id:
            raise ValueError("reply_to_external_id required for comment reply")
        ig_account_id = message.metadata.get("ig_account_id", "")
        if not ig_account_id:
            raise ValueError(
                "metadata.ig_account_id is required for Instagram comment reply"
            )
        self.require_account_credentials(ig_account_id)

        payload = {"message": message.text}
        return await self._post(f"{message.reply_to_external_id}/replies", payload)
