"""
Focused root-cause repair tests — Shipping Data Contract & Draft Idempotency.

Covers:
1. Tool schema + validation accept canonical shipping fields.
2. municipality / commune aliases normalize correctly.
3. Same items + new phone preserves previous wilaya.
4. Same items + new wilaya preserves previous phone.
5. Same items + municipality/address merges without erasing other fields.
6. Failed draft creation does not lose validated shipping data.
7. A later conversation turn can recover saved shipping data.
8. Missing phone or wilaya prevents final confirmation.
9. A modified draft invalidates old confirmation.
10. A repeated successful confirmation does not create a second order.
11. Multi-turn integration test.
"""
import asyncio
import hashlib
import json
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent.conversation_engine import ConversationEngine
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.update_order_draft import UpdateOrderDraftTool
from app.database import Base
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store
from app.services.exceptions import ValidationError
from app.services.order_draft_service import save_draft_safe, _normalize_canonical_shipping


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def factory(tmp_path):
    engine = create_engine(URL.create("sqlite", database=str(tmp_path / "shipping.sqlite")))
    Base.metadata.create_all(bind=engine)
    factory_cls = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory_cls
    finally:
        engine.dispose()


def seed(factory):
    with factory.begin() as db:
        store = Store(name="Test Store", slug=f"ts-{uuid.uuid4()}")
        db.add(store)
        db.flush()
        customer = Customer(store_id=store.id, name="Test Customer")
        db.add(customer)
        db.flush()
        conv = Conversation(
            store_id=store.id,
            customer_id=customer.id,
            channel="test",
            status=ConversationStatus.ACTIVE,
            metadata_json={"variant_index_map": {}},
            active_draft_json=None,
        )
        db.add(conv)
        db.flush()
        product = Product(store_id=store.id, name="Test Product", base_price=Decimal("100"), is_active=True)
        db.add(product)
        db.flush()
        variant = ProductVariant(product_id=product.id, name="Option A", price_adjustment=Decimal("10"))
        db.add(variant)
        db.flush()
        db.add(InventoryItem(store_id=store.id, variant_id=variant.id, quantity=10))
        conv.metadata_json = {"variant_index_map": {"1": str(variant.id)}}
        return (store.id, conv.id, variant.id)


def make_context(session, store_id, conv_id):
    conv = session.query(Conversation).filter(Conversation.id == conv_id).one()
    return {
        "db": session,
        "store_id": store_id,
        "conversation_id": conv_id,
        "customer_id": conv.customer_id,
        "channel": "test",
    }


def get_draft(session, conv_id):
    conv = session.query(Conversation).filter(Conversation.id == conv_id).first()
    return conv.active_draft_json if conv else None


# ---------------------------------------------------------------------------
# 1. Canonical shipping fields accepted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fields",
    [
        {"phone": "0555123456", "wilaya": "الجزائر"},
        {"phone": "0555123456", "wilaya": "Oran", "municipality": "Oran"},
        {"phone": "0555123456", "wilaya": "Constantine", "address": "1 Rue Test"},
        {"phone": "0555123456", "wilaya": "Blida", "first_name": "Ahmed"},
        {"phone": "0555123456", "wilaya": "Setif", "last_name": "Boudiaf"},
        {"phone": "0555123456", "wilaya": "Annaba", "commune": "Annaba Centre"},
        {
            "phone": "0770001111",
            "wilaya": "Batna",
            "municipality": "Batna Ville",
            "commune": "Batna",
            "address": "123 Example St",
            "first_name": "Fatima",
            "last_name": "Zahra",
        },
    ],
)
def test_valid_shipping_fields_accepted(factory, fields):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        result = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info=fields,
        )
    assert result["shipping_info"]
    for key in ("phone", "wilaya"):
        assert result["shipping_info"].get(key) == fields[key]
    for key in ("municipality", "commune", "address", "first_name", "last_name"):
        if key in fields:
            assert result["shipping_info"].get(key) == fields[key]


# ---------------------------------------------------------------------------
# 2. municipality / commune aliases normalize correctly
# ---------------------------------------------------------------------------

def test_municipality_and_commune_both_persist(factory):
    store_id, conv_id, _ = seed(factory)
    info = {
        "phone": "0555123456",
        "wilaya": "Sétif",
        "municipality": "Sétif Ville",
        "commune": "Sétif Commune",
    }
    with factory.begin() as db:
        result = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info=info,
        )
    assert result["shipping_info"]["municipality"] == "Sétif Ville"
    assert result["shipping_info"]["commune"] == "Sétif Commune"


def test_unknown_shipping_keys_dropped_by_normalize():
    raw = {"phone": "0555123456", "wilaya": "Tizi Ouzou", "extra_field": "boom"}
    normalized = _normalize_canonical_shipping(raw)
    assert "phone" in normalized
    assert "wilaya" in normalized
    assert "extra_field" not in normalized


# ---------------------------------------------------------------------------
# 3. Same items + new phone preserves previous wilaya
# ---------------------------------------------------------------------------

