from __future__ import annotations

import asyncio
import importlib
import json
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import conversation_engine as conversation_engine_module
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.base import LLMMessage, LLMResponse
from app.agent.tools import tool_registry
from app.database import Base, engine as source_engine
import app.models  # noqa: F401
from app.models.conversation import Conversation, Message, MessageRole
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store


SENDER_ID = "phase14-e2e-customer"
EXPECTED_PRICE = 79_900.0
STEPS: dict[str, dict[str, str]] = {
    "1 Product search": {
        "expected": "single Samsung product selected; PRODUCT_SELECTED",
        "actual": "not run",
        "result": "NOT RUN",
    },
    "2 Attribute variant resolution": {
        "expected": "real variant selected; reply includes DB price and stock",
        "actual": "not run",
        "result": "NOT RUN",
    },
    "3 Draft creation": {
        "expected": "one draft item; quantity 1; stock remains 10",
        "actual": "not run",
        "result": "NOT RUN",
    },
    "4 Order confirmation": {
        "expected": "one CONFIRMED order; stock becomes 9; draft cleared",
        "actual": "not run",
        "result": "NOT RUN",
    },
    "5 Duplicate webhook": {
        "expected": "duplicate mid skipped; one order; stock remains 9",
        "actual": "not run",
        "result": "NOT RUN",
    },
}


class OfflineNLU:
    """Provide deterministic NLU responses without making network requests."""

    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = list(payloads)

    async def chat(
        self,
        messages: list[LLMMessage] | None = None,
        tools: list[Any] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        del messages, tools, system_prompt
        if not self.payloads:
            raise RuntimeError("Offline NLU has no response queued for this webhook.")
        return LLMResponse(
            content=json.dumps(self.payloads.pop(0), ensure_ascii=False),
            finish_reason="stop",
        )


def nlu(intent: str, **values: Any) -> dict[str, Any]:
    return {
        "intent": intent,
        "intent_guess": intent,
        "product_mention": None,
        "attributes": {},
        "quantity": None,
        "confirmation_phrase": False,
        "language": "ar",
        "confidence": 1.0,
        **values,
    }


def webhook_request(payload: dict[str, Any]) -> Request:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/webhooks/meta",
        "raw_path": b"/webhooks/meta",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "server": ("testserver", 80),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope, receive)


def meta_payload(sender_id: str, mid: str, message: str) -> dict[str, Any]:
    return {
        "object": "page",
        "entry": [
            {
                "messaging": [
                    {
                        "sender": {"id": sender_id},
                        "recipient": {"id": "phase14-test-page"},
                        "timestamp": 1,
                        "message": {"mid": mid, "text": message},
                    }
                ]
            }
        ],
    }


def set_step(name: str, actual: Any, passed: bool) -> None:
    STEPS[name]["actual"] = str(actual)
    STEPS[name]["result"] = "PASS" if passed else "FAIL"
    print(f"{name}: {STEPS[name]['result']} — {actual}")
    if not passed:
        raise AssertionError(f"{name} failed: {actual}")


def print_json(label: str, value: Any) -> None:
    print(f"{label}:\n{json.dumps(value, ensure_ascii=False, default=str, indent=2)}")


def ensure_local_postgres() -> None:
    if source_engine.dialect.name != "postgresql":
        raise RuntimeError("Phase 14 E2E requires the configured PostgreSQL database.")

    host = source_engine.url.host
    if host not in (None, "", "localhost", "127.0.0.1", "::1"):
        raise RuntimeError(
            "Refusing to run: DATABASE_URL does not point to a local PostgreSQL host."
        )


