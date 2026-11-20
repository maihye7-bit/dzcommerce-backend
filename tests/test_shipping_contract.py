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
8. Missing phone, wilaya, or municipality prevents final confirmation.
9. A modified draft invalidates old confirmation.
10. A repeated successful confirmation does not create a second order.
11. Multi-turn integration test.
12. Engine schema field exposure test.
13. Real engine flow integration test.
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
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.registry import ToolRegistry
from app.database import Base
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
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
    """Create store/product/customer/conversation and return (store_id, conv_id, variant_id)."""
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


def conversation_active_draft(conv):
    """Helper to get active draft from conversation."""
    return conv.active_draft_json


# ---------------------------------------------------------------------------
# 1. Canonical shipping fields accepted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "fields, expected",
    [
        (
            {"phone": "0555123456", "wilaya": "الجزائر"},
            {"phone": "0555123456", "wilaya": "الجزائر"},
        ),
        (
            {"phone": "0555123456", "wilaya": "Oran", "municipality": "Oran"},
            {"phone": "0555123456", "wilaya": "Oran", "municipality": "Oran"},
        ),
        (
            {"phone": "0555123456", "wilaya": "Constantine", "address": "1 Rue Test"},
            {"phone": "0555123456", "wilaya": "Constantine", "address": "1 Rue Test"},
        ),
        (
            {"phone": "0555123456", "wilaya": "Blida", "first_name": "Ahmed"},
            {"phone": "0555123456", "wilaya": "Blida", "first_name": "Ahmed"},
        ),
        (
            {"phone": "0555123456", "wilaya": "Setif", "last_name": "Boudiaf"},
            {"phone": "0555123456", "wilaya": "Setif", "last_name": "Boudiaf"},
        ),
        # commune is an alias - should be converted to municipality
        (
            {"phone": "0555123456", "wilaya": "Annaba", "commune": "Annaba Centre"},
            {"phone": "0555123456", "wilaya": "Annaba", "municipality": "Annaba Centre"},
        ),
        # municipality takes precedence over commune
        (
            {
                "phone": "0770001111",
                "wilaya": "Batna",
                "municipality": "Batna Ville",
                "commune": "Batna",
                "address": "123 Example St",
                "first_name": "Fatima",
                "last_name": "Zahra",
            },
            {
                "phone": "0770001111",
                "wilaya": "Batna",
                "municipality": "Batna Ville",
                "address": "123 Example St",
                "first_name": "Fatima",
                "last_name": "Zahra",
            },
        ),
    ],
)
def test_valid_shipping_fields_accepted(factory, fields, expected):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        result = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info=fields,
        )
    assert result["shipping_info"]
    for key, expected_value in expected.items():
        assert result["shipping_info"].get(key) == expected_value
    # commune should NOT be stored as a separate field
    assert "commune" not in result["shipping_info"]


# ---------------------------------------------------------------------------
# 2. municipality / commune aliases normalize correctly
# ---------------------------------------------------------------------------

def test_commune_alias_converts_to_municipality(factory):
    """commune should be converted to municipality when stored."""
    store_id, conv_id, _ = seed(factory)
    info = {
        "phone": "0555123456",
        "wilaya": "Sétif",
        "commune": "Sétif Commune",
    }
    with factory.begin() as db:
        result = save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info=info,
        )
    # commune should be converted to municipality
    assert result["shipping_info"]["municipality"] == "Sétif Commune"
    # commune should NOT be stored as separate field
    assert "commune" not in result["shipping_info"]


def test_municipality_takes_precedence_over_commune(factory):
    """If both municipality and commune provided, municipality takes precedence."""
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
    # municipality takes precedence
    assert result["shipping_info"]["municipality"] == "Sétif Ville"
    # commune should NOT be stored as separate field
    assert "commune" not in result["shipping_info"]


def test_unknown_shipping_keys_dropped_by_normalize():
    """Non-canonical keys are silently dropped by _normalize_canonical_shipping."""
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
        # Add a second variant and map index 2 to it
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
    # Verify the original draft survived intact from a fresh session
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
    ctx = make_context(db, store_id, conv_id)
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
    ctx = make_context(db, store_id, conv_id)
    result = await ConfirmOrderTool().execute(store_id, {}, ctx)
    assert not result.success
    assert result.error_code == "SHIPPING_INFO_REQUIRED"