def test_same_item_new_phone_preserves_wilaya(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        r1 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555000000", "wilaya": "Algiers"},
        )
        assert r1["shipping_info"]["wilaya"] == "Algiers"
        r2 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555999999"},
        )
    assert r2["shipping_info"]["phone"] == "0555999999"
    assert r2["shipping_info"]["wilaya"] == "Algiers"


# ---------------------------------------------------------------------------
# 4. Same items + new wilaya preserves previous phone
# ---------------------------------------------------------------------------

def test_same_item_new_wilaya_preserves_phone(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        r1 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555111111", "wilaya": "Oran"},
        )
        r2 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"wilaya": "Constantine"},
        )
    assert r2["shipping_info"]["phone"] == "0555111111"
    assert r2["shipping_info"]["wilaya"] == "Constantine"


# ---------------------------------------------------------------------------
# 5. Same items + municipality/address merges without erasing other fields
# ---------------------------------------------------------------------------

def test_same_item_merge_municipality_address(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        r1 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555222222", "wilaya": "Bejaia", "first_name": "Karim"},
        )
        r2 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"municipality": "Bejaia Centre", "address": "5 Rue Mohamed"},
        )
    info = r2["shipping_info"]
    assert info["phone"] == "0555222222"
    assert info["wilaya"] == "Bejaia"
    assert info["first_name"] == "Karim"
    assert info["municipality"] == "Bejaia Centre"
    assert info["address"] == "5 Rue Mohamed"


# ---------------------------------------------------------------------------
# 6. Failed draft creation does not lose validated shipping data
# ---------------------------------------------------------------------------

def test_failed_draft_does_not_lose_existing_shipping(factory):
    """Case B raises and leaves the existing draft untouched."""
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        r1 = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555333333", "wilaya": "Djelfa"},
        )
        assert r1["shipping_info"]["phone"] == "0555333333"
        product_b = Product(store_id=store_id, name="Other", base_price=Decimal("50"), is_active=True)
        db.add(product_b); db.flush()
        variant_b = ProductVariant(product_id=product_b.id, name="B", price_adjustment=Decimal("0"))
        db.add(variant_b); db.flush()
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        conv.metadata_json["variant_index_map"]["2"] = str(variant_b.id)
        db.flush()
        with pytest.raises(ValidationError):
            save_draft_safe(
                db=db, conversation_id=conv_id, store_id=store_id,
                items=[{"variant_index": 2, "quantity": 1}],
                shipping_info={"phone": "NEW"},
            )
    with factory.begin() as db:
        draft = get_draft(db, conv_id)
        assert draft is not None
        assert draft["shipping_info"]["phone"] == "0555333333"
        assert draft["shipping_info"]["wilaya"] == "Djelfa"


# ---------------------------------------------------------------------------
# 7. Later conversation turn recovers saved shipping data via metadata
# ---------------------------------------------------------------------------

def test_metadata_shipping_survives_after_draft_cleared(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        conv.metadata_json = {
            "shipping_info": {"phone": "0555444444", "wilaya": "Tlemcen"},
            "variant_index_map": conv.metadata_json.get("variant_index_map", {}),
        }
        conv.active_draft_json = None
    state = ConversationEngine._normalize_current_state(
        db.query(Conversation).filter(Conversation.id == conv_id).one(), store_id
    )
    assert state["shipping_info"]["phone"] == "0555444444"
    assert state["shipping_info"]["wilaya"] == "Tlemcen"


# ---------------------------------------------------------------------------
# 8. Missing phone or wilaya prevents final confirmation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_fails_without_phone(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"wilaya": "Algiers"},
        )
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        conv.metadata_json["confirmation_pending"] = {"draft_id": conv.active_draft_json["draft_id"]}
    ctx = make_context(
        db, store_id, conv_id,
    )
    result = await ConfirmOrderTool().execute(store_id, {}, ctx)
    assert not result.success
    assert result.error_code == "SHIPPING_INFO_REQUIRED"


@pytest.mark.asyncio
async def test_confirm_fails_without_wilaya(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555555555"},
        )
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        conv.metadata_json["confirmation_pending"] = {"draft_id": conv.active_draft_json["draft_id"]}
    ctx = make_context(
        db, store_id, conv_id,
    )
    result = await ConfirmOrderTool().execute(store_id, {}, ctx)
    assert not result.success
    assert result.error_code == "SHIPPING_INFO_REQUIRED"


# ---------------------------------------------------------------------------
# 9. Modified draft invalidates old confirmation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modified_draft_invalidates_old_confirmation(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555666666", "wilaya": "Constantine"},
        )
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        conv.metadata_json["confirmation_pending"] = {"draft_id": "some-other-draft-id"}
    ctx = make_context(
        db, store_id, conv_id,
    )
    result = await ConfirmOrderTool().execute(store_id, {}, ctx)
    assert not result.success
    assert result.error_code == "CONFIRMATION_NOT_PENDING"


