"""Safe, single-conversation reset helpers for Messenger test data."""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.channel_identity import ChannelIdentity
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.models.order import Order, OrderItem, OrderStatus

_COMMERCE_METADATA_KEYS = {
    "selected_product_id",
    "selected_product_name",
    "selected_variant_id",
    "selected_attributes",
    "candidate_product_ids",
    "variant_index_map",
    "variant_index_map_product_id",
    "commerce_stage",
    "last_question_type",
    "last_intent",
    "last_nlu",
    "turn_plan",
    "pending_confirmation",
    "pending_confirmation_state",
    "confirmation_pending",
    "confirmation_state",
    "pending_action",
    "pending_action_state",
    "pending_action_type",
}
_UNCONFIRMED_DRAFT_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.WAITING_CONFIRMATION,
}


def _uuid(value: str | uuid.UUID, name: str) -> uuid.UUID:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{name} must be a valid UUID.") from exc


def _resolve_conversation(
    db: Session,
    store_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    psid: str | None,
    test_customer_id: uuid.UUID | None,
    *,
    for_update: bool = False,
) -> Conversation:
    selectors = [
        conversation_id is not None,
        psid is not None,
        test_customer_id is not None,
    ]
    if sum(selectors) != 1:
        raise ValueError(
            "Specify exactly one of conversation_id, PSID, or test_customer_id."
        )

    query = (
        db.query(Conversation)
        .join(
            Customer,
            (Conversation.customer_id == Customer.id)
            & (Conversation.store_id == Customer.store_id),
        )
        .filter(
            Conversation.store_id == store_id,
            Conversation.channel == "facebook",
        )
    )
    if for_update:
        query = query.with_for_update()
    if conversation_id is not None:
        conversation = query.filter(Conversation.id == conversation_id).one_or_none()
        if conversation is None:
            raise ValueError(
                "Messenger conversation was not found in the specified store."
            )
        return conversation

    if psid is not None:
        matches = (
            query.join(
                ChannelIdentity,
                (ChannelIdentity.customer_id == Customer.id)
                & (ChannelIdentity.store_id == Customer.store_id),
            )
            .filter(
                ChannelIdentity.store_id == store_id,
                ChannelIdentity.channel == "facebook",
                ChannelIdentity.external_user_id == psid,
            )
            .all()
        )
    else:
        matches = (
            query.filter(Customer.id == test_customer_id)
            .all()
        )

    if len(matches) != 1:
        if not matches:
            raise ValueError(
                "No Messenger conversation was found for this selector in the "
                "specified store."
            )
        raise ValueError(
            "The selector matches multiple Messenger conversations. "
            "Specify the exact conversation_id."
        )
    return matches[0]


def preview_messenger_test_conversation_reset(
    db: Session,
    *,
    store_id: str | uuid.UUID,
    conversation_id: str | uuid.UUID | None = None,
    psid: str | None = None,
    test_customer_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    """Return exact scoped record IDs and effects without modifying the database."""
    parsed_store_id = _uuid(store_id, "store_id")
    parsed_conversation_id = (
        _uuid(conversation_id, "conversation_id")
        if conversation_id is not None
        else None
    )
    parsed_customer_id = (
        _uuid(test_customer_id, "test_customer_id")
        if test_customer_id is not None
        else None
    )
    if psid is not None and not psid.strip():
        raise ValueError("psid must not be empty.")

    conversation = _resolve_conversation(
        db,
        parsed_store_id,
        parsed_conversation_id,
        psid,
        parsed_customer_id,
    )
    metadata = dict(conversation.metadata_json or {})
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
        .all()
    )
    orders = (
        db.query(Order)
        .filter(
            Order.conversation_id == conversation.id,
            Order.store_id == parsed_store_id,
        )
        .order_by(Order.created_at, Order.id)
        .all()
    )

    deletable_orders = [
        order
        for order in orders
        if order.status in _UNCONFIRMED_DRAFT_STATUSES
        and order.customer_id == conversation.customer_id
    ]
    preserved_orders = [order for order in orders if order not in deletable_orders]
    order_items_by_order: dict[uuid.UUID, list[str]] = {}
    if deletable_orders:
        order_items = (
            db.query(OrderItem)
            .filter(OrderItem.order_id.in_([order.id for order in deletable_orders]))
            .order_by(OrderItem.id)
            .all()
        )
        for item in order_items:
            order_items_by_order.setdefault(item.order_id, []).append(str(item.id))

    return {
        "store_id": str(parsed_store_id),
        "conversation": {
            "id": str(conversation.id),
            "customer_id": str(conversation.customer_id),
            "channel": conversation.channel,
            "status": conversation.status,
        },
        "messages_to_delete": [
            {
                "id": str(message.id),
                "role": message.role,
                "created_at": (
                    message.created_at.isoformat()
                    if message.created_at is not None
                    else None
                ),
            }
            for message in messages
        ],
        "conversation_fields_to_reset": {
            "active_draft_json": conversation.active_draft_json is not None,
            "metadata_keys_to_clear": sorted(
                key for key in metadata if key in _COMMERCE_METADATA_KEYS
            ),
            "metadata_keys_to_preserve": sorted(
                key for key in metadata if key not in _COMMERCE_METADATA_KEYS
            ),
        },
        "unconfirmed_test_orders_requiring_explicit_ids": [
            {
                "id": str(order.id),
                "status": order.status.value,
                "order_item_ids": order_items_by_order.get(order.id, []),
                "customer_id": (
                    str(order.customer_id) if order.customer_id else None
                ),
            }
            for order in deletable_orders
        ],
        "orders_to_preserve": [
            {
                "id": str(order.id),
                "status": order.status.value,
                "customer_id": (
                    str(order.customer_id) if order.customer_id else None
                ),
            }
            for order in preserved_orders
        ],
        "records_changed_by_reset": {
            "conversation": str(conversation.id),
            "message_ids": [str(message.id) for message in messages],
        },
    }


