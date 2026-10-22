"""Interactive terminal chat against the DzCommerce conversation engine."""
from __future__ import annotations

import asyncio
import argparse
import copy
import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from app.agent.conversation_engine import ConversationEngine  # noqa: E402
from app.agent.providers.qwen_provider import QwenLLMProvider  # noqa: E402
from app.agent.tools.confirm_order import ConfirmOrderTool  # noqa: E402
from app.agent.tools.create_order_draft import CreateOrderDraftTool  # noqa: E402
from app.agent.tools.get_product_details import GetProductDetailsTool  # noqa: E402
from app.agent.tools.registry import ToolRegistry  # noqa: E402
from app.agent.tools.search_products import SearchProductsTool  # noqa: E402
from app.database import SessionLocal, engine  # noqa: E402
from app.models.conversation import (  # noqa: E402
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from app.models.customer import Customer  # noqa: E402
from app.models.inventory import InventoryItem  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.product import Product, ProductVariant  # noqa: E402
from app.models.store import Store  # noqa: E402

STORE_NAME = "DzCommerce Demo"
STORE_SLUG = "dzcommerce-demo"
CUSTOMER_NAME = "عميل تجريبي"
PRODUCT_NAME = "حذاء أحذية رياضية Nike Air Max (Manual Chat Demo)"
LEGACY_PRODUCT_NAMES = (
    "Nike Air Max (Manual Chat Demo)",
    "أحذية رياضية Nike Air Max (Manual Chat Demo)",
)
VARIANTS = (
    {
        "name": "أسود / 42",
        "sku": "MANUAL-CHAT-NIKE-BLACK-42",
        "attributes": {"color": "black", "size": "42"},
    },
    {
        "name": "أبيض / 42",
        "sku": "MANUAL-CHAT-NIKE-WHITE-42",
        "attributes": {"color": "white", "size": "42"},
    },
)


class Color:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"


def colored(text: str, color: str) -> str:
    return f"{color}{text}{Color.RESET}"


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def ensure_customer(
    db: Session,
    store_id: uuid.UUID,
    customer_id: uuid.UUID | None = None,
) -> tuple[Customer, bool]:
    """Reuse a customer belonging to this store, or create the demo customer."""
    if customer_id is not None:
        customer = db.query(Customer).filter(Customer.id == customer_id).first()
        if customer is None:
            raise ValueError(f"Customer {customer_id} was not found.")
        if customer.store_id != store_id:
            raise ValueError(
                f"Customer {customer_id} belongs to store {customer.store_id}, "
                f"not selected store {store_id}."
            )
        return customer, False

    customer = (
        db.query(Customer)
        .filter(Customer.store_id == store_id, Customer.name == CUSTOMER_NAME)
        .first()
    )
    if customer is None:
        customer = (
            db.query(Customer)
            .filter(Customer.store_id == store_id)
            .order_by(Customer.created_at.asc())
            .first()
        )
    if customer is not None:
        return customer, False

    customer = Customer(store_id=store_id, name=CUSTOMER_NAME)
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer, True


def ensure_demo_data(
    db: Session,
    customer_id: uuid.UUID | None = None,
) -> tuple[Store, Customer, Product, list[ProductVariant], dict[str, list[str]]]:
    """Create missing demo fixtures without resetting any existing inventory."""
    created: dict[str, list[str]] = {
        "created": [],
        "reused": [],
    }

    store = db.query(Store).filter(Store.slug == STORE_SLUG).first()
    if store is None:
        store = Store(name=STORE_NAME, slug=STORE_SLUG, is_active=True)
        db.add(store)
        db.flush()
        created["created"].append("store")
    else:
        created["reused"].append("store")

    customer, customer_created = ensure_customer(db, store.id, customer_id)
    if customer_created:
        created["created"].append("customer")
    else:
        created["reused"].append("customer")

    product = (
        db.query(Product)
        .filter(Product.store_id == store.id, Product.name == PRODUCT_NAME)
        .first()
    )
    if product is None:
        product = (
            db.query(Product)
            .filter(
                Product.store_id == store.id,
                Product.name.in_(LEGACY_PRODUCT_NAMES),
            )
            .first()
        )
        if product is not None:
            product.name = PRODUCT_NAME
    if product is None:
        product = Product(
            store_id=store.id,
            name=PRODUCT_NAME,
            base_price=Decimal("12000.00"),
            is_active=True,
        )
        db.add(product)
        db.flush()
        created["created"].append("product")
    else:
        created["reused"].append("product")
        if not product.is_active:
            product.is_active = True

    variants: list[ProductVariant] = []
    for spec in VARIANTS:
        variant = (
            db.query(ProductVariant)
            .filter(
                ProductVariant.product_id == product.id,
                ProductVariant.attributes_json == spec["attributes"],
            )
            .first()
        )
        if variant is None:
            variant = ProductVariant(
                product_id=product.id,
                name=spec["name"],
                sku=spec["sku"],
                attributes_json=spec["attributes"],
                price_adjustment=Decimal("0.00"),
            )
            db.add(variant)
            db.flush()
            created["created"].append(f"variant:{spec['attributes']['color']}-42")
        else:
            created["reused"].append(f"variant:{spec['attributes']['color']}-42")

        inventory = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.store_id == store.id,
                InventoryItem.variant_id == variant.id,
            )
            .first()
        )
        if inventory is None:
            inventory = InventoryItem(
                store_id=store.id,
                variant_id=variant.id,
                quantity=10,
            )
            db.add(inventory)
            created["created"].append(f"inventory:{spec['attributes']['color']}-42")
        else:
            created["reused"].append(f"inventory:{spec['attributes']['color']}-42")
        variants.append(variant)

    db.commit()
    return store, customer, product, variants, created


