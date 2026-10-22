"""
CustomerContextService: builds structured customer context from
persisted application data only. Never invents data.

Architecture:
  Agent Tool -> CustomerContextService -> Database (via ORM queries)

Every query is scoped by store_id for tenant isolation.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer import Customer
from app.models.customer_memory import CustomerMemory
from app.models.order import Order, OrderItem, OrderStatus
from app.services.exceptions import NotFoundError

# Open statuses: orders that still require action
OPEN_STATUSES = [OrderStatus.DRAFT, OrderStatus.CONFIRMED]


def get_customer(db: Session, store_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
    """Fetch customer with strict tenant isolation."""
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.store_id == store_id)
        .first()
    )
    if customer is None:
        raise NotFoundError("Customer not found")
    return customer


def get_customer_context(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
    recent_orders_limit: int = 5,
    recent_conversations_limit: int = 5,
    memories_limit: int = 20,
) -> dict:
    """
    Build complete customer context. All queries scoped by store_id.
    Returns a plain dict (serializable) for the agent tool.
    """
    # 1. Verify customer exists in this store (raises NotFoundError if not)
    customer = get_customer(db, store_id, customer_id)

    # 2. Recent orders (all statuses, most recent first)
    recent_orders = (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .limit(recent_orders_limit)
        .all()
    )

    # 3. Open orders (DRAFT or CONFIRMED)
    open_orders = (
        db.query(Order)
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
            Order.status.in_(OPEN_STATUSES),
        )
        .order_by(Order.created_at.desc())
        .all()
    )

    # 4. Previous products (from order items, joined with orders)
    previous_products = (
        db.query(OrderItem, Order.created_at)
        .join(Order, OrderItem.order_id == Order.id)
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
        )
        .order_by(Order.created_at.desc())
        .limit(recent_orders_limit * 5)
        .all()
    )

    # 5. Recent conversations
    recent_conversations = (
        db.query(Conversation)
        .filter(
            Conversation.store_id == store_id,
            Conversation.customer_id == customer_id,
        )
        .order_by(Conversation.created_at.desc())
        .limit(recent_conversations_limit)
        .all()
    )

    # 6. Customer memories (preferences, interests, etc.)
    memories = (
        db.query(CustomerMemory)
        .filter(
            CustomerMemory.store_id == store_id,
            CustomerMemory.customer_id == customer_id,
        )
        .order_by(CustomerMemory.created_at.desc())
        .limit(memories_limit)
        .all()
    )

    # 7. Behavior summary (deterministic counts)
    behavior = _build_behavior_summary(db, store_id, customer_id)

    # 8. Build conversation summaries with last message
    conversation_summaries = []
    for conv in recent_conversations:
        msg_count = (
            db.query(func.count(Message.id))
            .filter(Message.conversation_id == conv.id)
            .scalar()
        )
        last_msg = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.created_at.desc())
            .first()
        )
        conversation_summaries.append(
            {
                "id": str(conv.id),
                "channel": conv.channel,
                "status": (
                    conv.status.value
                    if hasattr(conv.status, "value")
                    else str(conv.status)
                ),
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "last_message": last_msg.content[:200] if last_msg else None,
                "message_count": msg_count or 0,
            }
        )

    # 9. Assemble the context
    return {
        "customer": {
            "id": str(customer.id),
            "name": customer.name,
            "phone": customer.phone,
            "email": customer.email,
            "language": customer.language,
            "created_at": (
                customer.created_at.isoformat() if customer.created_at else None
            ),
        },
        "recent_orders": [
            {
                "id": str(o.id),
                "status": (
                    o.status.value if hasattr(o.status, "value") else str(o.status)
                ),
                "total_amount": str(o.total_amount),
                "currency": o.currency,
                "created_at": o.created_at.isoformat() if o.created_at else None,
                "item_count": len(
                    o.id
                    and db.query(OrderItem).filter(OrderItem.order_id == o.id).all()
                    or []
                ),
            }
            for o in recent_orders
        ],
        "open_orders": [
            {
                "id": str(o.id),
                "status": (
                    o.status.value if hasattr(o.status, "value") else str(o.status)
                ),
                "total_amount": str(o.total_amount),
                "currency": o.currency,
                "created_at": o.created_at.isoformat() if o.created_at else None,
            }
            for o in open_orders
        ],
        "previous_products": [
            {
                "product_id": str(item.product_id),
                "product_name": item.product_name,
                "quantity": item.quantity,
                "unit_price": str(item.unit_price),
                "order_date": order_date.isoformat() if order_date else None,
            }
            for item, order_date in previous_products
        ],
        "recent_conversations": conversation_summaries,
        "preferences": [
            {
                "memory_type": m.memory_type,
                "key": m.key,
                "value": m.value,
                "confidence": m.confidence,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
        "behavior_summary": behavior,
    }


def _build_behavior_summary(
    db: Session, store_id: uuid.UUID, customer_id: uuid.UUID
) -> dict:
    """Deterministic behavior summary from order data."""
    orders = (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .all()
    )

    total_orders = len(orders)
    completed = sum(1 for o in orders if o.status == OrderStatus.COMPLETED)
    cancelled = sum(1 for o in orders if o.status == OrderStatus.CANCELLED)
    open_count = sum(1 for o in orders if o.status in OPEN_STATUSES)

    # Total purchased quantity and spending
    total_qty = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, OrderItem.order_id == Order.id)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .scalar()
    )

    total_spent = (
        db.query(func.coalesce(func.sum(Order.total_amount), 0))
        .filter(
            Order.store_id == store_id,
            Order.customer_id == customer_id,
            Order.status == OrderStatus.COMPLETED,
        )
        .scalar()
    )

    last_order = (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .order_by(Order.created_at.desc())
        .first()
    )

    return {
        "total_orders": total_orders,
        "completed_orders": completed,
        "cancelled_orders": cancelled,
        "open_orders": open_count,
        "total_purchased_quantity": int(total_qty),
        "total_spent": str(total_spent),
        "last_order_date": (
            last_order.created_at.isoformat()
            if last_order and last_order.created_at
            else None
        ),
    }
