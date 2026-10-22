from __future__ import annotations

import asyncio
import importlib
import json
import sys
import uuid
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.base import LLMResponse
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.database import Base, engine as source_engine
import app.models  # noqa: F401
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem
from app.models.product import Product, ProductVariant
from app.models.store import Store

PREFERRED_STORE_ID = uuid.UUID("8c072081-f062-4831-856b-fe31b287e712")


class FakeNLU:
    """Return deterministic structured NLU without making external model calls."""

    def __init__(self, payloads: list[dict[str, Any]]):
        self.payloads = list(payloads)

    async def chat(self, messages=None, tools=None, system_prompt=None):
        if not self.payloads:
            return LLMResponse(
                content=json.dumps({"intent": "unknown", "confidence": 0.0}),
                finish_reason="stop",
            )
        return LLMResponse(
            content=json.dumps(self.payloads.pop(0)),
            finish_reason="stop",
        )


def print_json(label: str, value: Any) -> None:
    print(f"{label}:\n{json.dumps(value, default=str, ensure_ascii=False, indent=2)}")


def get_real_test_records(db: Session) -> tuple[Store, Product, ProductVariant, Customer]:
    """Choose a real Nike store/product with the requested black size-42 variant."""
    matching_rows = (
        db.query(Store, Product, ProductVariant)
        .join(Product, Product.store_id == Store.id)
        .join(ProductVariant, ProductVariant.product_id == Product.id)
        .filter(
            Product.name.ilike("%Nike%"),
            Product.is_active.is_(True),
            ProductVariant.name.ilike("%black%"),
            ProductVariant.name.ilike("%42%"),
        )
        .all()
    )
    if not matching_rows:
        raise RuntimeError("No active Nike product with a Black / Size 42 variant exists.")

    preferred = next(
        (row for row in matching_rows if row[0].id == PREFERRED_STORE_ID),
        None,
    )
    store, product, variant = preferred or matching_rows[0]

    customer = (
        db.query(Customer)
        .filter(Customer.store_id == store.id)
        .order_by(Customer.name)
        .first()
    )
    if customer is None:
        raise RuntimeError(f"No existing customer belongs to store {store.id}.")

    return store, product, variant, customer


def copy_test_records(source_db: Session, probe_db: Session) -> tuple[Store, Product, ProductVariant, Customer]:
    store, product, variant, customer = get_real_test_records(source_db)

    probe_store = Store(
        id=store.id,
        name=store.name,
        slug=store.slug,
        is_active=store.is_active,
    )
    probe_product = Product(
        id=product.id,
        store_id=product.store_id,
        name=product.name,
        description=product.description,
        sku=product.sku,
        base_price=product.base_price,
        is_active=product.is_active,
    )
    probe_variant = ProductVariant(
        id=variant.id,
        product_id=variant.product_id,
        name=variant.name,
        sku=variant.sku,
        price_adjustment=variant.price_adjustment,
    )
    probe_customer = Customer(
        id=customer.id,
        store_id=customer.store_id,
        name=customer.name,
        email=customer.email,
        phone=customer.phone,
        facebook_id=None,
        whatsapp_id=None,
    )
    source_inventory = source_db.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one_or_none()
    if source_inventory is None:
        raise RuntimeError(f"No inventory record exists for variant {variant.id}.")

    probe_inventory = InventoryItem(
        id=source_inventory.id,
        store_id=source_inventory.store_id,
        variant_id=source_inventory.variant_id,
        quantity=source_inventory.quantity,
        low_stock_threshold=source_inventory.low_stock_threshold,
    )
    probe_db.add(probe_store)
    probe_db.commit()

    probe_db.add(probe_product)
    probe_db.commit()

    probe_db.add_all([probe_variant, probe_customer])
    probe_db.commit()

    probe_db.add(probe_inventory)
    probe_db.commit()
    return probe_store, probe_product, probe_variant, probe_customer


def canonical_state(db: Session, conversation_id: uuid.UUID, store_id: uuid.UUID) -> dict:
    conversation = db.query(Conversation).filter(
        Conversation.id == conversation_id
    ).one()
    return ConversationEngine._normalize_current_state(conversation, store_id)