def new_conversation(db: Session, store_id: uuid.UUID, customer_id: uuid.UUID) -> Conversation:
    conversation = Conversation(
        store_id=store_id,
        customer_id=customer_id,
        channel="manual",
        status=ConversationStatus.ACTIVE,
        metadata_json={},
        active_draft_json=None,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def fetch_conversation(conversation_id: uuid.UUID) -> Conversation:
    with SessionLocal() as fresh_db:
        conversation = (
            fresh_db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if conversation is None:
            raise RuntimeError(f"Conversation {conversation_id} was not found.")
        fresh_db.expunge(conversation)
        return conversation


def read_stock(variant_id: uuid.UUID | None, store_id: uuid.UUID) -> int | None:
    if variant_id is None:
        return None
    with SessionLocal() as fresh_db:
        inventory = (
            fresh_db.query(InventoryItem)
            .filter(
                InventoryItem.store_id == store_id,
                InventoryItem.variant_id == variant_id,
            )
            .first()
        )
        return inventory.quantity if inventory else None


def read_order_count(conversation_id: uuid.UUID, customer_id: uuid.UUID) -> int:
    with SessionLocal() as fresh_db:
        return (
            fresh_db.query(Order)
            .filter(
                Order.conversation_id == conversation_id,
                Order.customer_id == customer_id,
            )
            .count()
        )


def persist_message(
    db: Session,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        external_message_id=f"manual:{uuid.uuid4()}",
        metadata_json=metadata,
    )
    db.add(message)
    db.commit()
    return message


class RecordingToolRegistry(ToolRegistry):
    """Capture the exact arguments passed through the normal tool registry."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []

    async def aexecute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> Any:
        self.calls.append(
            {"name": tool_name, "arguments": copy.deepcopy(arguments)}
        )
        return await super().aexecute(tool_name, arguments, context)


def parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"'{value}' is not a valid UUID.") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chat with the DzCommerce agent.")
    parser.add_argument(
        "--store",
        type=parse_uuid,
        help="Target an existing store by UUID; defaults to the DzCommerce Demo store.",
    )
    parser.add_argument(
        "--customer",
        type=parse_uuid,
        help="Use an existing customer UUID belonging to the selected store.",
    )
    return parser.parse_args()


async def run_chat(args: argparse.Namespace) -> None:
    if engine.dialect.name != "postgresql" or engine.url.host not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise RuntimeError(
            "Manual chat requires local PostgreSQL; refusing to seed a non-local database."
        )

    db = SessionLocal()
    try:
        if args.store is None:
            store, customer, product, variants, seed_status = ensure_demo_data(
                db,
                args.customer,
            )
            print(colored("Demo data", Color.CYAN))
            print_json(
                {
                    **seed_status,
                    "store": {"name": store.name, "slug": store.slug, "id": store.id},
                    "customer": {"name": customer.name, "id": customer.id},
                    "product": {"name": product.name, "id": product.id},
                    "variants": [
                        {
                            "name": variant.name,
                            "attributes": variant.attributes_json,
                            "stock": read_stock(variant.id, store.id),
                        }
                        for variant in variants
                    ],
                }
            )
        else:
            store = db.query(Store).filter(Store.id == args.store).first()
            if store is None:
                raise ValueError(f"Store {args.store} was not found.")
            customer, customer_created = ensure_customer(
                db,
                store.id,
                args.customer,
            )
            print(
                colored(
                    f"Target store: {store.name} ({store.id})",
                    Color.CYAN,
                )
            )
            print(
                colored(
                    f"Customer {'created' if customer_created else 'reused'}: "
                    f"{customer.name} ({customer.id}), store_id={customer.store_id}",
                    Color.YELLOW,
                )
            )

        registry = RecordingToolRegistry()
        for tool in (
            SearchProductsTool(),
            GetProductDetailsTool(),
            CreateOrderDraftTool(),
            ConfirmOrderTool(),
        ):
            registry.register(tool)

        engine_instance = ConversationEngine(
            llm_provider=QwenLLMProvider(),
            tool_registry=registry,
        )
        conversation = new_conversation(db, store.id, customer.id)
        conversation_id = conversation.id
        print(
            colored(
                f"Conversation: {conversation_id} (store_id={store.id})",
                Color.YELLOW,
            )
        )
        turn_number = 0
        tracked_variant_id: uuid.UUID | None = None

        print(colored("\nDzCommerce Manual Chat — /state /reset /clear-draft /exit", Color.CYAN))
        while True:
            try:
                text = input(colored("You> ", Color.GREEN)).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not text:
                continue
            if text == "/exit":
                break
            if text == "/state":
                state = fetch_conversation(conversation_id)
                print(colored("metadata_json:", Color.YELLOW))
                print_json(state.metadata_json or {})
                print(colored("active_draft_json:", Color.YELLOW))
                print_json(state.active_draft_json)
                continue
            if text == "/reset":
                conversation = new_conversation(db, store.id, customer.id)
                conversation_id = conversation.id
                tracked_variant_id = None
                print(colored(f"Started conversation {conversation_id}", Color.YELLOW))
                continue
            if text == "/clear-draft":
                current = (
                    db.query(Conversation)
                    .filter(Conversation.id == conversation_id)
                    .first()
                )
                if current is None:
                    raise RuntimeError(f"Conversation {conversation_id} was not found.")
                current.active_draft_json = None
                db.commit()
                print(colored("Draft cleared.", Color.YELLOW))
                continue

            turn_number += 1
            stock_before = read_stock(tracked_variant_id, store.id)
            orders_before = read_order_count(conversation_id, customer.id)
            try:
                persist_message(
                    db,
                    conversation_id,
                    MessageRole.CUSTOMER,
                    text,
                )
                registry.calls.clear()
                result = await engine_instance.process_message(
                    db=db,
                    store_id=store.id,
                    customer_id=customer.id,
                    conversation_id=conversation_id,
                    channel="manual",
                    user_message=text,
                )
                print(colored(f"Customer> {text}", Color.GREEN))
                if result.get("error"):
                    reply = f"Engine error: {result['error']}"
                    print(colored(reply, Color.RED))
                else:
                    reply = str(result["response"])
                    print(colored(f"Agent> {reply}", Color.CYAN))

                message_metadata = {
                    "engine_tool_calls": result.get("tool_calls", []),
                    "observed_tool_calls": copy.deepcopy(registry.calls),
                }
                persist_message(
                    db,
                    conversation_id,
                    MessageRole.AGENT,
                    reply,
                    message_metadata,
                )

                fresh = fetch_conversation(conversation_id)
                draft_items = (fresh.active_draft_json or {}).get("items", [])
                if draft_items and draft_items[0].get("variant_id"):
                    tracked_variant_id = uuid.UUID(str(draft_items[0]["variant_id"]))
                elif (fresh.metadata_json or {}).get("selected_variant_id"):
                    tracked_variant_id = uuid.UUID(
                        str(fresh.metadata_json["selected_variant_id"])
                    )

                print(colored("engine tool_calls:", Color.YELLOW))
                print_json(result.get("tool_calls", []))
                print(colored("tools called + raw arguments:", Color.YELLOW))
                print_json(registry.calls)
                print(colored("metadata_json (fresh DB read):", Color.YELLOW))
                print_json(fresh.metadata_json or {})
                print(colored("active_draft_json (fresh DB read):", Color.YELLOW))
                print_json(fresh.active_draft_json)

                if turn_number in (4, 5):
                    stock_after = read_stock(tracked_variant_id, store.id)
                    orders_after = read_order_count(conversation_id, customer.id)
                    print(colored(f"Stock before turn: {stock_before}", Color.YELLOW))
                    print(colored(f"Stock after turn:  {stock_after}", Color.YELLOW))
                    print(colored(f"Orders before turn: {orders_before}", Color.YELLOW))
                    print(colored(f"Orders after turn:  {orders_after}", Color.YELLOW))

                with SessionLocal() as fresh_db:
                    message_count = (
                        fresh_db.query(Message)
                        .filter(Message.conversation_id == conversation_id)
                        .count()
                    )
                print(colored(f"Persisted messages in conversation: {message_count}", Color.YELLOW))
            except Exception as exc:
                db.rollback()
                print(colored(f"Turn failed ({type(exc).__name__}): {exc}", Color.RED))

    finally:
        db.close()


if __name__ == "__main__":
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(run_chat(parse_args()))
    except Exception as exc:
        print(colored(f"Startup failed ({type(exc).__name__}): {exc}", Color.RED))
        raise SystemExit(1) from exc