# ---------------------------------------------------------------------------
# 10. Repeated successful confirmation creates exactly one order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repeated_confirmation_no_duplicate_order(factory):
    store_id, conv_id, variant_id = seed(factory)
    with factory.begin() as db:
        save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 2}],
            shipping_info={"phone": "0555777777", "wilaya": "Annaba"},
        )
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        fp_data = {
            "items": conv.active_draft_json["items"],
            "shipping_info": conv.active_draft_json["shipping_info"],
        }
        fp = hashlib.sha256(json.dumps(fp_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        conv.metadata_json["confirmation_pending"] = {
            "draft_id": conv.active_draft_json["draft_id"],
            "fingerprint": fp,
            "status": "awaiting",
        }
        conv.metadata_json["last_question_type"] = "ORDER_CONFIRMATION"
        ctx = make_context(db, store_id, conv_id)
        r1 = await ConfirmOrderTool().execute(store_id, {}, ctx)
    assert r1.success
    with factory.begin() as db:
        count = db.query(Order).filter(Order.conversation_id == conv_id).count()
        inv = db.query(InventoryItem).filter(InventoryItem.variant_id == variant_id).first()
    assert count == 1
    assert inv.quantity == 8  # 10 - 2


# ---------------------------------------------------------------------------
# 11. Realistic multi-turn integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_turn_integration_customer_selects_then_confirms(factory):
    """
    Simulates:
      - Customer selects product+variant -> draft created
      - Customer provides phone+wilaya together
      - Customer changes phone only
      - Confirmation succeeds
      - Exactly one order with latest shipping data
    """
    store_id, conv_id, variant_id = seed(factory)

    async def run(tool_cls, args):
        with factory.begin() as db:
            ctx = make_context(db, store_id, conv_id)
            tool = tool_cls() if isinstance(tool_cls, type) else tool_cls
            return await tool.execute(store_id, args, ctx)

    # Step 1: Create draft
    r = await run(CreateOrderDraftTool(), {"items": [{"variant_index": 1, "quantity": 1}]})
    assert r.success, f"Draft creation failed: {r.error}"

    with factory.begin() as db:
        draft = get_draft(db, conv_id)
        assert draft["items"][0]["quantity"] == 1
        assert draft["shipping_info"] == {}

    # Step 2: Add phone + wilaya
    r = await run(UpdateOrderDraftTool(), {
        "action": "set_shipping",
        "shipping_info": {"phone": "0555888888", "wilaya": "Batna"},
    })
    assert r.success, f"Shipping update failed: {r.error}"

    with factory.begin() as db:
        draft = get_draft(db, conv_id)
        assert draft["shipping_info"]["phone"] == "0555888888"
        assert draft["shipping_info"]["wilaya"] == "Batna"

    # Step 3: Change phone only — wilaya must persist
    r = await run(UpdateOrderDraftTool(), {
        "action": "set_shipping",
        "shipping_info": {"phone": "0555999999"},
    })
    assert r.success, f"Phone change failed: {r.error}"

    with factory.begin() as db:
        draft = get_draft(db, conv_id)
        assert draft["shipping_info"]["phone"] == "0555999999"
        assert draft["shipping_info"]["wilaya"] == "Batna"

    # Step 4: Set up pending confirmation
    with factory.begin() as db:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        draft = conv.active_draft_json
        fp_data = {
            "items": draft["items"],
            "shipping_info": draft["shipping_info"],
        }
        fp = hashlib.sha256(json.dumps(fp_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        conv.metadata_json["confirmation_pending"] = {
            "draft_id": draft["draft_id"],
            "fingerprint": fp,
            "status": "awaiting",
        }
        conv.metadata_json["last_question_type"] = "ORDER_CONFIRMATION"

    # Step 5: Confirm
    r = await run(ConfirmOrderTool(), {})
    assert r.success, f"Confirmation failed: {r.error}"
    assert r.data["status"] == "confirmed"

    # Step 6: Verify exactly one order with correct shipping, stock deducted once
    with factory.begin() as db:
        orders = db.query(Order).filter(Order.conversation_id == conv_id).all()
        assert len(orders) == 1
        order = orders[0]
        assert order.status.value == "confirmed"
        assert order.wilaya == "Batna"
        shipping = json.loads(order.shipping_address) if isinstance(order.shipping_address, str) else (order.shipping_address or {})
        assert shipping.get("phone") == "0555999999"
        assert shipping.get("wilaya") == "Batna"
        inv = db.query(InventoryItem).filter(InventoryItem.variant_id == variant_id).first()
        assert inv.quantity == 9  # 10 - 1

        # Re-confirm should not create a second order
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        assert conv.active_draft_json is None
        ctx2 = make_context(db, store_id, conv_id)
        r2 = await ConfirmOrderTool().execute(store_id, {}, ctx2)
        assert r2.success  # returns already-confirmed message
        assert db.query(Order).filter(Order.conversation_id == conv_id).count() == 1
        inv = db.query(InventoryItem).filter(InventoryItem.variant_id == variant_id).first()
        assert inv.quantity == 9  # no additional deduction