def reset_messenger_test_conversation(
    db: Session,
    *,
    store_id: str | uuid.UUID,
    conversation_id: str | uuid.UUID,
    delete_unconfirmed_test_order_ids: list[str | uuid.UUID] | None = None,
) -> dict[str, Any]:
    """Reset exactly one Messenger conversation and explicitly selected test drafts.

    The caller owns the outer transaction and must commit on success. A savepoint
    keeps the reset atomic when the caller uses a larger transaction.
    """
    parsed_store_id = _uuid(store_id, "store_id")
    parsed_conversation_id = _uuid(conversation_id, "conversation_id")
    selected_order_ids = {
        _uuid(order_id, "delete_unconfirmed_test_order_id")
        for order_id in (delete_unconfirmed_test_order_ids or [])
    }

    with db.begin_nested():
        conversation = _resolve_conversation(
            db,
            parsed_store_id,
            parsed_conversation_id,
            None,
            None,
            for_update=True,
        )
        plan = preview_messenger_test_conversation_reset(
            db,
            store_id=parsed_store_id,
            conversation_id=parsed_conversation_id,
        )
        eligible_order_ids = {
            uuid.UUID(item["id"])
            for item in plan["unconfirmed_test_orders_requiring_explicit_ids"]
        }
        if not selected_order_ids.issubset(eligible_order_ids):
            raise ValueError(
                "Only listed, same-customer DRAFT or WAITING_CONFIRMATION orders "
                "may be selected for cleanup."
            )

        if selected_order_ids:
            selected_items = (
                db.query(OrderItem)
                .join(Order, OrderItem.order_id == Order.id)
                .filter(
                    Order.id.in_(selected_order_ids),
                    Order.conversation_id == parsed_conversation_id,
                    Order.store_id == parsed_store_id,
                )
                .all()
            )
            deleted_item_ids = [str(item.id) for item in selected_items]
            for item in selected_items:
                db.delete(item)
            selected_orders = (
                db.query(Order)
                .filter(
                    Order.id.in_(selected_order_ids),
                    Order.conversation_id == parsed_conversation_id,
                    Order.store_id == parsed_store_id,
                    Order.customer_id == conversation.customer_id,
                    Order.status.in_(_UNCONFIRMED_DRAFT_STATUSES),
                )
                .with_for_update()
                .all()
            )
            if {order.id for order in selected_orders} != selected_order_ids:
                raise ValueError(
                    "One or more selected draft orders changed or no longer "
                    "belong to this conversation."
                )
            for order in selected_orders:
                db.delete(order)
        else:
            deleted_item_ids = []

        db.query(Message).filter(
            Message.conversation_id == parsed_conversation_id
        ).delete(synchronize_session=False)

        metadata = dict(conversation.metadata_json or {})
        for key in _COMMERCE_METADATA_KEYS:
            metadata.pop(key, None)
        conversation.metadata_json = metadata
        conversation.active_draft_json = None
        db.flush()

        plan["unconfirmed_test_orders_requiring_explicit_ids"] = [
            item
            for item in plan["unconfirmed_test_orders_requiring_explicit_ids"]
            if uuid.UUID(item["id"]) not in selected_order_ids
        ]
        plan["orders_deleted"] = sorted(str(order_id) for order_id in selected_order_ids)
        plan["order_item_ids_deleted"] = sorted(deleted_item_ids)
        plan["records_changed_by_reset"]["metadata_keys_cleared"] = (
            plan["conversation_fields_to_reset"]["metadata_keys_to_clear"]
        )
        plan["records_changed_by_reset"]["active_draft_json_set_to_null"] = True
        return plan
