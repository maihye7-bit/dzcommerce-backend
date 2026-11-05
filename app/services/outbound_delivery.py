"""Durable outbound delivery queue with bounded, restart-safe retries."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, or_, update
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.channel_account import ChannelAccount
from app.models.conversation import Conversation
from app.models.outbound_delivery import OutboundDelivery
from app.models.store_meta_token import StoreMetaToken
from app.services.messenger_media import (
    MessengerDeliveryResult,
    send_instagram_text,
    send_messenger_image,
    send_messenger_text,
)
from app.services.meta_token_security import (
    MetaTokenEncryptionError,
    decrypt_meta_token,
)

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
CLAIM_LEASE = timedelta(minutes=2)
POLL_INTERVAL_SECONDS = 2
MAX_BACKOFF_SECONDS = 300


def enqueue_delivery(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    channel: str,
    external_account_id: str,
    recipient_external_id: str,
    payload_type: str,
    payload: dict[str, Any],
    message_id: uuid.UUID | None = None,
    fallback_for_id: uuid.UUID | None = None,
) -> OutboundDelivery:
    if channel not in {"facebook", "instagram"}:
        raise ValueError(f"Outbound delivery is not supported for channel {channel}")
    if payload_type not in {"text", "image"}:
        raise ValueError(f"Unsupported outbound payload type: {payload_type}")
    if channel == "instagram" and payload_type != "text":
        raise ValueError("Instagram image delivery is not enabled")
    delivery = OutboundDelivery(
        message_id=message_id,
        conversation_id=conversation_id,
        fallback_for_id=fallback_for_id,
        channel=channel,
        external_account_id=external_account_id,
        recipient_external_id=recipient_external_id,
        payload_type=payload_type,
        payload_json=payload,
        status="pending",
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.add(delivery)
    db.flush()
    return delivery


def _due_filter(now: datetime):
    return or_(
        and_(
            OutboundDelivery.status == "pending",
            OutboundDelivery.next_attempt_at <= now,
        ),
        and_(
            OutboundDelivery.status == "sending",
            OutboundDelivery.claimed_at <= now - CLAIM_LEASE,
        ),
    )


def _enqueue_image_failure_fallback(db: Session, delivery: OutboundDelivery) -> None:
    fallback_text = delivery.payload_json.get("fallback_text")
    if (
        delivery.payload_type != "image"
        or not isinstance(fallback_text, str)
        or not fallback_text.strip()
    ):
        return
    enqueue_delivery(
        db,
        conversation_id=delivery.conversation_id,
        channel=delivery.channel,
        external_account_id=delivery.external_account_id,
        recipient_external_id=delivery.recipient_external_id,
        payload_type="text",
        payload={"text": fallback_text},
        fallback_for_id=delivery.id,
    )


def _fail_exhausted_claims(db: Session, now: datetime) -> None:
    expired_ids = (
        db.query(OutboundDelivery.id)
        .filter(
            OutboundDelivery.status == "sending",
            OutboundDelivery.attempt_count >= MAX_ATTEMPTS,
            OutboundDelivery.claimed_at <= now - CLAIM_LEASE,
        )
        .all()
    )
    changed = False
    for (delivery_id,) in expired_ids:
        result = db.execute(
            update(OutboundDelivery)
            .where(
                OutboundDelivery.id == delivery_id,
                OutboundDelivery.status == "sending",
                OutboundDelivery.attempt_count >= MAX_ATTEMPTS,
                OutboundDelivery.claimed_at <= now - CLAIM_LEASE,
            )
            .values(
                status="failed",
                failure_kind="retry_limit",
                last_error="delivery_claim_expired",
                claimed_at=None,
            )
        )
        if result.rowcount:
            delivery = (
                db.query(OutboundDelivery)
                .filter(OutboundDelivery.id == delivery_id)
                .one()
            )
            _enqueue_image_failure_fallback(db, delivery)
            changed = True
    if changed:
        db.commit()


def _claim_delivery(db: Session) -> dict[str, Any] | None:
    now = datetime.now(timezone.utc)
    _fail_exhausted_claims(db, now)

    while True:
        candidate = (
            db.query(OutboundDelivery.id)
            .filter(_due_filter(now), OutboundDelivery.attempt_count < MAX_ATTEMPTS)
            .order_by(OutboundDelivery.created_at, OutboundDelivery.id)
            .first()
        )
        if candidate is None:
            return None

        claimable = _due_filter(now)
        result = db.execute(
            update(OutboundDelivery)
            .where(
                OutboundDelivery.id == candidate.id,
                claimable,
                OutboundDelivery.attempt_count < MAX_ATTEMPTS,
            )
            .values(
                status="sending",
                attempt_count=OutboundDelivery.attempt_count + 1,
                claimed_at=now,
            )
        )
        if result.rowcount != 1:
            db.rollback()
            continue
        db.commit()
        delivery = db.query(OutboundDelivery).filter_by(id=candidate.id).one()
        return {
            "id": delivery.id,
            "message_id": delivery.message_id,
            "conversation_id": delivery.conversation_id,
            "fallback_for_id": delivery.fallback_for_id,
            "channel": delivery.channel,
            "external_account_id": delivery.external_account_id,
            "recipient_external_id": delivery.recipient_external_id,
            "payload_type": delivery.payload_type,
            "payload_json": delivery.payload_json,
            "attempt_count": delivery.attempt_count,
        }


def resolve_meta_access_token(
    db: Session,
    *,
    store_id: uuid.UUID,
    channel: str,
    external_account_id: str,
) -> str | None:
    if channel == "facebook":
        active_account = (
            db.query(ChannelAccount.id)
            .filter(
                ChannelAccount.store_id == store_id,
                ChannelAccount.channel == channel,
                ChannelAccount.external_account_id == external_account_id,
                ChannelAccount.is_active.is_(True),
            )
            .first()
        )
        if active_account is None:
            return None

    credentials = (
        db.query(StoreMetaToken)
        .filter(StoreMetaToken.store_id == store_id)
        .one_or_none()
    )
    if credentials is None or not credentials.access_token:
        return None

    if channel == "facebook" and credentials.page_id == external_account_id:
        try:
            return decrypt_meta_token(credentials.access_token)
        except MetaTokenEncryptionError:
            logger.error(
                "meta_account_credential_unavailable store_id=%s channel=%s",
                str(store_id),
                channel,
            )
            return None
    if (
        channel == "instagram"
        and credentials.instagram_page_id == external_account_id
    ):
        try:
            return decrypt_meta_token(credentials.access_token)
        except MetaTokenEncryptionError:
            logger.error(
                "meta_account_credential_unavailable store_id=%s channel=%s",
                str(store_id),
                channel,
            )
            return None
    return None


def _resolve_access_token(db: Session, delivery: dict[str, Any]) -> str | None:
    store_id = (
        db.query(Conversation.store_id)
        .filter(Conversation.id == delivery["conversation_id"])
        .scalar()
    )
    if store_id is None:
        return None
    return resolve_meta_access_token(
        db,
        store_id=store_id,
        channel=delivery["channel"],
        external_account_id=delivery["external_account_id"],
    )


async def _send(
    delivery: dict[str, Any],
    access_token: str,
) -> MessengerDeliveryResult:
    channel = delivery["channel"]
    payload = delivery["payload_json"]
    if delivery["payload_type"] == "image":
        if channel != "facebook":
            return MessengerDeliveryResult(
                False, failure_code="unsupported_channel", retryable=False
            )
        return await send_messenger_image(
            delivery["recipient_external_id"],
            payload["url"],
            access_token,
        )
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        return MessengerDeliveryResult(
            False, failure_code="invalid_text_payload", retryable=False
        )
    if channel == "instagram":
        return await send_instagram_text(
            delivery["external_account_id"],
            delivery["recipient_external_id"],
            text,
            access_token,
        )
    return await send_messenger_text(
        delivery["recipient_external_id"],
        text,
        access_token,
    )


def _finish_delivery(
    db: Session,
    delivery_data: dict[str, Any],
    result: MessengerDeliveryResult,
) -> None:
    delivery = (
        db.query(OutboundDelivery)
        .filter(
            OutboundDelivery.id == delivery_data["id"],
            OutboundDelivery.status == "sending",
        )
        .one_or_none()
    )
    if delivery is None:
        return

    delivery.claimed_at = None
    if result.delivered:
        delivery.status = "sent"
        delivery.failure_kind = None
        delivery.last_error = None
    elif result.retryable and delivery.attempt_count < MAX_ATTEMPTS:
        delay = min(
            2 ** (delivery.attempt_count - 1),
            MAX_BACKOFF_SECONDS,
        )
        delivery.status = "pending"
        delivery.next_attempt_at = datetime.now(timezone.utc) + timedelta(
            seconds=delay
        )
        delivery.failure_kind = "transient"
        delivery.last_error = result.failure_code or "transient_delivery_error"
    else:
        delivery.status = "failed"
        delivery.failure_kind = (
            "retry_limit" if result.retryable else "permanent"
        )
        delivery.last_error = result.failure_code or "permanent_delivery_error"
        _enqueue_image_failure_fallback(db, delivery)

    logger.info(
        "outbound_delivery_finished delivery_id=%s channel=%s status=%s "
        "attempt=%d failure_kind=%s",
        str(delivery.id),
        delivery.channel,
        delivery.status,
        delivery.attempt_count,
        delivery.failure_kind or "none",
    )
    db.commit()


async def dispatch_one(db: Session) -> bool | None:
    delivery = _claim_delivery(db)
    if delivery is None:
        return None
    try:
        access_token = _resolve_access_token(db, delivery)
        if access_token is None:
            result = MessengerDeliveryResult(
                False,
                failure_code="meta_account_credential_unavailable",
                retryable=False,
            )
        else:
            result = await _send(delivery, access_token)
    except Exception as exc:
        logger.exception(
            "outbound_delivery_unexpected_error delivery_id=%s error_type=%s",
            str(delivery["id"]),
            type(exc).__name__,
        )
        result = MessengerDeliveryResult(
            False,
            failure_code=f"internal_{type(exc).__name__}",
            retryable=False,
        )
    _finish_delivery(db, delivery, result)
    return result.delivered


async def dispatch_due_deliveries(db: Session, limit: int = 10) -> int:
    delivered = 0
    for _ in range(max(limit, 0)):
        result = await dispatch_one(db)
        if result is None:
            break
        delivered += int(result)
    return delivered


async def run_delivery_worker() -> None:
    """Poll persistent pending deliveries; database claims coordinate workers."""
    while True:
        db = SessionLocal()
        try:
            processed = await dispatch_due_deliveries(db, limit=20)
        except Exception:
            logger.exception("outbound_delivery_worker_batch_failed")
            db.rollback()
            processed = 0
        finally:
            db.close()
        if processed == 0:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
