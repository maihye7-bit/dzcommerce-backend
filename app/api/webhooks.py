"""
Webhook endpoints - Integrated with ConversationEngine & Tool Registry.
Phase 12-D + Idempotency Fix: Robust duplicate webhook handling.
CRITICAL: Implements safe INSERT-or-SKIP logic for incoming messages.
"""
import json
import logging
import re
import uuid
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import get_db
from app.core.config import AGENT_PROVIDER
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.channel_identity import ChannelIdentity
from app.models.outbound_delivery import OutboundDelivery
from app.models.store import Store
from app.models.channel_account import ChannelAccount
from app.services.webhook_security import (
    verify_meta_signature,
    verify_meta_verify_token,
    verify_whatsapp_verify_token,
)
from app.services.inbound_attachments import (
    InboundAttachmentError,
    download_and_store_meta_image,
)
from app.services import product_image_storage
from app.services.exceptions import ImageStorageError
from app.services.channel_service import resolve_channel_customer
from app.services.outbound_delivery import (
    dispatch_due_deliveries,
    enqueue_delivery,
    resolve_meta_access_token,
)

# Imports for Phase 12-D Integration (FIXED: Added #)
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.mock_provider import MockLLMProvider
from app.agent.providers.qwen_provider import QwenLLMProvider
from app.agent.providers.freellm_provider import FreeLLMProvider
from app.agent.tools import tool_registry

router = APIRouter(prefix="/webhooks", tags=["social-webhooks"])
logger = logging.getLogger(__name__)  # FIXED: Changed name to __name__

class InboundMessagePersistenceError(Exception):
    """An inbound insert failed for a reason other than its scoped duplicate."""

def _build_llm_provider():
    if AGENT_PROVIDER == "qwen":
        return QwenLLMProvider()
    if AGENT_PROVIDER == "freellm":
        return FreeLLMProvider()
    return MockLLMProvider()

async def _send_facebook_comment_reply(
    comment_id: str,
    text: str,
    access_token: str,
) -> httpx.Response:
    url = f"https://graph.facebook.com/v26.0/{comment_id}/comments"
    payload = {"message": text}
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(
            url,
            params={"access_token": access_token},
            json=payload,
        )

async def _send_instagram_comment_reply(
    comment_id: str,
    text: str,
    access_token: str,
) -> httpx.Response:
    url = f"https://graph.facebook.com/v26.0/{comment_id}/replies"
    payload = {"message": text}
    async with httpx.AsyncClient(timeout=30.0) as client:
        return await client.post(
            url,
            params={"access_token": access_token},
            json=payload,
        )

# Initialize Components Once at Module Load Time (FIXED: Added #)
_llm_provider = _build_llm_provider()
_engine = ConversationEngine(llm_provider=_llm_provider, tool_registry=tool_registry)

def _extract_message_attachments(message_data: dict) -> list[dict]:
    attachments = message_data.get("attachments")
    if not isinstance(attachments, list):
        return []
    extracted = []
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        payload = attachment.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        attachment_id = attachment.get("id")
        extracted.append(
            {
                "type": str(attachment.get("type") or "unknown").casefold(),
                "url": payload.get("url") if isinstance(payload.get("url"), str) else None,
                "metadata": (
                    {"external_attachment_id": str(attachment_id)}
                    if attachment_id
                    else {}
                ),
            }
        )
    return extracted


async def _store_inbound_attachments(attachments: list[dict]) -> list[dict]:
    stored = []
    for attachment in attachments:
        attachment_type = attachment["type"]
        record = {"type": attachment_type, **attachment["metadata"]}
        if attachment_type != "image":
            record["status"] = "unsupported"
        elif not attachment.get("url"):
            record["status"] = "unavailable"
        else:
            try:
                record.update(
                    await download_and_store_meta_image(attachment["url"])
                )
            except InboundAttachmentError as exc:
                record.update(status="failed", failure_code=exc.failure_code)
                logger.warning(
                    "meta_attachment_receive_failed type=%s failure_code=%s",
                    attachment_type,
                    exc.failure_code,
                )
            except Exception as exc:
                record.update(
                    status="failed",
                    failure_code="attachment_processing_failed",
                )
                logger.error(
                    "meta_attachment_receive_failed type=%s failure_type=%s",
                    attachment_type,
                    type(exc).__name__,
                )
        stored.append(record)
    return stored


