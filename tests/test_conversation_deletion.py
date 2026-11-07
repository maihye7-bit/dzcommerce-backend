import uuid
from decimal import Decimal

import pytest

from app.core.security import create_access_token
from app.models.ai_usage_event import AIUsageEvent
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.models.human_handoff import HumanHandoff
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.outbound_delivery import OutboundDelivery
from app.models.product import Product, ProductVariant
from app.models.sales_opportunity import SalesOpportunity
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User
from tests.helpers import auth_headers


def _store(db_session, name):
    store = Store(name=name, slug=f"{name.lower().replace(' ', '-')}-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    return store


def _owner(db_session, store):
    user = User(
        email=f"owner-{uuid.uuid4()}@example.com",
        hashed_password="test-hash",
        full_name="Store Owner",
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        StoreUser(store_id=store.id, user_id=user.id, role=StoreRole.OWNER)
    )
    db_session.flush()
    return create_access_token(str(user.id))


def _conversation(db_session, store, customer, *, draft=None):
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status="active",
        active_draft_json=draft,
    )
    db_session.add(conversation)
    db_session.flush()
    message = Message(
        conversation_id=conversation.id,
        role="customer",
        content="Keep or delete this message?",
    )
    db_session.add(message)
    db_session.flush()
    return conversation, message


def _order(db_session, store, customer, conversation, status):
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id if conversation else None,
        status=status,
        subtotal=Decimal("1250"),
        shipping_cost=Decimal("200"),
        total=Decimal("1450"),
    )
    db_session.add(order)
    db_session.flush()
    item = OrderItem(
        order_id=order.id,
        quantity=1,
        unit_price=Decimal("1250"),
    )
    db_session.add(item)
    db_session.flush()
    return order, item