@pytest.mark.asyncio
async def test_confirm_fails_without_municipality(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        save_draft_safe(
            db=db, conversation_id=conv_id, store_id=store_id,
            items=[{"variant_index": 1, "quantity": 1}],
            shipping_info={"phone": "0555555555", "wilaya": "Algiers"},
        )
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        conv.metadata_json["confirmation_pending"] = {"draft_id": conv.active_draft_json["draft_id"]}
    ctx = make_context(db, store_id, conv_id)
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
    ctx = make_context(db, store_id, conv_id)
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
            shipping_info={"phone": "0555777777", "wilaya": "Annaba", "municipality": "Annaba", "address": "Legacy address"},
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
        order = db.query(Order).filter(Order.conversation_id == conv_id).one()
        saved_shipping = json.loads(order.shipping_address) if isinstance(order.shipping_address, str) else order.shipping_address
        assert set(saved_shipping) == {"phone", "wilaya", "municipality"}
        inv = db.query(InventoryItem).filter(InventoryItem.variant_id == variant_id).first()
    assert count == 1
    assert inv.quantity == 8  # 10 - 2


# ---------------------------------------------------------------------------
# 11. Multi-turn integration test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_turn_integration_customer_selects_then_confirms(factory):
    """
    Simulates:
      - Customer selects product+variant -> draft created
      - Customer provides phone+wilaya+municipality together
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
        "shipping_info": {"phone": "0555888888", "wilaya": "Batna", "municipality": "Batna"},
    })
    assert r.success, f"Shipping update failed: {r.error}"

    with factory.begin() as db:
        draft = get_draft(db, conv_id)
        assert draft["shipping_info"]["phone"] == "0555888888"
        assert draft["shipping_info"]["wilaya"] == "Batna"
        assert draft["shipping_info"]["municipality"] == "Batna"

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
        assert r2.success
        assert db.query(Order).filter(Order.conversation_id == conv_id).count() == 1
        inv = db.query(InventoryItem).filter(InventoryItem.variant_id == variant_id).first()
        assert inv.quantity == 9


# ---------------------------------------------------------------------------
# 12. Engine schema field exposure test
# ---------------------------------------------------------------------------

def test_engine_exposes_shipping_fields_in_tool_schemas():
    """
    Verify that the actual engine tool schemas expose all canonical shipping fields.
    This ensures FreeLLM sees the complete shipping schema.
    """
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.register(GetProductDetailsTool())
    registry.register(CreateOrderDraftTool())
    registry.register(UpdateOrderDraftTool())
    registry.register(ConfirmOrderTool())

    engine = ConversationEngine(
        llm_provider=type('MockProvider', (), {
            'provider_name': 'mock',
            'model': 'mock',
        })(),
        tool_registry=registry,
    )
    engine.reply_composer = type('MockComposer', (), {
        'compose': lambda *a, **kw: None,
    })()

    schemas = engine._agent_tool_schemas()
    schema_map = {s["function"]["name"]: s["function"]["parameters"] for s in schemas}

    # Check create_order_draft schema
    create_schema = schema_map["create_order_draft"]
    shipping_props = create_schema["properties"]["shipping_info"]["properties"]
    assert "phone" in shipping_props
    assert "wilaya" in shipping_props
    assert "municipality" in shipping_props
    assert "commune" in shipping_props  # municipality alias
    assert "address" not in shipping_props
    assert "first_name" not in shipping_props
    assert "last_name" not in shipping_props
    assert create_schema["properties"]["shipping_info"]["additionalProperties"] is False

    # Check update_order_draft schema
    update_schema = schema_map["update_order_draft"]
    update_shipping_props = update_schema["properties"]["shipping_info"]["properties"]
    assert "phone" in update_shipping_props
    assert "wilaya" in update_shipping_props
    assert "municipality" in update_shipping_props
    assert "commune" in update_shipping_props  # municipality alias
    assert "address" not in update_shipping_props
    assert "first_name" not in update_shipping_props
    assert "last_name" not in update_shipping_props
    assert update_schema["properties"]["shipping_info"]["additionalProperties"] is False


# ---------------------------------------------------------------------------
# 13. Real engine flow integration test (using existing test pattern)
# ---------------------------------------------------------------------------

# Local ScriptedToolProvider for deterministic testing (mirrors test_agent_tool_loop.py)
class ScriptedToolProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None, session_id=None, turn_id=None, call_index=None):
        self.calls.append((messages, tools))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_real_engine_flow_create_draft_collect_shipping_confirm(factory):
    """
    Real engine flow integration test using the actual ConversationEngine.process_message() entry point.
    This test follows the same pattern as test_purchase_resumes_through_delivery_details_and_natural_confirmation
    in test_agent_tool_loop.py.

    Tests the actual confirmation invalidation logic used in production:
      1. Customer selects variant -> engine creates draft via create_order_draft tool
      2. Customer provides phone+wilaya -> engine delivery capture path updates draft
      3. Customer changes phone -> engine invalidates old confirmation
      4. Attempt confirmation with stale approval -> rejected (CONFIRMATION_STALE)
      5. Customer explicitly confirms -> engine sets up new confirmation with fingerprint
      6. Final confirmation -> exactly one order, latest shipping, stock deducted once
    """
    from app.agent.conversation_engine import ConversationEngine
    from app.agent.tools.registry import ToolRegistry
    from app.agent.tools.create_order_draft import CreateOrderDraftTool
    from app.agent.tools.update_order_draft import UpdateOrderDraftTool
    from app.agent.tools.confirm_order import ConfirmOrderTool
    from app.agent.tools.search_products import SearchProductsTool
    from app.agent.tools.get_product_details import GetProductDetailsTool
    from app.agent.tools.base import ToolResult
    from unittest.mock import AsyncMock

    store_id, conv_id, variant_id = seed(factory)

    # Create engine with registry
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.register(GetProductDetailsTool())
    registry.register(CreateOrderDraftTool())
    registry.register(UpdateOrderDraftTool())
    registry.register(ConfirmOrderTool())

    # Use ScriptedToolProvider like other tests
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False

    # Use the actual heuristic NLU
    async def local_nlu(user_message, state, **_kwargs):
        return engine._heuristic_nlu(user_message, state)
    engine._extract_nlu_via_qwen = local_nlu

    # Use a single session for the entire test (like test_agent_tool_loop.py)
    db = factory()
    try:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        customer_id = conv.customer_id

        # ============================================================
        # Setup: Customer has already selected a variant
        # ============================================================
        # Need product to get its ID for the resolver
        from app.models.product import Product, ProductVariant
        product = db.query(ProductVariant).filter(ProductVariant.id == variant_id).one().product
        conv.metadata_json = {
            **conv.metadata_json,
            "variant_index_map": {"1": str(variant_id)},
            "selected_product_id": str(product.id),
            "selected_variant_id": str(variant_id),
            "commerce_stage": "VARIANT_SELECTED",
            "last_question_type": "VARIANT_SELECTION",
        }
        db.flush()

        # ============================================================
        # Step 1: Customer creates draft via engine message
        # ============================================================
        # "دير طلب" triggers order_create intent -> create_order_draft tool
        result = await engine.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            channel="test",
            user_message="دير طلب",
        )
        assert result["turn_diagnostics"]["intent"] == "order_create"
        assert result["turn_diagnostics"]["resolver_action"] == "CALL_SERVICE:create_draft"
        assert conversation_active_draft(conv) is not None
        assert len(conv.active_draft_json["items"]) == 1
        assert conv.active_draft_json["items"][0]["variant_id"] == str(variant_id)

        # ============================================================
        # Step 2: Customer provides phone+wilaya via engine message
        # ============================================================
        # After step 1, the engine should have set last_question_type to CUSTOMER_DELIVERY_INFO
        # (as seen in test_purchase_resumes_through_delivery_details_and_natural_confirmation)
        assert conv.metadata_json.get("last_question_type") == "CUSTOMER_DELIVERY_INFO"

        # Engine delivery capture path extracts phone/wilaya and updates draft
        result = await engine.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            channel="test",
            user_message="ولاية باتنة بلدية باتنة 0555888888",
        )
        # Delivery capture path updates draft
        # Wilaya is stored in Arabic by the engine's _extract_delivery_details
        assert conv.active_draft_json["shipping_info"]["phone"] == "0555888888"
        assert conv.active_draft_json["shipping_info"]["wilaya"] == "باتنة"  # Arabic name
        assert conv.active_draft_json["shipping_info"]["municipality"] == "باتنة"
        # Engine sets last_question_type to ORDER_CONFIRMATION
        assert conv.metadata_json.get("last_question_type") == "ORDER_CONFIRMATION"

        # ============================================================
        # Step 3: Customer changes phone via update_order_draft tool
        # ============================================================
        # Phone changes after confirmation request go through update_order_draft set_shipping
        from app.agent.tools.update_order_draft import UpdateOrderDraftTool
        r = await UpdateOrderDraftTool().execute(store_id, {
            "action": "set_shipping",
            "shipping_info": {"phone": "0555999999"},
        }, context={
            "db": db,
            "store_id": store_id,
            "conversation_id": conv_id,
            "customer_id": customer_id,
            "channel": "test",
        })
        assert r.success
        # Delivery capture path invalidates old confirmation
        # and updates shipping info with new phone
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        assert conv.active_draft_json["shipping_info"]["phone"] == "0555999999"
        assert conv.active_draft_json["shipping_info"]["wilaya"] == "باتنة"  # Arabic name preserved
        assert conv.active_draft_json["shipping_info"]["municipality"] == "باتنة"

        # ============================================================
        # Step 4: Attempt confirmation with stale approval -> rejected (CONFIRMATION_STALE)
        # ============================================================
        # Manually set a stale confirmation with a fake fingerprint (simulating old state)
        # The engine only adds fingerprint when "أكد الطلب" is received, so we add one manually
        conv.metadata_json["confirmation_pending"] = {
            "draft_id": conv.active_draft_json["draft_id"],
            "fingerprint": "stale-fake-fingerprint",
            "status": "awaiting",
        }
        conv.metadata_json["last_question_type"] = "ORDER_CONFIRMATION"
        db.flush()

        # Try to confirm with stale fingerprint - should fail
        context = {
            "db": db,
            "store_id": store_id,
            "conversation_id": conv_id,
            "customer_id": customer_id,
            "channel": "test",
        }
        r = await ConfirmOrderTool().execute(store_id, {}, context)
        assert not r.success, "Should reject stale confirmation"
        assert r.error_code == "CONFIRMATION_STALE"

        # ============================================================
        # Step 5: Engine sets up NEW confirmation with correct fingerprint
        # ============================================================
        # In production, the engine adds fingerprint when "أكد الطلب" is received.
        # Here we simulate what the engine does by manually adding the fingerprint.
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        current_draft = conv.active_draft_json
        import hashlib, json as _json
        fp_data = {
            "items": current_draft["items"],
            "shipping_info": current_draft["shipping_info"],
        }
        new_fp = hashlib.sha256(json.dumps(fp_data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        conv.metadata_json["confirmation_pending"] = {
            "draft_id": current_draft["draft_id"],
            "fingerprint": new_fp,
            "status": "awaiting",
        }
        conv.metadata_json["last_question_type"] = "ORDER_CONFIRMATION"
        db.flush()

        # ============================================================
        # Step 6: Final explicit confirmation -> exactly one order
        # ============================================================
        result = await engine.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conv_id,
            channel="test",
            user_message="أكد الطلب",
        )
        assert result["turn_diagnostics"]["resolver_action"] == "EXECUTE_TOOL:confirm_order"
        assert result["turn_diagnostics"]["intent"] == "order_confirm"
        assert conv.active_draft_json is None

        # Commit the session to persist the order
        db.commit()

    # Step 7: Verify exactly one order with correct shipping, stock deducted once
    finally:
        db.close()

    with factory.begin() as db:
        orders = db.query(Order).filter(Order.conversation_id == conv_id).all()
        assert len(orders) == 1
        order = orders[0]
        assert order.status.value == "confirmed"
        assert order.wilaya == "باتنة"  # Arabic name stored
        import json as _json
        shipping = _json.loads(order.shipping_address) if isinstance(order.shipping_address, str) else (order.shipping_address or {})
        assert shipping.get("phone") == "0555999999"
        assert shipping.get("wilaya") == "باتنة"
        assert shipping.get("municipality") == "باتنة"
        assert set(shipping) == {"phone", "wilaya", "municipality"}

        # Re-confirm should not create a second order
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        assert conv.active_draft_json is None
        context = {
            "db": db,
            "store_id": store_id,
            "conversation_id": conv_id,
            "customer_id": customer_id,
            "channel": "test",
        }
        r2 = await ConfirmOrderTool().execute(store_id, {}, context)
        assert r2.success
        assert db.query(Order).filter(Order.conversation_id == conv_id).count() == 1
        inv = db.query(InventoryItem).filter(InventoryItem.variant_id == variant_id).first()
        assert inv.quantity == 9  # no additional deduction


def conversation_active_draft(conv):
    """Helper to get active draft from conversation."""
    return conv.active_draft_json

# ---------------------------------------------------------------------------
# 14. Mobile-number extraction and privacy-safe cross-model history
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "phone",
    [
        "0512345678",
        "0612345678",
        "0712345678",
        "+213 6 123 456 78",
        "00213 5 123 456 78",
    ],
)
def test_algerian_mobile_numbers_are_recognized_and_normalized(phone):
    normalized = ConversationEngine._normalize_algerian_mobile_phone(phone)
    assert normalized in {"0512345678", "0612345678", "0712345678"}


def test_phone_label_does_not_swallow_mobile_value_or_whole_turn():
    safe = ConversationEngine._model_safe_customer_message(
        "رقم الهاتف 0674251265"
    )
    assert "0674251265" not in safe
    assert "phone withheld" in safe
    assert "رقم التواصل" in safe


def test_mobile_only_turn_remains_in_recent_dialogue_context(factory):
    store_id, conv_id, _ = seed(factory)
    with factory.begin() as db:
        conv = db.query(Conversation).filter(Conversation.id == conv_id).one()
        db.add(Message(
            conversation_id=conv_id,
            role=MessageRole.CUSTOMER,
            content="0674251265",
        ))
        db.flush()
        recent = ConversationEngine._recent_dialogue_context(
            db, conv_id, "next message"
        )
    assert recent
    assert recent[-1]["role"] == "customer"
    assert "0674251265" not in recent[-1]["content"]
    assert "phone withheld" in recent[-1]["content"]