def _attachment_notice(attachments: list[dict], language: str) -> str:
    has_stored_image = any(
        attachment.get("type") == "image"
        and attachment.get("status") == "stored"
        for attachment in attachments
    )
    has_failed_image = any(
        attachment.get("type") == "image"
        and attachment.get("status") != "stored"
        for attachment in attachments
    )
    if has_failed_image:
        return (
            "تعذر فتح الصورة. أعد إرسالها من فضلك أو صف لي ما تحتاجه."
            if language == "ar"
            else "Je n'ai pas pu ouvrir la photo. Vous pouvez la renvoyer ou me décrire votre demande."
            if language == "fr"
            else "I couldn't open the image. Please resend it or describe what you need."
        )
    if has_stored_image:
        return (
            "وصلتني الصورة، لكن لا أستطيع تحليل محتواها بصرياً حالياً. صف لي ما تحتاجه وسأساعدك."
            if language == "ar"
            else "J'ai bien reçu la photo, mais je ne peux pas analyser son contenu visuellement pour le moment. Décrivez-moi votre besoin."
            if language == "fr"
            else "I received the image, but I can't analyze its visual contents right now. Please describe what you need."
        )
    return (
        "وصلني المرفق، لكن لا يمكنني قراءته حالياً. أرسل صورة بصيغة مدعومة أو صف لي ما تحتاجه."
        if language == "ar"
        else "J'ai reçu la pièce jointe, mais je ne peux pas la lire pour le moment."
        if language == "fr"
        else "I received the attachment, but can't read it right now."
    )


def _message_language(text: str) -> str:
    if re.search(r"[\u0600-\u06ff]", text or ""):
        return "ar"
    if re.search(
        r"\b(?:bonjour|merci|photo|produit|envoyer|est-ce|vous)\b",
        text or "",
        re.IGNORECASE,
    ):
        return "fr"
    return "ar"


