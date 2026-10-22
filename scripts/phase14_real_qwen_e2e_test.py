"""Run the real-Qwen Phase 14 flow inside a disposable PostgreSQL schema."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.database import engine as source_engine  # noqa: E402
from app.models.conversation import Conversation  # noqa: E402
from app.models.customer import Customer  # noqa: E402
from app.models.inventory import InventoryItem  # noqa: E402
from app.models.order import Order, OrderItem, OrderStatus  # noqa: E402
from app.models.product import Product, ProductVariant  # noqa: E402
from app.models.store import Store  # noqa: E402


EXPECTED_PRICE = Decimal("4500")


def preflight() -> bool:
    """Require local PostgreSQL and configured Qwen credentials."""
    if source_engine.dialect.name != "postgresql":
        print("DATABASE_URL must use PostgreSQL. Aborting.")
        return False
    if source_engine.url.host not in {"localhost", "127.0.0.1", "::1"}:
        print("DATABASE_URL must point to local PostgreSQL. Aborting.")
        return False
    if not os.getenv("QWEN_API_KEY"):
        print("QWEN_API_KEY is not set. Check the project .env file.")
        return False

    print(
        "DB OK: "
        f"{source_engine.url.host}:{source_engine.url.port}/"
        f"{source_engine.url.database}"
    )
    print("QWEN_MODEL=" + os.getenv("QWEN_MODEL", "qwen-max"))
    return True


def seed(db: Session) -> tuple[Store, Customer, Product, ProductVariant]:
    """Create isolated store fixtures; customer precedes its conversation."""
    suffix = uuid.uuid4().hex
    store = Store(
        name=f"Phase 14 Qwen E2E {suffix[:8]}",
        slug=f"phase14-qwen-e2e-{suffix}",
        is_active=True,
    )
    db.add(store)
    db.flush()

    customer = Customer(
        store_id=store.id,
        name=f"Phase 14 Customer {suffix[:8]}",
        phone=f"qwen-e2e-{suffix}",
        whatsapp_id=f"qwen-e2e-{suffix}",
    )
    db.add(customer)
    db.flush()

    product = Product(
        store_id=store.id,
        name="Nike",
        base_price=EXPECTED_PRICE,
        is_active=True,
    )
    db.add(product)
    db.flush()

    variant = ProductVariant(
        product_id=product.id,
        name="Standard",
        sku=f"TEST-NIKE-STD-{suffix}",
        price_adjustment=Decimal("0"),
        attributes_json={},
    )
    db.add(variant)
    db.flush()
    db.add(
        InventoryItem(
            store_id=store.id,
            variant_id=variant.id,
            quantity=10,
        )
    )
    db.commit()
    return store, customer, product, variant


async def run_test() -> bool:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if not preflight():
        return False

    test_connection = None
    outer_transaction = None
    db = None
    passed = False

    try:
        from app.agent.providers.qwen_provider import QwenLLMProvider
        from app.agent.tools.registry import ToolRegistry
        from app.agent.tools.search_products import SearchProductsTool
        from app.agent.tools.get_product_details import GetProductDetailsTool
        from app.agent.tools.create_order_draft import CreateOrderDraftTool
        from app.agent.tools.confirm_order import ConfirmOrderTool
        from app.agent.conversation_engine import ConversationEngine

        test_connection = source_engine.connect()
        outer_transaction = test_connection.begin()
        TestSessionLocal = sessionmaker(
            bind=test_connection,
            autoflush=False,
            autocommit=False,
            join_transaction_mode="create_savepoint",
        )
        db = TestSessionLocal()

        store, customer, product, variant = seed(db)
        conversation = Conversation(
            store_id=store.id,
            customer_id=customer.id,
            channel="whatsapp",
            status="active",
            metadata_json={},
            active_draft_json=None,
        )
        db.add(conversation)
        db.commit()
        conv_id = conversation.id

        registry = ToolRegistry()
        registry.register(SearchProductsTool())
        registry.register(GetProductDetailsTool())
        registry.register(CreateOrderDraftTool())
        registry.register(ConfirmOrderTool())

        engine = ConversationEngine(
            llm_provider=QwenLLMProvider(),
            tool_registry=registry,
        )
        stock_before = db.query(InventoryItem).filter(
            InventoryItem.store_id == store.id,
            InventoryItem.variant_id == variant.id,
        ).one().quantity
        started_at = time.monotonic()
        results: list[tuple[str, bool]] = []
        response_counts: list[tuple[str, int]] = []

        async def say(message: str) -> tuple[dict[str, Any], Conversation]:
            nonlocal conv_id
            response = await engine.process_message(
                db=db,
                store_id=store.id,
                customer_id=customer.id,
                conversation_id=conv_id,
                channel="whatsapp",
                user_message=message,
            )
            conv_id = uuid.UUID(response["conversation_id"])
            current_conversation = db.get(Conversation, conv_id)
            if current_conversation is None:
                raise RuntimeError(f"Conversation {conv_id} was not persisted.")
            db.refresh(current_conversation)
            print("-" * 70)
            print("USER :", message)
            print("BOT  :", response["response"])
            print("STAGE:", (current_conversation.metadata_json or {}).get("commerce_stage"))
            diagnostics = response.get("turn_diagnostics") or {}
            returned_count = diagnostics.get("responses_returned", 1)
            response_counts.append((message, returned_count))
            print("RESPONSES RETURNED:", returned_count)
            return response, current_conversation

        print("=" * 70)
        print("Real Qwen replay of the reported Nike confirmation flow")
        print("=" * 70)

        _, current = await say("حبيت نايك")
        search_state = current.metadata_json or {}
        results.append(
            (
                "search: selected product persisted",
                str(search_state.get("selected_product_id")) == str(product.id)
                or str(product.id) in [
                    str(value)
                    for value in search_state.get("candidate_product_ids", [])
                ],
            )
        )

        _, current = await say("حبيت ندير طلب")
        draft = current.active_draft_json or {}
        draft_items = draft.get("items", [])
        stock_after_draft = db.query(InventoryItem).filter(
            InventoryItem.store_id == store.id,
            InventoryItem.variant_id == variant.id,
        ).one().quantity
        results.append(
            (
                "draft: correct Nike variant, price, quantity; stock unchanged",
                len(draft_items) == 1
                and str(draft_items[0].get("variant_id")) == str(variant.id)
                and int(draft_items[0].get("quantity", 0)) == 1
                and Decimal(str(draft_items[0].get("unit_price", 0))) == EXPECTED_PRICE
                and stock_after_draft == stock_before,
            )
        )

        _, current = await say("طيب اكمل الطلب")
        orders_before_confirmation = db.query(Order).filter(
            Order.store_id == store.id,
            Order.customer_id == customer.id,
        ).count()
        stock_before_confirmation = db.query(InventoryItem).filter(
            InventoryItem.store_id == store.id,
            InventoryItem.variant_id == variant.id,
        ).one().quantity
        results.append(
            (
                "review phrase leaves draft unconfirmed and stock unchanged",
                bool((current.active_draft_json or {}).get("items"))
                and orders_before_confirmation == 0
                and stock_before_confirmation == stock_before,
            )
        )

        _, current = await say("اكدلي الطلب")
        orders = db.query(Order).filter(
            Order.store_id == store.id,
            Order.customer_id == customer.id,
        ).all()
        order = orders[0] if len(orders) == 1 else None
        order_items = (
            db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            if order is not None
            else []
        )
        stock_after_confirm = db.query(InventoryItem).filter(
            InventoryItem.store_id == store.id,
            InventoryItem.variant_id == variant.id,
        ).one().quantity
        results.append(
            (
                "confirm: one order, correct price, one deduction, draft cleared",
                order is not None
                and order.status == OrderStatus.CONFIRMED
                and Decimal(str(order.total)) == EXPECTED_PRICE
                and len(order_items) == 1
                and order_items[0].variant_id == variant.id
                and order_items[0].quantity == 1
                and Decimal(str(order_items[0].unit_price)) == EXPECTED_PRICE
                and stock_after_confirm == stock_before - 1
                and current.active_draft_json is None,
            )
        )

        results.append(
            (
                "every user turn yields exactly one returned response",
                len(response_counts) == 4
                and all(count == 1 for _, count in response_counts),
            )
        )

        print("=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        for name, ok in results:
            print(f"{name}: {'PASS' if ok else 'FAIL'}")
        print("PER-TURN RESPONSE COUNTS:")
        for message, count in response_counts:
            print(f"{message!r}: {count}")
        count_passed = sum(ok for _, ok in results)
        passed = count_passed == len(results)
        print(
            f"TOTAL: {count_passed}/{len(results)} PASS | "
            f"elapsed ~{time.monotonic() - started_at:.1f}s"
        )
        print("Database writes will be rolled back after the test.")

    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        if db is not None:
            db.rollback()
        passed = False
    finally:
        if db is not None:
            db.close()
        if outer_transaction is not None and outer_transaction.is_active:
            try:
                outer_transaction.rollback()
                print("Outer database transaction rolled back; test rows were not persisted.")
            except Exception:
                print("ERROR: failed to roll back the test transaction.")
                import traceback

                traceback.print_exc()
                passed = False
        if test_connection is not None:
            test_connection.close()
    return passed


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run_test()) else 1)
