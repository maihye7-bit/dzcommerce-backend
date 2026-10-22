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
from app.services.exceptions import NotFoundError


def _resolve_customer(
    db: Session, store_id: uuid.UUID, event: InboundEvent
) -> Customer:
    """
    Find or create a Customer for this inbound event.
    Uses ChannelIdentity to map external user IDs to internal customers.
    """
    identity = (
        db.query(ChannelIdentity)
        .filter(
            ChannelIdentity.store_id == store_id,
            ChannelIdentity.channel == event.channel,
            ChannelIdentity.external_user_id == event.external_user_id,
        )
        .first()
    )

    if identity:
        return (
            db.query(Customer)
            .filter(Customer.id == identity.customer_id, Customer.store_id == store_id)
            .first()
        )

    # No identity found -> create new customer + identity
    customer = Customer(
        store_id=store_id,
        name=event.customer_name or f"{event.channel} User",
        external_id=f"{event.channel}:{event.external_user_id}",
    )
    db.add(customer)
    db.flush()

    new_identity = ChannelIdentity(
        store_id=store_id,
        customer_id=customer.id,
        channel=event.channel,
        external_user_id=event.external_user_id,
        external_username=event.customer_name,
    )
    db.add(new_identity)
    db.flush()

    return customer


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

    msg = Message(
        conversation_id=conversation.id,
        role=MessageRole.CUSTOMER,
        content=event.message_text,
        message_type=event.event_type,
        external_message_id=event.external_message_id,
    )
    db.add(msg)
    db.commit()

    return {
        "skipped": False,
        "conversation_id": str(conversation.id),
        "customer_id": str(customer.id),
        "message_type": event.event_type,
    }
