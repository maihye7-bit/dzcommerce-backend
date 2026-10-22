"""
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
                raise ValueError(
                    f"Unsupported WhatsApp message type: {msg.get('type')}"
                )

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
        phone_number_id = message.metadata.get("phone_number_id", self._phone_number_id)
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
