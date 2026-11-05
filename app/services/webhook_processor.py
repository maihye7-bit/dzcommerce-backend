"""
WebhookProcessor: The bridge between external webhooks and internal logic.
Handles verification, store resolution, and event dispatching.
"""

import json
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.channels.base import ChannelAdapter
from app.models.channel_account import ChannelAccount
from app.models.webhook_log import WebhookLog
from app.services import channel_service


def _redact_webhook_payload(value: Any, key: str = "") -> Any:
    normalized_key = key.casefold()
    if normalized_key in {
        "access_token",
        "authorization",
        "message",
        "text",
        "url",
        "token",
    } or "url" in normalized_key or normalized_key.endswith("_token"):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): _redact_webhook_payload(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_webhook_payload(item) for item in value]
    return value


async def process_webhook_event(
    db: Session,
    adapter: ChannelAdapter,
    raw_payload: dict[str, Any],
    signature_header: str | None = None,
    payload_bytes: bytes | None = None,
) -> dict:
    """
    Main entry point for all webhooks.
    1. Log the raw payload.
    2. Normalize the event using the adapter.
    3. Resolve the Store via ChannelAccount.
    4. Dispatch to ChannelService.
    """
    # 1. Log raw payload
    log_entry = WebhookLog(
        channel=adapter.channel_name,
        event_type="unknown",
        payload_json=json.dumps(
            _redact_webhook_payload(raw_payload)
        ),
    )
    db.add(log_entry)
    db.flush()

    try:
        # 2. Normalize
        event = adapter.normalize_inbound_event(raw_payload)
        log_entry.event_type = event.event_type
        log_entry.external_message_id = event.external_message_id

        # 3. Resolve Store (Find which store owns this external account)
        account_id = (
            event.metadata.get("external_account_id")
            or event.metadata.get("page_id")
            or event.metadata.get("ig_account_id")
            or event.metadata.get("phone_number")
        )

        if not account_id:
            raise HTTPException(
                status_code=400, detail="Cannot identify target account from payload"
            )

        account = (
            db.query(ChannelAccount)
            .filter(
                ChannelAccount.channel == adapter.channel_name,
                ChannelAccount.external_account_id == account_id,
                ChannelAccount.is_active == True,
            )
            .first()
        )

        if not account:
            raise HTTPException(
                status_code=404, detail="No active store found for this account"
            )

        log_entry.store_id = account.store_id

        # 4. Dispatch to Channel Service
        result = channel_service.handle_inbound_event(db, account.store_id, event)

        log_entry.is_processed = True
        db.commit()

        return result

    except Exception as e:
        log_entry.error_message = (
            f"Webhook processing failed ({type(e).__name__})."
        )
        db.commit()
        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed.",
        )