def seed_fixture(db: Session) -> tuple[Store, Product, ProductVariant]:
    store = Store(
        name="Phase 14 E2E Store",
        slug=f"phase14-e2e-{uuid.uuid4().hex}",
        is_active=True,
    )
    db.add(store)
    db.flush()

    phone = Product(
        store_id=store.id,
        name="Samsung Galaxy A54",
        description="Phase 14 electronics test fixture",
        base_price=EXPECTED_PRICE,
        is_active=True,
    )
    table = Product(
        store_id=store.id,
        name="طاولة خشب",
        description="Phase 14 furniture test fixture",
        base_price=24_500.0,
        is_active=True,
    )
    db.add_all([phone, table])
    db.flush()

    phone_variant = ProductVariant(
        product_id=phone.id,
        name="256GB / Black",
        price_adjustment=0,
        attributes_json={"storage": "256GB", "color": "black"},
    )
    table_variant = ProductVariant(
        product_id=table.id,
        name="Wood",
        price_adjustment=0,
        attributes_json={"material": "wood"},
    )
    db.add_all([phone_variant, table_variant])
    db.flush()
    db.add_all(
        [
            InventoryItem(store_id=store.id, variant_id=phone_variant.id, quantity=10),
            InventoryItem(store_id=store.id, variant_id=table_variant.id, quantity=5),
        ]
    )
    db.commit()
    return store, phone, phone_variant


def snapshot(
    db: Session,
    sender_id: str,
) -> tuple[Conversation | None, str | None]:
    db.rollback()
    customer = db.query(Customer).filter(Customer.phone == sender_id).one_or_none()
    if customer is None:
        return None, None
    conversation = (
        db.query(Conversation)
        .filter(
            Conversation.customer_id == customer.id,
            Conversation.status == "active",
        )
        .one_or_none()
    )
    if conversation is None:
        return None, None
    latest_reply = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role == MessageRole.AGENT,
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    return conversation, latest_reply.content if latest_reply else None


async def send_webhook(
    webhook_module: Any,
    db: Session,
    mid: str,
    message: str,
) -> dict[str, Any]:
    return await webhook_module.meta_webhook(
        webhook_request(meta_payload(SENDER_ID, mid, message)),
        db,
    )


