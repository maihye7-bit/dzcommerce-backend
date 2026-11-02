import uuid

import pytest

from app.models.channel_identity import ChannelIdentity
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.customer import Customer
from app.models.order import Order, OrderItem, OrderStatus
from app.models.store import Store
from app.services.messenger_test_conversation_reset import (
    preview_messenger_test_conversation_reset,
    reset_messenger_test_conversation,
)


def _conversation_fixture(db_session):
    store = Store(name="Messenger reset test", slug=f"reset-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(
        store_id=store.id,
        name="Messenger test customer",
        facebook_id="psid-reset-test",
    )
    db_session.add(customer)
    db_session.flush()
    db_session.add(
        ChannelIdentity(
            store_id=store.id,
            customer_id=customer.id,
            channel="facebook",
            external_user_id="psid-reset-test",
        )
    )
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
        metadata_json={
            "selected_product_id": str(uuid.uuid4()),
            "selected_variant_id": str(uuid.uuid4()),
            "candidate_product_ids": [str(uuid.uuid4())],
            "variant_index_map": {"1": str(uuid.uuid4())},
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "pending_confirmation_state": {"action": "confirm"},
            "pending_action_state": {"action": "create_draft"},
            "custom_setting": "keep",
        },
        active_draft_json={"items": [{"quantity": 1}]},
    )
    db_session.add(conversation)
    db_session.flush()
    messages = [
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="old customer message",
        ),
        Message(
            conversation_id=conversation.id,
            role=MessageRole.AGENT,
            content="old bot message",
        ),
    ]
    db_session.add_all(messages)
    db_session.flush()
    return store, customer, conversation, messages


def _add_order(db_session, store, customer, conversation, status):
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        status=status,
        subtotal=100,
        shipping_cost=0,
        total=100,
    )
    db_session.add(order)
    db_session.flush()
    item = OrderItem(
        order_id=order.id,
        quantity=1,
        unit_price=100,
    )
    db_session.add(item)
    db_session.flush()
    return order, item


def test_reset_preview_is_scoped_and_read_only(db_session):
    store, customer, conversation, messages = _conversation_fixture(db_session)
    draft, draft_item = _add_order(
        db_session, store, customer, conversation, OrderStatus.DRAFT
    )
    confirmed, _ = _add_order(
        db_session, store, customer, conversation, OrderStatus.CONFIRMED
    )
    db_session.flush()

    preview = preview_messenger_test_conversation_reset(
        db_session,
        store_id=store.id,
        conversation_id=conversation.id,
    )

    assert preview["conversation"]["id"] == str(conversation.id)
    assert {item["id"] for item in preview["messages_to_delete"]} == {
        str(message.id) for message in messages
    }
    assert preview["conversation_fields_to_reset"]["metadata_keys_to_clear"]
    assert preview["conversation_fields_to_reset"]["metadata_keys_to_preserve"] == [
        "custom_setting"
    ]
    assert preview["unconfirmed_test_orders_requiring_explicit_ids"] == [
        {
            "id": str(draft.id),
            "status": "draft",
            "order_item_ids": [str(draft_item.id)],
            "customer_id": str(customer.id),
        }
    ]
    assert preview["orders_to_preserve"][0]["id"] == str(confirmed.id)
    assert db_session.query(Message).filter(
        Message.conversation_id == conversation.id
    ).count() == 2
    assert conversation.active_draft_json is not None


def test_reset_clears_one_conversation_and_only_explicit_unconfirmed_drafts(
    db_session,
):
    store, customer, conversation, _ = _conversation_fixture(db_session)
    other_conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
        metadata_json={"commerce_stage": "PRODUCT_SELECTED"},
        active_draft_json={"items": [{"quantity": 1}]},
    )
    db_session.add(other_conversation)
    db_session.flush()
    other_message = Message(
        conversation_id=other_conversation.id,
        role=MessageRole.CUSTOMER,
        content="keep other conversation",
    )
    db_session.add(other_message)

    draft, draft_item = _add_order(
        db_session, store, customer, conversation, OrderStatus.DRAFT
    )
    waiting, waiting_item = _add_order(
        db_session,
        store,
        customer,
        conversation,
        OrderStatus.WAITING_CONFIRMATION,
    )
    confirmed, confirmed_item = _add_order(
        db_session, store, customer, conversation, OrderStatus.CONFIRMED
    )
    unrelated_customer = Customer(
        store_id=store.id,
        name="Different customer",
    )
    db_session.add(unrelated_customer)
    db_session.flush()
    mismatched_customer_order, mismatched_item = _add_order(
        db_session, store, unrelated_customer, conversation, OrderStatus.DRAFT
    )
    db_session.flush()
    expected_messages = {
        message.id
        for message in db_session.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .all()
    }

    result = reset_messenger_test_conversation(
        db_session,
        store_id=store.id,
        conversation_id=conversation.id,
        delete_unconfirmed_test_order_ids=[draft.id, waiting.id],
    )

    assert set(result["records_changed_by_reset"]["message_ids"]) == {
        str(message_id) for message_id in expected_messages
    }
    assert set(result["orders_deleted"]) == {str(draft.id), str(waiting.id)}
    assert set(result["order_item_ids_deleted"]) == {
        str(draft_item.id),
        str(waiting_item.id),
    }
    assert db_session.query(Message).filter(
        Message.conversation_id == conversation.id
    ).count() == 0
    assert db_session.query(Message).filter(Message.id == other_message.id).count() == 1
    assert conversation.active_draft_json is None
    assert conversation.metadata_json == {"custom_setting": "keep"}
    assert db_session.get(Order, confirmed.id) is not None
    assert db_session.get(OrderItem, confirmed_item.id) is not None
    assert db_session.get(Order, mismatched_customer_order.id) is not None
    assert db_session.get(OrderItem, mismatched_item.id) is not None
    assert other_conversation.active_draft_json is not None


def test_psid_resolution_is_store_scoped_and_requires_one_conversation(db_session):
    store, customer, conversation, _ = _conversation_fixture(db_session)
    preview = preview_messenger_test_conversation_reset(
        db_session,
        store_id=store.id,
        psid="psid-reset-test",
    )
    assert preview["conversation"]["id"] == str(conversation.id)

    with pytest.raises(ValueError, match="specified store"):
        preview_messenger_test_conversation_reset(
            db_session,
            store_id=uuid.uuid4(),
            psid="psid-reset-test",
        )

    db_session.add(
        Conversation(
            store_id=store.id,
            customer_id=customer.id,
            channel="facebook",
            status=ConversationStatus.CLOSED,
            metadata_json={},
        )
    )
    db_session.flush()
    with pytest.raises(ValueError, match="multiple Messenger conversations"):
        preview_messenger_test_conversation_reset(
            db_session,
            store_id=store.id,
            psid="psid-reset-test",
        )


def test_reset_rejects_an_order_not_listed_for_this_conversation(db_session):
    store, customer, conversation, _ = _conversation_fixture(db_session)
    order, _ = _add_order(
        db_session, store, customer, conversation, OrderStatus.CONFIRMED
    )

    with pytest.raises(ValueError, match="Only listed"):
        reset_messenger_test_conversation(
            db_session,
            store_id=store.id,
            conversation_id=conversation.id,
            delete_unconfirmed_test_order_ids=[order.id],
        )

    assert db_session.get(Order, order.id) is not None
