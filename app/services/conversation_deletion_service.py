"""Delete one conversation and only records directly owned by it."""

import logging
import uuid

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.models.ai_usage_event import AIUsageEvent
from app.models.conversation import Conversation, Message
from app.models.human_handoff import HumanHandoff
from app.models.order import Order, OrderItem
from app.models.outbound_delivery import OutboundDelivery
from app.models.sales_opportunity import SalesOpportunity

logger = logging.getLogger(__name__)


def delete_conversation_records(
    db: Session,
    conversation: Conversation,
    *,
    delete_orders: bool,
) -> None:
    """Apply the deletion policy; the caller owns commit and rollback."""
    inspector = inspect(db.get_bind())
    order_filter = (
        Order.store_id == conversation.store_id,
        Order.conversation_id == conversation.id,
    )
    order_ids = [
        order_id
        for (order_id,) in db.query(Order.id).filter(*order_filter).all()
    ]

    if delete_orders:
        if order_ids:
            db.query(OrderItem).filter(OrderItem.order_id.in_(order_ids)).delete(
                synchronize_session=False
            )
            if inspector.has_table(SalesOpportunity.__tablename__):
                db.query(SalesOpportunity).filter(
                    SalesOpportunity.related_order_id.in_(order_ids)
                ).update(
                    {SalesOpportunity.related_order_id: None},
                    synchronize_session=False,
                )
            else:
                logger.warning(
                    "conversation_delete_optional_table_missing table=%s",
                    SalesOpportunity.__tablename__,
                )
            db.query(Order).filter(*order_filter).delete(synchronize_session=False)
    else:
        db.query(Order).filter(*order_filter).update(
            {Order.conversation_id: None},
            synchronize_session=False,
        )

    db.query(AIUsageEvent).filter(
        AIUsageEvent.conversation_id == conversation.id
    ).update(
        {AIUsageEvent.conversation_id: None},
        synchronize_session=False,
    )

    delivery_ids = [
        delivery_id
        for (delivery_id,) in db.query(OutboundDelivery.id)
        .filter(OutboundDelivery.conversation_id == conversation.id)
        .all()
    ]
    if delivery_ids:
        db.query(OutboundDelivery).filter(
            OutboundDelivery.conversation_id != conversation.id,
            OutboundDelivery.fallback_for_id.in_(delivery_ids),
        ).update(
            {OutboundDelivery.fallback_for_id: None},
            synchronize_session=False,
        )
        db.query(OutboundDelivery).filter(
            OutboundDelivery.conversation_id == conversation.id
        ).delete(synchronize_session=False)

    if inspector.has_table(HumanHandoff.__tablename__):
        db.query(HumanHandoff).filter(
            HumanHandoff.conversation_id == conversation.id
        ).delete(synchronize_session=False)
    else:
        logger.warning(
            "conversation_delete_optional_table_missing table=%s",
            HumanHandoff.__tablename__,
        )
    db.query(Message).filter(
        Message.conversation_id == conversation.id
    ).delete(synchronize_session=False)

    db.delete(conversation)
    db.flush()
