"""
Webhook endpoints - Integrated with ConversationEngine & Tool Registry.
Phase 12-D + Idempotency Fix: Robust duplicate webhook handling.
CRITICAL: Implements safe INSERT-or-SKIP logic for incoming messages.
"""
import json
import logging
import uuid

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.config import AGENT_PROVIDER, FACEBOOK_PAGE_ACCESS_TOKEN
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.customer import Customer
from app.models.store import Store
from app.models.channel_account import ChannelAccount
from app.services.webhook_security import (
    verify_meta_signature,
    verify_meta_verify_token,
    verify_whatsapp_verify_token,
)
# Imports for Phase 12-D Integration
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.mock_provider import MockLLMProvider
from app.agent.providers.qwen_provider import QwenLLMProvider
from app.agent.tools import tool_registry

router = APIRouter(prefix="/webhooks", tags=["social-webhooks"])
logger = logging.getLogger(__name__)


class InboundMessagePersistenceError(Exception):
    """An inbound insert failed for a reason other than its scoped duplicate."""


def _build_llm_provider():
    if AGENT_PROVIDER == "qwen":
        return QwenLLMProvider()
    return MockLLMProvider()


async def _send_facebook_comment_reply(comment_id: str, text: str) -> httpx.Response:
    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN is not configured")

    url = f"https://graph.facebook.com/v26.0/{comment_id}/comments"
    payload = {"message": text}
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(
            url,
            params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
            json=payload,
        )


async def _send_instagram_comment_reply(comment_id: str, text: str) -> httpx.Response:
    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN is not configured")

    url = f"https://graph.facebook.com/v26.0/{comment_id}/replies"
    payload = {"message": text}
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(
            url,
            params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
            json=payload,
        )


# Initialize Components Once at Module Load Time
_llm_provider = _build_llm_provider()
_engine = ConversationEngine(llm_provider=_llm_provider, tool_registry=tool_registry)


async def _send_facebook_message(recipient_id: str, text: str) -> httpx.Response:
    """Send a Messenger reply using the configured Facebook Page access token."""
    if not FACEBOOK_PAGE_ACCESS_TOKEN:
        raise RuntimeError("FACEBOOK_PAGE_ACCESS_TOKEN is not configured")

    url = "https://graph.facebook.com/v26.0/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(
            url,
            params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
            json=payload,
        )