def _persist_webhook_reply(
    db: Session,
    conversation_id: uuid.UUID,
    response: str,
    previous_response: str | None = None,
    channel: str | None = None,
    external_account_id: str | None = None,
    recipient_external_id: str | None = None,
) -> None:
    message = None
    if previous_response:
        message = (
            db.query(Message)
            .filter(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.AGENT,
                Message.content == previous_response,
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
        )
    if message is not None:
        message.content = response
        db.flush()
        queued_deliveries = (
            db.query(OutboundDelivery)
            .filter(
                OutboundDelivery.message_id == message.id,
                OutboundDelivery.payload_type == "text",
            )
            .all()
        )
        pending_delivery = next(
            (delivery for delivery in queued_deliveries if delivery.status == "pending"),
            None,
        )
        if pending_delivery is not None:
            pending_delivery.payload_json = {"text": response}
        elif not queued_deliveries and channel and external_account_id and recipient_external_id:
            enqueue_delivery(
                db,
                conversation_id=conversation_id,
                message_id=message.id,
                channel=channel,
                external_account_id=external_account_id,
                recipient_external_id=recipient_external_id,
                payload_type="text",
                payload={"text": response},
            )
    else:
        message = Message(
            conversation_id=conversation_id,
            role=MessageRole.AGENT,
            content=response,
        )
        db.add(message)
        db.flush()
        if channel and external_account_id and recipient_external_id:
            enqueue_delivery(
                db,
                conversation_id=conversation_id,
                message_id=message.id,
                channel=channel,
                external_account_id=external_account_id,
                recipient_external_id=recipient_external_id,
                payload_type="text",
                payload={"text": response},
            )
    db.commit()


def _delete_stored_attachments(attachments: list[dict]) -> None:
    for attachment in attachments:
        storage_key = attachment.get("storage_key")
        if attachment.get("status") != "stored" or not isinstance(storage_key, str):
            continue
        try:
            product_image_storage.delete_image(storage_key)
        except ImageStorageError as exc:
            logger.error(
                "meta_attachment_cleanup_failed failure_type=%s",
                type(exc).__name__,
            )


def _persist_inbound_message(
    db: Session,
    conversation_id: uuid.UUID,
    store_id: uuid.UUID,
    channel: str,
    sender_id: str,
    text: str,
    external_message_id: str | None,
    attachments: list[dict] | None = None,
    external_account_id: str | None = None,
) -> bool:
    """Stage an inbound event; return False only for its scoped duplicate."""
    attachments = attachments or []
    has_image = any(attachment["type"] == "image" for attachment in attachments)
    initial_attachment_metadata = [
        {
            "type": attachment["type"],
            "status": "pending" if attachment.get("url") else "unavailable",
            **attachment["metadata"],
        }
        for attachment in attachments
    ]
    message = Message(
        conversation_id=conversation_id,
        role=MessageRole.CUSTOMER,
        content=text,
        message_type=(
            "text_image"
            if text.strip() and has_image
            else "image"
            if has_image
            else "text_attachment"
            if text.strip() and attachments
            else "attachment"
            if attachments
            else "text"
        ),
        external_message_id=external_message_id,
        metadata_json=(
            {"attachments": initial_attachment_metadata}
            if attachments
            else None
        ),
    )
    db.add(message)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        if external_message_id is None:
            raise InboundMessagePersistenceError from exc
        
        existing_message = (
            db.query(Message.id)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .join(
                ChannelIdentity,
                (ChannelIdentity.customer_id == Conversation.customer_id)
                & (ChannelIdentity.store_id == Conversation.store_id),
            )
            .filter(
                Message.external_message_id == external_message_id,
                Conversation.store_id == store_id,
                Conversation.channel == channel,
                ChannelIdentity.external_account_id == external_account_id,
                ChannelIdentity.external_user_id == sender_id,
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
    
    # 1. Verify Signature
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

    # 2. Parse Payload
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

    # 3. Resolve Stores (With Graceful Auto-Provisioning)
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

        # Try to find existing active store link
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

        target_store_id = None
        if store_ids:
            if len(store_ids) > 1:
                raise HTTPException(
                    status_code=409,
                    detail="Meta account is connected to multiple stores",
                )
            target_store_id = store_ids[0][0]
        else:
            # Fallback mechanism: Graceful Auto-Provisioning for dev/initial setup
            active_stores = db.query(Store).filter(Store.is_active.is_(True)).all()
            
            if len(active_stores) == 1:
                default_store = active_stores[0]
                
                # Attempt to create/link a temporary ChannelAccount
                try:
                    new_account = ChannelAccount(
                        store_id=default_store.id,
                        channel=channel,
                        external_account_id=str(account_id),
                        external_account_name=f"Auto-linked {channel.capitalize()} Page",
                        is_active=True,
                    )
                    db.add(new_account)
                    db.commit()
                    db.refresh(new_account)
                    target_store_id = default_store.id
                    logger.info(
                        "AUTO_LINKED_NEW_PAGE: Linked page %s to store %s", 
                        account_id, 
                        default_store.name
                    )
                    
                except Exception as e:
                    db.rollback()
                    logger.error("Failed to auto-link page %s: %s", account_id, str(e))
                    return {
                        "status": "ignored",
                        "reason": f"Auto-linking failed: {str(e)}"
                    }
            else:
                # No active store or multiple stores - return 200 OK but ignored status
                logger.warning(
                    "UNLINKED_PAGE_RECEIVED: No unique active store to auto-link page %s", 
                    account_id
                )
                return {
                    "status": "ignored",
                    "reason": "No active store linked to this Page ID. Please connect via Dashboard."
                }

        mapped_entries.append((entry, target_store_id))

    processed_count = 0
    skipped_duplicates = 0

    # 4. Process Entries
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
                access_token = resolve_meta_access_token(
                    db,
                    store_id=store_id,
                    channel=channel,
                    external_account_id=str(entry.get("id") or ""),
                )
                if access_token is None:
                    raise RuntimeError("Meta account credential unavailable")
                if channel == "facebook":
                    await _send_facebook_comment_reply(
                        str(comment_id),
                        reply_text,
                        access_token,
                    )
                else:
                    await _send_instagram_comment_reply(
                        str(comment_id),
                        reply_text,
                        access_token,
                    )
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
            sender_id = str(sender_id)
                
            if not isinstance(message_data, dict):
                continue
            message_text = message_data.get("text")
            text = message_text if isinstance(message_text, str) else ""
            raw_attachments = _extract_message_attachments(message_data)
            if not text.strip() and not raw_attachments:
                continue

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
            attachment_metadata = []

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
                external_account_id = str(entry.get("id") or "")
                customer = resolve_channel_customer(
                    db=db,
                    store_id=store.id,
                    channel=channel,
                    external_account_id=external_account_id,
                    external_user_id=str(sender_id),
                    display_name=f"{channel.upper()} User {str(sender_id)[-6:]}",
                )

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
                conv_metadata = dict(conv.metadata_json or {})
                conv_metadata["external_account_id"] = external_account_id
                conv.metadata_json = conv_metadata
                
                conv_id_for_log = conv.id

                inserted = _persist_inbound_message(
                    db=db,
                    conversation_id=conv.id,
                    store_id=store.id,
                    channel=channel,
                    sender_id=sender_id,
                    external_account_id=external_account_id,
                    text=text,
                    external_message_id=external_mid,
                    attachments=raw_attachments,
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

                inbound_query = db.query(Message).filter(
                    Message.conversation_id == conv.id,
                    Message.role == MessageRole.CUSTOMER,
                )
                if external_mid:
                    inbound_query = inbound_query.filter(
                        Message.external_message_id == external_mid
                    )
                else:
                    inbound_query = inbound_query.filter(Message.content == text)
                inbound_message = (
                    inbound_query.order_by(
                        Message.created_at.desc(),
                        Message.id.desc(),
                    )
                    .first()
                )
                if inbound_message is None:
                    raise InboundMessagePersistenceError

                db.commit()
                if raw_attachments:
                    attachment_metadata = await _store_inbound_attachments(
                        raw_attachments
                    )
                if raw_attachments:
                    has_image = any(
                        attachment["type"] == "image"
                        for attachment in raw_attachments
                    )
                    inbound_message.message_type = (
                        "text_image"
                        if text.strip() and has_image
                        else "image"
                        if has_image
                        else "text_attachment"
                        if text.strip()
                        else "attachment"
                    )
                    inbound_message.metadata_json = {
                        "attachments": attachment_metadata
                    }

                if raw_attachments and not text.strip():
                    ai_reply = _attachment_notice(
                        attachment_metadata,
                        _message_language(text),
                    )
                    _persist_webhook_reply(
                        db,
                        conv.id,
                        ai_reply,
                        channel=channel,
                        external_account_id=external_account_id,
                        recipient_external_id=sender_id,
                    )
                    turn_diagnostics = {
                        "intent": "image_received",
                        "resolver_action": "RESPOND:text_only",
                        "response_candidates": 1,
                    }
                else:
                    attachment_suffix = (
                        _attachment_notice(
                            attachment_metadata,
                            _message_language(text),
                        )
                        if raw_attachments
                        else None
                    )
                    result = await _engine.process_message(
                        db=db,
                        store_id=store.id,
                        customer_id=customer.id,
                        conversation_id=conv.id,
                        channel=channel,
                        user_message=text,
                        external_account_id=external_account_id,
                        external_user_id=sender_id,
                        outbound_suffix=attachment_suffix,
                    )
                    ai_reply = result.get("response", "")
                    turn_diagnostics = result.get("turn_diagnostics") or {}
                    processing_failed = bool(result.get("processing_failed"))

                    if raw_attachments:
                        if processing_failed:
                            ai_reply = (
                                f"{ai_reply}\n\n{attachment_suffix}".strip()
                            )
                            _delete_stored_attachments(attachment_metadata)
                        elif attachment_suffix and not ai_reply.endswith(
                            attachment_suffix
                        ):
                            ai_reply = f"{ai_reply}\n\n{attachment_suffix}".strip()
                    if ai_reply and not processing_failed:
                        _persist_webhook_reply(
                            db,
                            conv.id,
                            ai_reply,
                            previous_response=result.get("response"),
                            channel=channel,
                            external_account_id=external_account_id,
                            recipient_external_id=sender_id,
                        )

                    logger.debug(
                        "AGENT_REPLY delivery_id=%s reply_length=%d",
                        delivery_trace_id,
                        len(ai_reply),
                    )

                    if result.get("tool_calls"):
                        tools_used = [tc["name"] for tc in result["tool_calls"]]
                        print(f"🔧 Tools Executed: {tools_used}")

            except InboundMessagePersistenceError as persistence_error:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to persist inbound message",
                ) from persistence_error
            except Exception as engine_err:
                logger.error(
                    "conversation_processing_failed error_type=%s",
                    type(engine_err).__name__,
                )
                db.rollback()
                _delete_stored_attachments(attachment_metadata)
                # The complete turn was rolled back, so only an apology can be sent.
                ai_reply = "عذراً، حدث خطأ مؤقت. أعد إرسال رسالتك من فضلك."
                if raw_attachments:
                    ai_reply += "\n\n" + _attachment_notice(
                        attachment_metadata,
                        _message_language(text),
                    )
                processing_failed = True

            if ai_reply and processing_failed and conv_id_for_log:
                _persist_webhook_reply(
                    db,
                    conv_id_for_log,
                    ai_reply,
                    channel=channel,
                    external_account_id=external_account_id,
                    recipient_external_id=sender_id,
                )

            # The durable outbox, not the webhook event, owns response delivery.
            if ai_reply and conv_id_for_log and not processing_failed:
                processed_count += 1
            if conv_id_for_log:
                logger.debug("SEND_ATTEMPT delivery_id=%s", delivery_trace_id)
                response_sent_count = await dispatch_due_deliveries(db, limit=20)
                if response_sent_count:
                    logger.debug("SEND_OK delivered_count=%d", response_sent_count)
                elif ai_reply:
                    logger.error(
                        "SEND_FAIL delivery_id=%s reply remains pending_or_failed",
                        delivery_trace_id,
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