def orders_for_customer(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> list[Order]:
    return (
        db.query(Order)
        .filter(Order.store_id == store_id, Order.customer_id == customer_id)
        .all()
    )


def inventory_quantity(
    db: Session,
    store_id: uuid.UUID,
    variant_id: uuid.UUID,
) -> int | None:
    inventory = db.query(InventoryItem).filter(
        InventoryItem.store_id == store_id,
        InventoryItem.variant_id == variant_id,
    ).one_or_none()
    return inventory.quantity if inventory else None


async def run_flow() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    schema_name = f"phase13_probe_{uuid.uuid4().hex}"
    with source_engine.begin() as source_connection:
        source_connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    probe_engine = create_engine(
        source_engine.url,
        connect_args={"options": f"-csearch_path={schema_name}"},
        pool_pre_ping=True,
    )
    Base.metadata.create_all(bind=probe_engine)
    ProbeSessionLocal = sessionmaker(
        bind=probe_engine,
        autoflush=False,
        autocommit=False,
    )
    registry_module = importlib.import_module("app.agent.tools.registry")
    original_registry_session_factory = registry_module.SessionLocal
    registry_module.SessionLocal = ProbeSessionLocal
    source_session = sessionmaker(bind=source_engine)()
    db = ProbeSessionLocal()

    statuses = {
        "STEP 1 Product Search": "FAIL",
        "STEP 2 Variant Selection": "FAIL (not reached)",
        "STEP 3 Draft Creation": "FAIL (not reached)",
        "STEP 4 Confirmation": "FAIL (not reached)",
        "STEP 5 Duplicate Confirmation": "FAIL (not reached)",
    }
    stock_before = None
    stock_after = None
    variant_id = None
    order_id = None
    duplicate_order_created = False
    duplicate_stock_deduction = False

    try:
        store, product, expected_variant, customer = copy_test_records(
            source_session,
            db,
        )
        store_id = store.id
        customer_id = customer.id
        variant_id = expected_variant.id
        conversation_id = uuid.uuid4()

        print(
            f"DATABASE: {source_engine.url.host}:{source_engine.url.port}/"
            f"{source_engine.url.database} (isolated schema: {schema_name})"
        )
        print(f"REAL STORE:\n{store_id}")
        print(f"REAL PRODUCT:\n{product.id}")
        print(f"PRODUCT NAME:\n{product.name}")
        print(f"REAL VARIANT:\n{expected_variant.name}")
        print(f"VARIANT ID:\n{expected_variant.id}")
        print(f"TEST CUSTOMER:\n{customer.id} ({customer.name})")

        stock_before = inventory_quantity(db, store_id, variant_id)
        baseline_order_ids = {
            order.id for order in orders_for_customer(db, store_id, customer_id)
        }

        conversation = Conversation(
            id=conversation_id,
            store_id=store_id,
            customer_id=customer_id,
            channel="web",
            status="active",
            metadata_json={},
            active_draft_json=None,
        )
        db.add(conversation)
        db.commit()

        # Step 1 calls the application's existing search tool directly.
        search_result = await SearchProductsTool().execute(
            store_id=store_id,
            arguments={"query": "Nike"},
            context={
                "db": db,
                "store_id": store_id,
                "customer_id": customer_id,
                "conversation_id": conversation_id,
                "channel": "web",
            },
        )
        db.commit()
        state_after_search = canonical_state(db, conversation_id, store_id)
        search_products = search_result.data.get("products", [])
        selected_product_id = state_after_search.get("selected_product_id")
        selected_product_name = state_after_search.get("selected_product_name")

        print("\nSTEP 1 Product Search:", end=" ")
        step1_ok = (
            search_result.success
            and any(str(row.get("id")) == str(product.id) for row in search_products)
            and str(selected_product_id) == str(product.id)
            and selected_product_name == product.name
        )
        print("PASS" if step1_ok else "FAIL")
        print_json("SEARCH RESPONSE", {
            "success": search_result.success,
            "data": search_result.data,
            "error": search_result.error,
        })
        print(f"SELECTED PRODUCT ID:\n{selected_product_id}")
        print(f"SELECTED PRODUCT NAME:\n{selected_product_name}")
        print_json("CANONICAL STATE", state_after_search)
        if not step1_ok:
            report_failure(
                file="app/agent/tools/search_products.py",
                function="SearchProductsTool.execute",
                expected=f"selected real DB product {product.id} ({product.name})",
                actual={
                    "success": search_result.success,
                    "error": search_result.error,
                    "selected_product_id": selected_product_id,
                    "products": search_products,
                },
            )
            return
        statuses["STEP 1 Product Search"] = "PASS"

        registry = ToolRegistry()
        registry.register(SearchProductsTool())
        registry.register(GetProductDetailsTool())
        registry.register(CreateOrderDraftTool())
        registry.register(ConfirmOrderTool())
        llm = FakeNLU([
            {
                "intent": "variant_selection",
                "product_mention": None,
                "attributes": {"color": "black", "size": "42"},
                "quantity": 1,
                "confirmation_phrase": False,
                "language": "ar",
                "confidence": 1.0,
            },
            {
                "intent": "order_create",
                "product_mention": None,
                "attributes": {},
                "quantity": 1,
                "confirmation_phrase": False,
                "language": "ar",
                "confidence": 1.0,
            },
            {
                "intent": "order_confirm",
                "product_mention": None,
                "attributes": {},
                "quantity": 1,
                "confirmation_phrase": True,
                "language": "ar",
                "confidence": 1.0,
            },
            {
                "intent": "order_confirm",
                "product_mention": None,
                "attributes": {},
                "quantity": 1,
                "confirmation_phrase": True,
                "language": "ar",
                "confidence": 1.0,
            },
        ])
        app = ConversationEngine(llm, registry)

        # Step 2 uses the normal engine/resolver flow against the real DB.
        step2_response = await app.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            channel="web",
            user_message="الأسود 42",
        )
        state_after_variant = canonical_state(db, conversation_id, store_id)
        resolved_variant_id = state_after_variant.get("selected_variant_id")
        step2_ok = str(resolved_variant_id) == str(expected_variant.id)
        statuses["STEP 2 Variant Selection"] = "PASS" if step2_ok else "FAIL"
        print("\nSTEP 2 Variant Selection:", statuses["STEP 2 Variant Selection"])
        if not step2_ok:
            stock_after = inventory_quantity(db, store_id, variant_id)
            report_failure(
                file="app/agent/commerce_resolver.py",
                function="CommerceResolver.resolve / _resolve_variant_from_attributes",
                expected=f"selected_variant_id={expected_variant.id} from DB attributes/name",
                actual={
                    "selected_variant_id": resolved_variant_id,
                    "response": step2_response.get("response"),
                    "variant_index_map": state_after_variant.get("variant_index_map"),
                    "database_variant_name": expected_variant.name,
                },
            )
        print_json("STEP 2 RESPONSE", step2_response)
        print_json("STATE AFTER STEP 2", state_after_variant)
        print("EXPECTED VARIANT:", expected_variant.name, expected_variant.id)
        if not step2_ok:
            return

        # Step 3 proceeds only if the backend actually selected the DB variant.
        step3_response = await app.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            channel="web",
            user_message="ديرلي طلب",
        )
        conversation = db.query(Conversation).filter(
            Conversation.id == conversation_id
        ).one()
        draft = conversation.active_draft_json or {}
        step3_ok = bool(draft.get("items")) and any(
            str(item.get("variant_id")) == str(expected_variant.id)
            and item.get("product_name") == product.name
            and int(item.get("quantity", 0)) == 1
            and float(item.get("unit_price", 0)) == float(product.base_price)
            for item in draft.get("items", [])
        )
        statuses["STEP 3 Draft Creation"] = "PASS" if step3_ok else "FAIL"
        print("\nSTEP 3 Draft Creation:", statuses["STEP 3 Draft Creation"])
        print_json("STEP 3 RESPONSE", step3_response)
        print_json("DRAFT AFTER STEP 3", draft)
        if not step3_ok:
            report_failure(
                file="app/agent/conversation_engine.py",
                function="ConversationEngine._handle_service_call / create_draft",
                expected="active draft with real product/variant IDs, DB price, and quantity 1",
                actual={"response": step3_response.get("response"), "active_draft_json": draft},
            )
            return

        # Step 4 confirmation commits only to the enclosing test transaction.
        step4_response = await app.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            channel="web",
            user_message="أكد",
        )
        orders_after_confirm = orders_for_customer(db, store_id, customer_id)
        new_orders = [o for o in orders_after_confirm if o.id not in baseline_order_ids]
        order_id = new_orders[0].id if len(new_orders) == 1 else None
        order_items = (
            db.query(OrderItem)
            .filter(OrderItem.order_id == order_id)
            .all()
            if order_id
            else []
        )
        stock_after = inventory_quantity(db, store_id, variant_id)
        step4_ok = (
            len(new_orders) == 1
            and new_orders[0].store_id == store_id
            and new_orders[0].status.value == "confirmed"
            and len(order_items) == 1
            and order_items[0].variant_id == expected_variant.id
            and order_items[0].quantity == 1
        )
        statuses["STEP 4 Confirmation"] = "PASS" if step4_ok else "FAIL"
        print("\nSTEP 4 Confirmation:", statuses["STEP 4 Confirmation"])
        print_json("STEP 4 RESPONSE", step4_response)
        print("ORDER ID:", order_id)
        print("ORDER STATUS:", new_orders[0].status if new_orders else None)
        print("INVENTORY BEFORE:", stock_before)
        print("INVENTORY AFTER:", stock_after)
        if not step4_ok:
            report_failure(
                file="app/agent/tools/confirm_order.py",
                function="ConfirmOrderTool.execute",
                expected="one confirmed order for this store/customer and one item for the real variant",
                actual={
                    "new_order_ids": [str(o.id) for o in new_orders],
                    "order_items": [
                        {
                            "variant_id": str(i.variant_id),
                            "quantity": i.quantity,
                        }
                        for i in order_items
                    ],
                    "stock_before": stock_before,
                    "stock_after": stock_after,
                },
            )
            return

        # Step 5 must not create an additional order or deduct stock again.
        step5_response = await app.process_message(
            db=db,
            store_id=store_id,
            customer_id=customer_id,
            conversation_id=conversation_id,
            channel="web",
            user_message="أكد",
        )
        orders_after_duplicate = orders_for_customer(db, store_id, customer_id)
        duplicate_orders = [
            o for o in orders_after_duplicate
            if o.id not in baseline_order_ids and o.id != order_id
        ]
        duplicate_item_count = (
            db.query(OrderItem).filter(OrderItem.order_id == order_id).count()
            if order_id
            else 0
        )
        final_stock = inventory_quantity(db, store_id, variant_id)
        duplicate_order_created = bool(duplicate_orders)
        duplicate_stock_deduction = (
            stock_after is not None
            and final_stock is not None
            and final_stock < stock_after
        )
        step5_ok = (
            not duplicate_order_created
            and not duplicate_stock_deduction
            and duplicate_item_count == 1
        )
        statuses["STEP 5 Duplicate Confirmation"] = "PASS" if step5_ok else "FAIL"
        print("\nSTEP 5 Duplicate Confirmation:", statuses["STEP 5 Duplicate Confirmation"])
        print_json("DUPLICATE RESULT", step5_response)
        print("DUPLICATE ORDER CREATED:", "YES" if duplicate_order_created else "NO")
        print("DUPLICATE STOCK DEDUCTION:", "YES" if duplicate_stock_deduction else "NO")
        print("ORDER ITEM COUNT:", duplicate_item_count)
        print("INVENTORY AFTER DUPLICATE:", final_stock)
        if not step5_ok:
            report_failure(
                file="app/agent/tools/confirm_order.py",
                function="ConfirmOrderTool.execute / ConversationEngine.process_message",
                expected="no second order, no second stock deduction, and one order item",
                actual={
                    "duplicate_order_ids": [str(o.id) for o in duplicate_orders],
                    "duplicate_stock_deduction": duplicate_stock_deduction,
                    "order_item_count": duplicate_item_count,
                    "response": step5_response.get("response"),
                },
            )
    finally:
        db.close()
        source_session.close()
        registry_module.SessionLocal = original_registry_session_factory
        probe_engine.dispose()
        with source_engine.begin() as source_connection:
            source_connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        print("\nISOLATED SCHEMA: dropped; no test records or stock changes persisted to the live schema.")
        print("\nFINAL STEP RESULTS:")
        for name, status in statuses.items():
            print(f"{name}: {status}")
        print("ORDER ID:", order_id)
        print("VARIANT ID:", variant_id)
        print("INVENTORY BEFORE:", stock_before)
        print("INVENTORY AFTER:", stock_after)
        print("DUPLICATE ORDER CREATED:", "YES" if duplicate_order_created else "NO")
        print("DUPLICATE STOCK DEDUCTION:", "YES" if duplicate_stock_deduction else "NO")


def report_failure(file: str, function: str, expected: str, actual: Any) -> None:
    print("FILE:", file)
    print("FUNCTION:", function)
    print("ERROR: Real Phase 13 flow did not meet the expected result.")
    print("EXPECTED:", expected)
    print_json("ACTUAL", actual)


if __name__ == "__main__":
    asyncio.run(run_flow())