def _persist_inbound_message(
    db: Session,
    conversation_id: uuid.UUID,
    store_id: uuid.UUID,
    channel: str,
    sender_id: str,
    text: str,
    external_message_id: str | None,
) -> bool:
    """Stage an inbound event; return False only for its scoped duplicate."""
    db.add(
        Message(
            conversation_id=conversation_id,
            role=MessageRole.CUSTOMER,
            content=text,
            external_message_id=external_message_id,
        )
    )
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if external_message_id is None:
            raise InboundMessagePersistenceError from exc

        existing_message = (
            db.query(Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(Customer, Conversation.customer_id == Customer.id)
            .filter(
                Message.external_message_id == external_message_id,
                Conversation.store_id == store_id,
                Conversation.channel == channel,
                Customer.phone == sender_id,
            )
            .first()
        )
        db.rollback()
        if existing_message:
            return False
        raise InboundMessagePersistenceError from exc
    return True


@router.post("/meta")
async def meta_webhook(request: Request, db: Session = Depends(get_db)):
    body_bytes = await request.body()
    try:
        signature_valid = verify_meta_signature(
            body_bytes,
            request.headers.get("X-Hub-Signature-256"),
        )
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Meta webhook signature verification is not configured",
        )
    if not signature_valid:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    logger.debug("SIGNATURE_OK path=%s", request.url.path)

    try:
        payload = json.loads(body_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid Meta webhook payload")
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="Invalid Meta webhook payload")
    logger.debug(
        "PARSED object=%s entries=%d",
        payload.get("object"),
        len(entries),
    )

    platform_object = payload.get("object")
    if platform_object not in (None, "page", "instagram") and any(
        isinstance(entry, dict) and entry.get("messaging") for entry in entries
    ):
        raise HTTPException(status_code=400, detail="Unsupported Meta webhook object")

    if platform_object not in (None, "page", "instagram"):
        return {"status": "processed", "count": 0, "skipped": 0}

    channel = "instagram" if platform_object == "instagram" else "facebook"
    mapped_entries = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if not entry.get("messaging") and not entry.get("changes"):
            continue
        account_id = entry.get("id")
        if not account_id:
            raise HTTPException(
                status_code=400,
                detail="Meta account ID is missing from webhook entry",
            )
        store_ids = (
            db.query(ChannelAccount.store_id)
            .join(Store, Store.id == ChannelAccount.store_id)
            .filter(
                ChannelAccount.channel == channel,
                ChannelAccount.external_account_id == str(account_id),
                ChannelAccount.is_active.is_(True),
                Store.is_active.is_(True),
            )
            .all()
        )
        if not store_ids:
            raise HTTPException(
                status_code=404,
                detail="No active store is connected to this Meta account",
            )
        if len(store_ids) > 1:
            raise HTTPException(
                status_code=409,
                detail="Meta account is connected to multiple stores",
            )
        mapped_entries.append((entry, store_ids[0][0]))

    processed_count = 0
    skipped_duplicates = 0

    for entry, store_id in mapped_entries:
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            if value.get("item") not in ("comment", None):
                continue
            comment_id = value.get("comment_id") or value.get("id")
            if not comment_id:
                continue
            reply_text = "شكرًا على تعليقك. سنرد عليك قريبًا من متجرنا."
            try:
                if channel == "facebook":
                    await _send_facebook_comment_reply(str(comment_id), reply_text)
                else:
                    await _send_instagram_comment_reply(str(comment_id), reply_text)
                processed_count += 1
                logger.info(
                    "auto_comment_reply sent channel=%s store_id=%s comment_id=%s",
                    channel,
                    str(store_id),
                    str(comment_id),
                )
            except Exception as exc:  # pragma: no cover - defensive network guard
                logger.warning(
                    "auto_comment_reply failed channel=%s store_id=%s comment_id=%s error=%s",
                    channel,
                    str(store_id),
                    str(comment_id),
                    str(exc),
                )

    print("\n" + "=" * 60)
    print("📨 RECEIVED META WEBHOOK EVENT (AGENT PROCESSING)")
    print("=" * 60)

    for entry, store_id in mapped_entries:
        messaging_events = entry.get("messaging", [])
        for event in messaging_events:
            if not isinstance(event, dict):
                continue
            if "read" in event or "delivery" in event:
                logger.debug("PARSED ignored non-message event (read/delivery)")
                continue

            message_data = event.get("message")
            if isinstance(message_data, dict) and message_data.get("is_echo"):
                logger.debug("PARSED ignored Messenger echo event")
                continue

            sender_id = (event.get("sender") or {}).get("id")
            if not sender_id:
                continue
            if not isinstance(message_data, dict) or not isinstance(
                message_data.get("text"), str
            ):
                continue

            text = message_data["text"]
            external_mid = message_data.get("mid")
            delivery_trace_id = uuid.uuid4().hex

            # --- SAFETY NET: Ensure clean transaction state before starting ---
            try:
                if db.in_transaction():
                    db.rollback()
            except Exception:
                pass

            ai_reply = ""
            conv_id_for_log = None
            processing_failed = False
            customer = None
            turn_diagnostics = {}
            response_sent_count = 0

            try:
                # 1. Resolve only the store bound to this signed Meta account.
                store = db.query(Store).filter(
                    Store.id == store_id,
                    Store.is_active.is_(True),
                ).first()
                if not store:
                    print("⚠️ Connected Meta store is inactive or unavailable.")
                    continue

                # 2. Identify/Create Customer
                customer = db.query(Customer).filter(
                    Customer.phone == sender_id,
                    Customer.store_id == store.id
                ).first()

                if not customer:
                    customer = Customer(
                        store_id=store.id,
                        name=f"FB User {sender_id[-6:]}",
                        phone=sender_id,
                        email=None,
                    )
                    db.add(customer)
                    db.flush()

                # 3. Identify/Create Active Conversation
                conv = db.query(Conversation).filter(
                    Conversation.store_id == store.id,
                    Conversation.customer_id == customer.id,
                    Conversation.channel == channel,
                    Conversation.status == ConversationStatus.ACTIVE
                ).first()

                if not conv:
                    conv = Conversation(
                        store_id=store.id,
                        customer_id=customer.id,
                        channel=channel,
                        status=ConversationStatus.ACTIVE,
                    )
                    db.add(conv)
                    db.flush()

                conv_id_for_log = conv.id

                inserted = _persist_inbound_message(
                    db=db,
                    conversation_id=conv.id,
                    store_id=store.id,
                    channel=channel,
                    sender_id=sender_id,
                    text=text,
                    external_message_id=external_mid,
                )

                # If duplicate, skip the rest of the processing for this event
                if not inserted:
                    skipped_duplicates += 1
                    logger.info(
                        (
                            "conversation_delivery delivery_id=%s "
                            "inbound_message_id_present=%s duplicate_inbound=true "
                            "response_candidates=0 responses_sent=0"
                        ),
                        delivery_trace_id,
                        bool(external_mid),
                    )
                    print("♻️ Duplicate inbound event skipped.")
                    continue

                # 5. Process via Engine (Only for NEW messages)
                result = await _engine.process_message(
                    db=db,
                    store_id=store.id,
                    customer_id=customer.id,
                    conversation_id=conv.id,
                    channel=channel,
                    user_message=text,
                )
                ai_reply = result.get("response", "")
                turn_diagnostics = result.get("turn_diagnostics") or {}
                processing_failed = bool(result.get("processing_failed"))
                logger.debug(
                    "AGENT_REPLY delivery_id=%s reply_length=%d",
                    delivery_trace_id,
                    len(ai_reply),
                )

                # Log tool usage
                if result.get("tool_calls"):
                    tools_used = [tc['name'] for tc in result['tool_calls']]
                    print(f"🔧 Tools Executed: {tools_used}")

            except InboundMessagePersistenceError as persistence_error:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to persist inbound message",
                ) from persistence_error
            except Exception as engine_err:
                print(f"❌ Engine/AI Error: {str(engine_err)}")
                db.rollback()
                # The complete turn was rolled back, so only an apology can be sent.
                ai_reply = "عذراَ، حدث خطأ تقني مؤقت. سأحاول مساعدتك لاحقاَ."
                processing_failed = True

            # The engine persists successful replies in the same transaction as the
            # inbound message and tool changes. Failed turns are rolled back; their
            # fallback apology is sent but is not recorded as a completed reply.
            if ai_reply and conv_id_for_log:
                if not processing_failed:
                    processed_count += 1

                if channel == "facebook":
                    recipient_id = str(sender_id)
                    logger.debug(
                        "SEND_ATTEMPT delivery_id=%s",
                        delivery_trace_id,
                    )
                    try:
                        if not recipient_id:
                            raise RuntimeError(
                                "Customer.phone does not contain the Messenger PSID"
                            )
                        send_response = await _send_facebook_message(
                            recipient_id=recipient_id,
                            text=ai_reply,
                        )
                        if send_response.is_success:
                            response_sent_count = 1
                            logger.debug(
                                "SEND_OK status_code=%d",
                                send_response.status_code,
                            )
                        else:
                            logger.error(
                                "SEND_FAIL status_code=%d",
                                send_response.status_code,
                            )
                    except (httpx.HTTPError, RuntimeError) as send_err:
                        logger.error(
                            "SEND_FAIL error_type=%s",
                            type(send_err).__name__,
                        )

            logger.info(
                (
                    "conversation_delivery delivery_id=%s turn_id=%s intent=%s "
                    "resolver_action=%s inbound_message_id_present=%s "
                    "response_candidates=%d responses_sent=%d"
                ),
                delivery_trace_id,
                turn_diagnostics.get("turn_id", ""),
                turn_diagnostics.get("intent", "unknown"),
                turn_diagnostics.get("resolver_action", "unavailable"),
                bool(external_mid),
                turn_diagnostics.get(
                    "response_candidates",
                    1 if ai_reply else 0,
                ),
                response_sent_count,
            )

    print(f"✅ Processed: {processed_count} | ♻️ Skipped Duplicates: {skipped_duplicates}")
    print("=" * 60 + "\n")
    return {"status": "processed", "count": processed_count, "skipped": skipped_duplicates}


@router.get("/meta")
@router.get("/whatsapp")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verifier = (
        verify_whatsapp_verify_token
        if request.url.path.endswith("/whatsapp")
        else verify_meta_verify_token
    )
    try:
        token_valid = verifier(token or "")
    except RuntimeError:
        raise HTTPException(
            status_code=503,
            detail="Webhook verification token is not configured",
        )

    if mode == "subscribe" and token_valid:
        return int(challenge) if challenge and challenge.isdigit() else challenge
    raise HTTPException(status_code=403, detail="Invalid verification token")
