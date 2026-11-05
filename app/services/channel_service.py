"""
ChannelService: Bridges external channel events to the Conversation Engine.

Responsibilities:
  - Resolve/create ChannelIdentity for the sender
  - Find or create a Conversation for the event
  - Enforce idempotency via external_message_id
  - Delegate message processing to ConversationEngine

Architecture:
  Webhook -> ChannelAdapter.normalize() -> ChannelService.handle_event()
    -> ConversationEngine.process_message()
"""

import uuid

from sqlalchemy.orm import Session

from app.models.channel_identity import ChannelIdentity
from app.models.conversation import Conversation, ConversationStatus, Message
from app.models.customer import Customer
from app.schemas.channel_events import InboundEvent
from sqlalchemy.exc import IntegrityError


def resolve_channel_customer(
    db: Session,
    store_id: uuid.UUID,
    channel: str,
    external_account_id: str | None,
    external_user_id: str,
    display_name: str | None = None,
) -> Customer:
    """Resolve a tenant- and account-scoped external user identity."""
    identity_filter = (
        ChannelIdentity.store_id == store_id,
        ChannelIdentity.channel == channel,
        ChannelIdentity.external_account_id == external_account_id,
        ChannelIdentity.external_user_id == external_user_id,
    )
    def find_identity() -> ChannelIdentity | None:
        identities = db.query(ChannelIdentity).filter(*identity_filter).all()
        if len(identities) > 1:
            raise ValueError(
                "Multiple legacy channel identities match this account-less user"
            )
        return identities[0] if identities else None

    identity = find_identity()

    if identity:
        customer = (
            db.query(Customer)
            .filter(Customer.id == identity.customer_id, Customer.store_id == store_id)
            .one_or_none()
        )
        if customer is None:
            raise ValueError("Channel identity is not attached to a customer in this store")
        return customer

    try:
        with db.begin_nested():
            customer = Customer(
                store_id=store_id,
                name=display_name or f"{channel} User",
            )
            db.add(customer)
            db.flush()
            db.add(
                ChannelIdentity(
                    store_id=store_id,
                    customer_id=customer.id,
                    channel=channel,
                    external_account_id=external_account_id,
                    external_user_id=external_user_id,
                    external_username=display_name,
                )
            )
            db.flush()
    except IntegrityError:
        identity = find_identity()
        if identity is None:
            raise
        customer = (
            db.query(Customer)
            .filter(Customer.id == identity.customer_id, Customer.store_id == store_id)
            .one_or_none()
        )
        if customer is None:
            raise ValueError("Channel identity is not attached to a customer in this store")

    return customer


def _resolve_customer(db: Session, store_id: uuid.UUID, event: InboundEvent) -> Customer:
    return resolve_channel_customer(
        db=db,
        store_id=store_id,
        channel=event.channel,
        external_account_id=event.metadata.get("external_account_id"),
        external_user_id=event.external_user_id,
        display_name=event.customer_name,
    )


def _find_or_create_conversation(
    db: Session, store_id: uuid.UUID, customer_id: uuid.UUID, event: InboundEvent
) -> Conversation:
    """Find an existing active conversation or create a new one."""
    conv = (
        db.query(Conversation)
        .filter(
            Conversation.store_id == store_id,
            Conversation.customer_id == customer_id,
            Conversation.channel == event.channel,
            Conversation.external_conversation_id == event.external_conversation_id,
            Conversation.status == ConversationStatus.ACTIVE,
        )
        .first()
    )

    if conv:
        return conv

    conv = Conversation(
        store_id=store_id,
        customer_id=customer_id,
        channel=event.channel,
        external_conversation_id=event.external_conversation_id,
        status=ConversationStatus.ACTIVE,
    )
    db.add(conv)
    db.flush()
    return conv


def _is_duplicate_message(db: Session, external_message_id: str) -> bool:
    """Check if we have already processed this external message (idempotency)."""
    if not external_message_id:
        return False
    exists = (
        db.query(Message)
        .filter(Message.external_message_id == external_message_id)
        .first()
    )
    return exists is not None


def handle_inbound_event(
    db: Session,
    store_id: uuid.UUID,
    event: InboundEvent,
) -> dict:
    """
    Process a normalized inbound event.

    Returns:
        dict with conversation_id and whether the message was processed
        or skipped (duplicate).
    """
    # Idempotency check
    if _is_duplicate_message(db, event.external_message_id):
        return {"skipped": True, "reason": "duplicate_message"}

    # Resolve customer
    customer = _resolve_customer(db, store_id, event)

    # Find or create conversation
    conversation = _find_or_create_conversation(db, store_id, customer.id, event)

    # Store the inbound message with external ID for idempotency
    from app.models.conversation import MessageRole

    attachment_metadata = [
        {
            "type": attachment.type,
            "status": "not_downloaded" if attachment.url else "unavailable",
            **attachment.metadata,
        }
        for attachment in event.attachments
    ]
    has_image = any(
        attachment.type == "image" for attachment in event.attachments
    )
    msg = Message(
        conversation_id=conversation.id,
        role=MessageRole.CUSTOMER,
        content=event.message_text,
        message_type=(
            "text_image"
            if event.message_text.strip() and has_image
            else "image"
            if has_image
            else "text_attachment"
            if event.message_text.strip() and event.attachments
            else "attachment"
            if event.attachments
            else event.event_type
        ),
        external_message_id=event.external_message_id,
        metadata_json=(
            {"attachments": attachment_metadata}
            if attachment_metadata
            else None
        ),
    )
    db.add(msg)
    db.commit()

    return {
        "skipped": False,
        "conversation_id": str(conversation.id),
        "customer_id": str(customer.id),
        "message_type": event.event_type,
    }
