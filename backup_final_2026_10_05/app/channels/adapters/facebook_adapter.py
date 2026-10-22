"""
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
