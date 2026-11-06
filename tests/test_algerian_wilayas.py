import uuid
from decimal import Decimal

import pytest

from app.agent.conversation_engine import ConversationEngine
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store
from app.services.algerian_wilayas import (
    WILAYAS,
    find_wilaya,
    normalize_wilaya_text,
    resolve_delivery_wilaya,
)


def test_reference_has_all_58_unique_wilaya_codes():
    codes = [wilaya.code for wilaya in WILAYAS]

    assert len(WILAYAS) == 58
    assert len(set(codes)) == 58
    assert set(codes) == {f"{number:02d}" for number in range(1, 59)}
    assert all(wilaya.name_ar and wilaya.name_fr for wilaya in WILAYAS)


@pytest.mark.parametrize(
    ("name", "expected_code"),
    [
        ("قالمة", "24"),
        ("قلمة", "24"),
        ("ولاية قالمة", "24"),
        ("Guelma", "24"),
        ("Aïn Defla", "44"),
        ("Ain Defla", "44"),
        ("وهران", "31"),
        ("Oran", "31"),
        ("El M'Ghair", "57"),
        ("المغير", "57"),
    ],
)
def test_wilaya_matching_handles_arabic_french_and_aliases(name, expected_code):
    match = find_wilaya(name)

    assert match is not None
    assert match.code == expected_code


def test_wilaya_normalization_is_separate_and_store_policy_is_preserved():
    assert normalize_wilaya_text("قَالْمَة") == normalize_wilaya_text("قالمة")
    assert resolve_delivery_wilaya("ولاية قالمة", "Guelma").name_ar == "قالمة"
    assert resolve_delivery_wilaya("ولاية قالمة", "Oran") is None
    assert resolve_delivery_wilaya("ولاية غير معروفة", None) is None


@pytest.mark.asyncio
async def test_canonical_wilaya_persists_from_delivery_capture_to_confirmed_order(
    db_session,
):
    store = Store(
        name="Wilaya order store",
        slug=f"wilaya-order-{uuid.uuid4()}",
        served_wilayas="Guelma",
    )
    db_session.add(store)
    db_session.flush()
    customer = Customer(store_id=store.id, name="Wilaya customer")
    db_session.add(customer)
    db_session.flush()
    product = Product(
        store_id=store.id,
        name="Test product",
        base_price=Decimal("1000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="Default",
        price_adjustment=Decimal("0"),
        attributes_json={},
    )
    db_session.add(variant)
    db_session.flush()
    db_session.add(
        InventoryItem(store_id=store.id, variant_id=variant.id, quantity=2)
    )
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="facebook",
        status=ConversationStatus.ACTIVE,
    )
    db_session.add(conversation)
    db_session.flush()

    _phone, wilaya = ConversationEngine._extract_delivery_details(
        "ولاية قلمة",
        store.served_wilayas,
    )
    assert wilaya == "قالمة"
    draft_id = str(uuid.uuid4())
    conversation.active_draft_json = {
        "draft_id": draft_id,
        "items": [{"variant_id": str(variant.id), "quantity": 1}],
        "shipping_info": {"phone": "0550000000", "wilaya": wilaya},
    }
    conversation.metadata_json = {
        "confirmation_pending": {"draft_id": draft_id},
    }
    db_session.commit()

    result = await ConfirmOrderTool().execute(
        store_id=store.id,
        arguments={},
        context={
            "db": db_session,
            "conversation_id": conversation.id,
            "customer_id": customer.id,
        },
    )
    db_session.commit()

    order = (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .one()
    )
    assert result.success
    assert order.status == OrderStatus.CONFIRMED
    assert order.wilaya == "قالمة"