async def run_e2e() -> bool:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    schema_name = f"p14e2e_{uuid.uuid4().hex}"
    schema_created = False
    probe_engine = None
    db = None
    registry_module = importlib.import_module("app.agent.tools.registry")
    original_session_factory = registry_module.SessionLocal
    original_resolve = conversation_engine_module.CommerceResolver.resolve
    webhook_module = None
    original_webhook_engine = None
    original_qwen_api_key = None
    active_step = "1 Product search"
    exception_text = ""
    cleanup_failed = False

    action_log: list[str] = []

    def record_resolution(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_resolve(self, *args, **kwargs)
        action_log.append(result.allowed_action)
        return result

    try:
        ensure_local_postgres()
        with source_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))
        schema_created = True

        probe_engine = create_engine(
            source_engine.url,
            connect_args={"options": f"-csearch_path={schema_name}"},
            pool_pre_ping=True,
        )
        Base.metadata.create_all(bind=probe_engine)
        probe_session_factory = sessionmaker(
            bind=probe_engine,
            autoflush=False,
            autocommit=False,
        )
        db = probe_session_factory()
        registry_module.SessionLocal = probe_session_factory

        # webhooks.py eagerly constructs QwenLLMProvider at import time. Replace
        # its key only in-process, then replace its engine before handling a request.
        config_module = importlib.import_module("app.core.config")
        original_qwen_api_key = config_module.QWEN_API_KEY
        config_module.QWEN_API_KEY = "phase14-offline-test-placeholder"
        provider_module = importlib.import_module("app.agent.providers.qwen_provider")
        if provider_module.QWEN_API_KEY != config_module.QWEN_API_KEY:
            importlib.reload(provider_module)
        webhook_module = importlib.import_module("app.api.webhooks")
        original_webhook_engine = webhook_module._engine

        conversation_engine_module.CommerceResolver.resolve = record_resolution

        offline_provider = OfflineNLU(
            [
                nlu(
                    "product_search",
                    product_mention="Samsung Galaxy A54",
                ),
                nlu(
                    "variant_selection",
                    attributes={"storage": "256 غيغا", "color": "أسود"},
                ),
                nlu("order_create", quantity=1),
                nlu("order_confirm", confirmation_phrase=True),
            ]
        )
        webhook_module._engine = ConversationEngine(offline_provider, tool_registry)

        store, product, variant = seed_fixture(db)
        print(
            "DATABASE:",
            f"{source_engine.url.host or 'local-socket'}/{source_engine.url.database}",
            f"(temporary schema: {schema_name})",
        )
        print("STORE:", store.id)
        print("PRODUCT:", product.id, product.name)
        print("EXPECTED VARIANT:", variant.id, variant.attributes_json)
        print("NLU MODE: deterministic offline mock; no Qwen/network calls")

        active_step = "1 Product search"
        first_result = await send_webhook(
            webhook_module,
            db,
            "phase14-mid-1",
            "Samsung Galaxy A54",
        )
        conversation, reply = snapshot(db, SENDER_ID)
        metadata = conversation.metadata_json if conversation else {}
        search_ok = (
            first_result.get("count") == 1
            and metadata.get("commerce_stage") == "PRODUCT_SELECTED"
            and str(metadata.get("selected_product_id")) == str(product.id)
            and action_log[-1:] == ["EXECUTE_TOOL:search_products"]
        )
        set_step(
            active_step,
            {
                "webhook": first_result,
                "selected_product_id": metadata.get("selected_product_id"),
                "stage": metadata.get("commerce_stage"),
                "reply": reply,
            },
            search_ok,
        )

        active_step = "2 Attribute variant resolution"
        second_result = await send_webhook(
            webhook_module,
            db,
            "phase14-mid-2",
            "أريد التخزين 256 غيغا واللون أسود",
        )
        conversation, reply = snapshot(db, SENDER_ID)
        metadata = conversation.metadata_json if conversation else {}
        expected_price_text = f"السعر: {EXPECTED_PRICE:.1f} دج"
        expected_stock_text = "الكمية المتوفرة: 10"
        variant_ok = (
            second_result.get("count") == 1
            and str(metadata.get("selected_variant_id")) == str(variant.id)
            and metadata.get("commerce_stage") == "VARIANT_SELECTED"
            and action_log[-1:] == ["CALL_SERVICE:resolve_variant"]
            and reply is not None
            and expected_price_text in reply
            and expected_stock_text in reply
        )
        set_step(
            active_step,
            {
                "webhook": second_result,
                "selected_variant_id": metadata.get("selected_variant_id"),
                "stage": metadata.get("commerce_stage"),
                "expected_price": EXPECTED_PRICE,
                "expected_stock": 10,
                "reply": reply,
            },
            variant_ok,
        )

        active_step = "3 Draft creation"
        third_result = await send_webhook(
            webhook_module,
            db,
            "phase14-mid-3",
            "نبي واحد",
        )
        conversation, reply = snapshot(db, SENDER_ID)
        draft = conversation.active_draft_json if conversation else None
        db.rollback()
        stock_after_draft = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.store_id == store.id,
                InventoryItem.variant_id == variant.id,
            )
            .one()
            .quantity
        )
        draft_items = draft.get("items", []) if isinstance(draft, dict) else []
        draft_ok = (
            third_result.get("count") == 1
            and action_log[-1:] == ["CALL_SERVICE:create_draft"]
            and len(draft_items) == 1
            and str(draft_items[0].get("variant_id")) == str(variant.id)
            and int(draft_items[0].get("quantity", 0)) == 1
            and stock_after_draft == 10
        )
        set_step(
            active_step,
            {
                "webhook": third_result,
                "draft": draft,
                "stock": stock_after_draft,
                "reply": reply,
            },
            draft_ok,
        )

        active_step = "4 Order confirmation"
        fourth_mid = "phase14-mid-4"
        fourth_result = await send_webhook(
            webhook_module,
            db,
            fourth_mid,
            "نؤكد الطلب",
        )
        conversation, reply = snapshot(db, SENDER_ID)
        db.rollback()
        orders = (
            db.query(Order)
            .filter(Order.store_id == store.id)
            .all()
        )
        order = orders[0] if len(orders) == 1 else None
        order_items = (
            db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
            if order
            else []
        )
        stock_after_confirm = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.store_id == store.id,
                InventoryItem.variant_id == variant.id,
            )
            .one()
            .quantity
        )
        confirmation_ok = (
            fourth_result.get("count") == 1
            and action_log[-1:] == ["EXECUTE_TOOL:confirm_order"]
            and len(orders) == 1
            and order is not None
            and order.status == OrderStatus.CONFIRMED
            and len(order_items) == 1
            and order_items[0].variant_id == variant.id
            and order_items[0].quantity == 1
            and stock_after_confirm == 9
            and conversation is not None
            and conversation.active_draft_json is None
        )
        set_step(
            active_step,
            {
                "webhook": fourth_result,
                "order_id": order.id if order else None,
                "order_status": order.status if order else None,
                "order_items": [
                    {
                        "variant_id": item.variant_id,
                        "quantity": item.quantity,
                    }
                    for item in order_items
                ],
                "stock": stock_after_confirm,
                "active_draft_json": (
                    conversation.active_draft_json if conversation else None
                ),
                "reply": reply,
            },
            confirmation_ok,
        )

        active_step = "5 Duplicate webhook"
        duplicate_result = await send_webhook(
            webhook_module,
            db,
            fourth_mid,
            "نؤكد الطلب",
        )
        db.rollback()
        orders_after_duplicate = (
            db.query(Order)
            .filter(Order.store_id == store.id)
            .all()
        )
        stock_after_duplicate = (
            db.query(InventoryItem)
            .filter(
                InventoryItem.store_id == store.id,
                InventoryItem.variant_id == variant.id,
            )
            .one()
            .quantity
        )
        duplicate_ok = (
            duplicate_result.get("count") == 0
            and duplicate_result.get("skipped") == 1
            and len(orders_after_duplicate) == 1
            and stock_after_duplicate == 9
            and len(action_log) == 4
        )
        set_step(
            active_step,
            {
                "webhook": duplicate_result,
                "order_count": len(orders_after_duplicate),
                "stock": stock_after_duplicate,
                "resolver_calls": len(action_log),
            },
            duplicate_ok,
        )

    except Exception as exc:
        exception_text = f"{type(exc).__name__}: {exc}"
        STEPS[active_step]["actual"] = exception_text
        STEPS[active_step]["result"] = "FAIL"
        print(f"\nERROR during {active_step}: {exception_text}")
        traceback.print_exc()
        if db is not None:
            try:
                conversation, reply = snapshot(db, SENDER_ID)
                print_json(
                    "CONVERSATION STATE AT FAILURE",
                    {
                        "metadata_json": (
                            conversation.metadata_json if conversation else None
                        ),
                        "active_draft_json": (
                            conversation.active_draft_json if conversation else None
                        ),
                        "latest_bot_reply": reply,
                    },
                )
            except Exception:
                print("Could not query conversation state after the failure:")
                traceback.print_exc()
    finally:
        if db is not None:
            db.close()
        registry_module.SessionLocal = original_session_factory
        conversation_engine_module.CommerceResolver.resolve = original_resolve
        if webhook_module is not None and original_webhook_engine is not None:
            webhook_module._engine = original_webhook_engine
        if original_qwen_api_key is not None:
            try:
                importlib.import_module("app.core.config").QWEN_API_KEY = (
                    original_qwen_api_key
                )
            except Exception:
                cleanup_failed = True
                traceback.print_exc()
        if probe_engine is not None:
            probe_engine.dispose()
        if schema_created:
            try:
                with source_engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
                print(f"\nTemporary schema {schema_name} dropped.")
            except Exception:
                cleanup_failed = True
                print(f"\nFailed to drop temporary schema {schema_name}:")
                traceback.print_exc()

    print("\nSTEP | EXPECTED | ACTUAL | PASS/FAIL")
    for name, step in STEPS.items():
        print(
            f"{name} | {step['expected']} | {step['actual']} | {step['result']}"
        )
    return (
        not exception_text
        and not cleanup_failed
        and all(step["result"] == "PASS" for step in STEPS.values())
    )


if __name__ == "__main__":
    success = asyncio.run(run_e2e())
    raise SystemExit(0 if success else 1)