def _commerce_fixture(db_session):
    store = _store(db_session, "Deletion Store")
    token = _owner(db_session, store)
    customer = Customer(store_id=store.id, name="Keep customer")
    db_session.add(customer)
    db_session.flush()
    conversation, message = _conversation(
        db_session,
        store,
        customer,
        draft={"draft_id": str(uuid.uuid4()), "items": [{"quantity": 1}]},
    )
    product = Product(
        store_id=store.id,
        name="Keep product",
        base_price=Decimal("1250"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(product_id=product.id, name="Variant")
    db_session.add(variant)
    db_session.flush()
    inventory = InventoryItem(
        store_id=store.id,
        variant_id=variant.id,
        quantity=7,
    )
    db_session.add(inventory)
    db_session.flush()
    usage = AIUsageEvent(
        store_id=store.id,
        conversation_id=conversation.id,
        provider="test",
        model="local",
        input_tokens=12,
        output_tokens=8,
        total_tokens=20,
        estimated_cost=Decimal("0.001"),
        latency_ms=10,
    )
    delivery = OutboundDelivery(
        conversation_id=conversation.id,
        channel="facebook",
        external_account_id="page-id",
        recipient_external_id="recipient-id",
        payload_type="text",
        payload_json={"text": "queued"},
    )
    handoff = HumanHandoff(
        store_id=store.id,
        conversation_id=conversation.id,
        customer_id=customer.id,
        reason="test",
        summary="test handoff",
    )
    db_session.add_all([usage, delivery, handoff])
    db_session.flush()
    return {
        "store": store,
        "token": token,
        "customer": customer,
        "conversation": conversation,
        "message": message,
        "product": product,
        "inventory": inventory,
        "usage": usage,
        "delivery": delivery,
        "handoff": handoff,
    }


def test_delete_conversation_only_keeps_and_unlinks_orders_and_store_data(
    client, db_session
):
    data = _commerce_fixture(db_session)
    retained_order, retained_item = _order(
        db_session,
        data["store"],
        data["customer"],
        data["conversation"],
        OrderStatus.CONFIRMED,
    )
    conversation_id = data["conversation"].id
    message_id = data["message"].id
    retained_order_id = retained_order.id
    retained_item_id = retained_item.id
    customer_id = data["customer"].id
    product_id = data["product"].id
    inventory_id = data["inventory"].id
    usage_id = data["usage"].id
    delivery_id = data["delivery"].id
    handoff_id = data["handoff"].id

    response = client.delete(
        f"/api/conversations/{conversation_id}",
        headers=auth_headers(data["token"]),
    )

    assert response.status_code == 204
    db_session.expire_all()
    assert db_session.get(Conversation, conversation_id) is None
    assert db_session.get(Message, message_id) is None
    retained_order = db_session.get(Order, retained_order_id)
    assert retained_order is not None
    assert retained_order.conversation_id is None
    assert db_session.get(OrderItem, retained_item_id) is not None
    assert db_session.get(Customer, customer_id) is not None
    assert db_session.get(Product, product_id) is not None
    assert db_session.get(InventoryItem, inventory_id).quantity == 7
    assert db_session.get(AIUsageEvent, usage_id).conversation_id is None
    assert db_session.get(OutboundDelivery, delivery_id) is None
    assert db_session.get(HumanHandoff, handoff_id) is None


def test_delete_conversation_and_orders_deletes_only_its_orders(client, db_session):
    data = _commerce_fixture(db_session)
    draft, draft_item = _order(
        db_session,
        data["store"],
        data["customer"],
        data["conversation"],
        OrderStatus.DRAFT,
    )
    waiting, waiting_item = _order(
        db_session,
        data["store"],
        data["customer"],
        data["conversation"],
        OrderStatus.WAITING_CONFIRMATION,
    )
    confirmed, confirmed_item = _order(
        db_session,
        data["store"],
        data["customer"],
        data["conversation"],
        OrderStatus.CONFIRMED,
    )
    other_conversation, _ = _conversation(
        db_session, data["store"], data["customer"]
    )
    cross_conversation_delivery = OutboundDelivery(
        conversation_id=other_conversation.id,
        fallback_for_id=data["delivery"].id,
        channel="facebook",
        external_account_id="page-id",
        recipient_external_id="recipient-id",
        payload_type="text",
        payload_json={"text": "delivery owned by another conversation"},
    )
    db_session.add(cross_conversation_delivery)
    db_session.flush()
    other_conversation_order, other_conversation_item = _order(
        db_session,
        data["store"],
        data["customer"],
        other_conversation,
        OrderStatus.DRAFT,
    )
    unrelated_order, unrelated_item = _order(
        db_session,
        data["store"],
        data["customer"],
        None,
        OrderStatus.CONFIRMED,
    )
    target_opportunity = SalesOpportunity(
        store_id=data["store"].id,
        customer_id=data["customer"].id,
        opportunity_type="abandoned_draft",
        related_order_id=draft.id,
        notes="Retain opportunity history",
    )
    unrelated_opportunity = SalesOpportunity(
        store_id=data["store"].id,
        customer_id=data["customer"].id,
        opportunity_type="abandoned_draft",
        related_order_id=unrelated_order.id,
    )
    db_session.add_all([target_opportunity, unrelated_opportunity])
    db_session.flush()
    conversation_id = data["conversation"].id
    target_order_ids = (draft.id, waiting.id, confirmed.id)
    target_item_ids = (draft_item.id, waiting_item.id, confirmed_item.id)
    other_conversation_id = other_conversation.id
    cross_delivery_id = cross_conversation_delivery.id
    other_order_id = other_conversation_order.id
    other_item_id = other_conversation_item.id
    unrelated_order_id = unrelated_order.id
    unrelated_item_id = unrelated_item.id
    target_opportunity_id = target_opportunity.id
    unrelated_opportunity_id = unrelated_opportunity.id
    customer_id = data["customer"].id
    product_id = data["product"].id
    inventory_id = data["inventory"].id
    usage_id = data["usage"].id

    response = client.delete(
        f"/api/conversations/{conversation_id}?delete_orders=true",
        headers=auth_headers(data["token"]),
    )

    assert response.status_code == 204
    db_session.expire_all()
    for order_id in target_order_ids:
        assert db_session.get(Order, order_id) is None
    for item_id in target_item_ids:
        assert db_session.get(OrderItem, item_id) is None
    assert db_session.get(Order, other_order_id) is not None
    assert db_session.get(OrderItem, other_item_id) is not None
    assert db_session.get(Order, unrelated_order_id) is not None
    assert db_session.get(OrderItem, unrelated_item_id) is not None
    assert db_session.get(SalesOpportunity, target_opportunity_id).related_order_id is None
    assert (
        db_session.get(SalesOpportunity, unrelated_opportunity_id).related_order_id
        == unrelated_order_id
    )
    assert db_session.get(Customer, customer_id) is not None
    assert db_session.get(Product, product_id) is not None
    assert db_session.get(InventoryItem, inventory_id).quantity == 7
    assert db_session.get(AIUsageEvent, usage_id).conversation_id is None
    assert db_session.get(Conversation, other_conversation_id) is not None
    retained_delivery = db_session.get(OutboundDelivery, cross_delivery_id)
    assert retained_delivery is not None
    assert retained_delivery.fallback_for_id is None


def test_conversation_deletion_is_owner_only_and_store_scoped(client, db_session):
    data = _commerce_fixture(db_session)
    other_store = _store(db_session, "Other Store")
    other_token = _owner(db_session, other_store)

    response = client.delete(
        f"/api/conversations/{data['conversation'].id}",
        headers=auth_headers(other_token),
    )

    assert response.status_code == 404
    assert db_session.get(Conversation, data["conversation"].id) is not None

    staff = User(
        email=f"staff-{uuid.uuid4()}@example.com",
        hashed_password="test-hash",
        full_name="Store Staff",
    )
    db_session.add(staff)
    db_session.flush()
    db_session.add(
        StoreUser(
            store_id=data["store"].id,
            user_id=staff.id,
            role=StoreRole.STAFF,
        )
    )
    db_session.flush()
    staff_response = client.delete(
        f"/api/conversations/{data['conversation'].id}",
        headers=auth_headers(create_access_token(str(staff.id))),
    )

    assert staff_response.status_code == 403
    assert db_session.get(Conversation, data["conversation"].id) is not None


def test_conversation_deletion_returns_404_for_missing_id_and_422_for_invalid_id(
    client, db_session
):
    data = _commerce_fixture(db_session)
    headers = auth_headers(data["token"])

    missing = client.delete(
        f"/api/conversations/{uuid.uuid4()}",
        headers=headers,
    )
    invalid = client.delete(
        "/api/conversations/not-a-uuid",
        headers=headers,
    )

    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_conversation_deletion_rolls_back_all_changes_on_failure(
    client, db_session, monkeypatch
):
    from app.api import conversations as conversations_api

    data = _commerce_fixture(db_session)
    order, item = _order(
        db_session,
        data["store"],
        data["customer"],
        data["conversation"],
        OrderStatus.DRAFT,
    )
    conversation_id = data["conversation"].id
    message_id = data["message"].id
    order_id = order.id
    item_id = item.id
    usage_id = data["usage"].id
    db_session.commit()
    original_delete = conversations_api.delete_conversation_records

    def fail_after_deleting_records(db, conversation, *, delete_orders):
        original_delete(db, conversation, delete_orders=delete_orders)
        raise RuntimeError("forced deletion failure")

    monkeypatch.setattr(
        conversations_api,
        "delete_conversation_records",
        fail_after_deleting_records,
    )

    with pytest.raises(RuntimeError, match="forced deletion failure"):
        client.delete(
            f"/api/conversations/{conversation_id}?delete_orders=true",
            headers=auth_headers(data["token"]),
        )

    db_session.expire_all()
    assert db_session.get(Conversation, conversation_id) is not None
    assert db_session.get(Message, message_id) is not None
    assert db_session.get(Order, order_id) is not None
    assert db_session.get(OrderItem, item_id) is not None
    assert db_session.get(AIUsageEvent, usage_id).conversation_id == conversation_id


def test_conversation_deletion_tolerates_unmigrated_optional_tables(
    client, db_session, caplog
):
    data = _commerce_fixture(db_session)
    order, item = _order(
        db_session,
        data["store"],
        data["customer"],
        data["conversation"],
        OrderStatus.DRAFT,
    )
    conversation_id = data["conversation"].id
    order_id = order.id
    item_id = item.id
    HumanHandoff.__table__.drop(db_session.connection())
    SalesOpportunity.__table__.drop(db_session.connection())

    response = client.delete(
        f"/api/conversations/{conversation_id}?delete_orders=true",
        headers=auth_headers(data["token"]),
    )

    assert response.status_code == 204
    assert db_session.get(Conversation, conversation_id) is None
    assert db_session.get(Order, order_id) is None
    assert db_session.get(OrderItem, item_id) is None
    assert "table=human_handoffs" in caplog.text
    assert "table=sales_opportunities" in caplog.text
