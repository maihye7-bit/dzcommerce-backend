import asyncio
import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.api import webhooks
from app.agent.commerce_resolver import CommerceResolver, ResolutionResult
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers import qwen_provider
from app.agent.providers.base import LLMResponse
from app.agent.providers.mock_provider import MockLLMProvider
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.base import ToolResult
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.search_products import (
    SearchProductsTool,
    normalize_product_search_text,
)
from app.agent.tools.list_catalog import ListCatalogProductsTool
from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store


def add_product_inventory(db_session, store_id, quantity=5):
    product = Product(
        store_id=store_id,
        name="Context Test Product",
        base_price=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="Default",
        price_adjustment=Decimal("0"),
    )
    db_session.add(variant)
    db_session.flush()
    inventory = InventoryItem(
        store_id=store_id,
        variant_id=variant.id,
        quantity=quantity,
    )
    db_session.add(inventory)
    db_session.commit()
    return product, variant, inventory


class StaticProvider:
    def __init__(self, nlu: dict):
        self.nlu = nlu

    async def chat(self, messages, tools=None, system_prompt=None):
        return LLMResponse(content=json.dumps(self.nlu, ensure_ascii=False))


class ConversationFlowProvider:
    def __init__(self):
        self.responses = {
            "سامسونغ": {
                "intent": "product_search",
                "product_mention": "سامسونغ",
                "language": "ar",
            },
            "نعم": {
                "intent": "order_confirm",
                "confirmation_phrase": True,
                "language": "ar",
            },
            "سعر": {"intent": "product_details", "language": "ar"},
            "سومة سامسونغ": {"intent": "product_details", "language": "ar"},
            "شحال سامسونغ": {"intent": "product_details", "language": "ar"},
            "بشحال": {"intent": "product_details", "language": "ar"},
            "1": {
                "intent": "variant_selection",
                "attributes": {"size": "1"},
                "language": "ar",
            },
            "2": {
                "intent": "variant_selection",
                "attributes": {"size": "2"},
                "language": "ar",
            },
            "256GB أسود": {
                "intent": "variant_selection",
                "attributes": {"storage": "256GB", "color": "black"},
                "language": "ar",
            },
            "حبيت نكومندي واحد": {
                "intent": "order_create",
                "quantity": 1,
                "language": "ar",
            },
        }

    async def chat(self, messages, tools=None, system_prompt=None):
        response = dict(self.responses[messages[-1].content])
        response.setdefault("confidence", 0.95)
        return LLMResponse(
            content=json.dumps(
                response,
                ensure_ascii=False,
            )
        )


def make_conversation(
    db_session,
    metadata: dict | None = None,
    draft: dict | None = None,
) -> Conversation:
    store = Store(name="Context Test", slug=f"context-test-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(store_id=store.id, name="Context Test Customer")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="test",
        status=ConversationStatus.ACTIVE,
        metadata_json=metadata or {},
        active_draft_json=draft,
    )
    db_session.add(conversation)
    db_session.commit()
    return conversation


def make_engine(nlu: dict, registry: ToolRegistry | None = None) -> ConversationEngine:
    nlu = dict(nlu)
    nlu.setdefault("confidence", 0.95)
    return ConversationEngine(
        llm_provider=StaticProvider(nlu),
        tool_registry=registry or ToolRegistry(),
    )


def test_product_search_normalization_is_unicode_and_digit_conservative():
    assert normalize_product_search_text("أَسْوَد ١٢") == "اسود 12"
    assert normalize_product_search_text("Samsung") == "سامسونغ"
    assert normalize_product_search_text("سامسونج") == "سامسونغ"
    assert normalize_product_search_text("مقاس ة") == "مقاس ه"
    assert normalize_product_search_text("الأحذية") == "حذاء"
    assert normalize_product_search_text("حذاء") == normalize_product_search_text(
        "احذيه"
    )


def test_recent_dialogue_context_is_bounded_and_excludes_current_turn(db_session):
    conversation = make_conversation(db_session)
    base_time = datetime(2025, 1, 1)
    db_session.add_all(
        [
            Message(
                conversation_id=conversation.id,
                role=MessageRole.CUSTOMER,
                content="نحب Samsung noir",
                created_at=base_time,
            ),
            Message(
                conversation_id=conversation.id,
                role=MessageRole.AGENT,
                content="وجدت المنتج. أي لون تريد؟",
                created_at=base_time + timedelta(seconds=1),
            ),
            Message(
                conversation_id=conversation.id,
                role=MessageRole.CUSTOMER,
                content="شحال؟",
                created_at=base_time + timedelta(seconds=2),
            ),
            Message(
                conversation_id=conversation.id,
                role=MessageRole.CUSTOMER,
                content="اتصل بي على 05551234567",
                created_at=base_time + timedelta(seconds=3),
            ),
        ]
    )
    db_session.commit()

    context = ConversationEngine._recent_dialogue_context(
        db_session,
        conversation.id,
        "شحال؟",
    )

    assert len(context) == 2
    assert {item["content"] for item in context} == {
        "نحب Samsung noir",
        "وجدت المنتج. أي لون تريد؟",
    }
    assert all("05551234567" not in item["content"] for item in context)


def test_webhook_provider_uses_configured_agent_provider(monkeypatch):
    qwen_provider_class = webhooks.QwenLLMProvider
    monkeypatch.setattr(webhooks, "AGENT_PROVIDER", "mock")
    monkeypatch.setattr(
        webhooks,
        "QwenLLMProvider",
        lambda: pytest.fail("Qwen provider must not initialize in mock mode"),
    )

    assert isinstance(webhooks._build_llm_provider(), MockLLMProvider)
    monkeypatch.setattr(webhooks, "AGENT_PROVIDER", "qwen")
    monkeypatch.setattr(webhooks, "QwenLLMProvider", qwen_provider_class)
    monkeypatch.setattr(qwen_provider, "QWEN_API_KEY", "")
    with pytest.raises(ValueError, match="QWEN_API_KEY is not set"):
        webhooks._build_llm_provider()


async def process(engine, db_session, conversation, message: str):
    return await engine.process_message(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        channel="test",
        user_message=message,
    )


@pytest.mark.asyncio
async def test_yes_after_product_details_offer_requests_details(db_session):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(uuid.uuid4()),
            "selected_product_name": "Samsung",
            "last_question_type": "PRODUCT_DETAILS_OFFER",
        },
        draft={
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 100,
        },
    )
    product, _, inventory = add_product_inventory(
        db_session, conversation.store_id
    )
    conversation.metadata_json["selected_product_id"] = str(product.id)
    db_session.commit()
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"product": {"id": "db-id"}, "variants": [{"index": 1}]},
        )
    )

    result = await process(
        make_engine(
            {
                "intent": "order_confirm",
                "confirmation_phrase": True,
            },
            registry,
        ),
        db_session,
        conversation,
        "نعم",
    )

    assert registry.aexecute.await_args.kwargs["tool_name"] == "get_product_details"
    assert "سأعرض لك تفاصيل المنتج والخيارات المتاحة." in result["response"]
    assert "المخزون غير محدد" in result["response"]
    assert "السعر" not in result["response"]
    assert conversation.metadata_json["last_question_type"] == "VARIANT_SELECTION"
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0
    db_session.refresh(inventory)
    assert inventory.quantity == 5


@pytest.mark.asyncio
async def test_greeting_in_empty_conversation_gets_greeting_fallback(db_session):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()

    result = await process(
        make_engine({"intent": "greeting", "language": "ar"}, registry),
        db_session,
        conversation,
        "سلام",
    )

    assert result["response"] == "وعليكم السلام! كيف نقدر نعاونك؟"
    assert conversation.metadata_json["last_question_type"] is None
    registry.aexecute.assert_not_awaited()


@pytest.mark.asyncio
async def test_yes_without_active_draft_does_not_confirm(db_session):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(uuid.uuid4()),
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()

    result = await process(
        make_engine(
            {
                "intent": "order_confirm",
                "confirmation_phrase": True,
            },
            registry,
        ),
        db_session,
        conversation,
        "نعم",
    )

    registry.aexecute.assert_not_awaited()
    assert "confirm_order" not in result["response"]
    assert conversation.metadata_json["last_intent"] == "unknown"


@pytest.mark.asyncio
async def test_yes_after_order_confirmation_does_not_confirm(db_session):
    draft_id = str(uuid.uuid4())
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "confirmation_pending": {"draft_id": str(uuid.uuid4())},
        },
        draft={
            "draft_id": draft_id,
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 100,
            "shipping_info": {"phone": "0550123456", "wilaya": "الجزائر"},
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"order_number": "ORD-TEST"},
        )
    )

    result = await process(
        make_engine(
            {
                "intent": "order_confirm",
                "confirmation_phrase": True,
            },
            registry,
        ),
        db_session,
        conversation,
        "نعم",
    )

    registry.aexecute.assert_not_awaited()
    assert "غير مؤكد" in result["response"]


@pytest.mark.asyncio
async def test_yes_after_shipping_information_does_not_confirm(db_session):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "SHIPPING_INFO",
        },
        draft={
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 100,
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()

    await process(
        make_engine(
            {"intent": "order_confirm", "confirmation_phrase": True},
            registry,
        ),
        db_session,
        conversation,
        "نعم",
    )

    registry.aexecute.assert_not_awaited()
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0


@pytest.mark.asyncio
async def test_order_confirm_intent_without_affirmative_reply_is_rejected(db_session):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
        },
        draft={
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 100,
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()

    await process(
        make_engine(
            {"intent": "order_confirm", "confirmation_phrase": True},
            registry,
        ),
        db_session,
        conversation,
        "كم السعر؟",
    )

    registry.aexecute.assert_not_awaited()
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0


@pytest.mark.asyncio
async def test_real_confirmation_and_duplicate_do_not_deduct_twice(db_session):
    draft_id = str(uuid.uuid4())
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "confirmation_pending": {"draft_id": draft_id},
        },
        draft={"draft_id": draft_id, "items": [], "total_price": 100},
    )
    _, variant, inventory = add_product_inventory(
        db_session, conversation.store_id
    )
    conversation.active_draft_json = {
        "draft_id": draft_id,
        "items": [{"variant_id": str(variant.id), "quantity": 1}],
        "total_price": 100,
        "shipping_info": {"phone": "0550123456", "wilaya": "الجزائر"},
    }
    db_session.commit()

    registry = ToolRegistry()
    registry.register(ConfirmOrderTool())
    engine = make_engine(
        {"intent": "order_confirm", "confirmation_phrase": True},
        registry,
    )

    await process(engine, db_session, conversation, "أكد الطلب")
    db_session.expire_all()
    await process(engine, db_session, conversation, "أكد الطلب")
    db_session.expire_all()

    assert db_session.query(Order).filter(
        Order.store_id == conversation.store_id,
        Order.conversation_id == conversation.id,
        Order.status == OrderStatus.CONFIRMED,
    ).count() == 1
    db_session.refresh(inventory)
    assert inventory.quantity == 4


@pytest.mark.asyncio
async def test_successful_confirmation_stays_in_confirmed_stage(db_session):
    draft_id = str(uuid.uuid4())
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "confirmation_pending": {"draft_id": draft_id},
        },
        draft={
            "draft_id": draft_id,
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 100,
            "shipping_info": {"phone": "0550123456", "wilaya": "الجزائر"},
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"order_number": "ORD-TEST"},
        )
    )
    engine = make_engine(
        {"intent": "order_confirm", "confirmation_phrase": True},
        registry,
    )

    await process(engine, db_session, conversation, "أكد الطلب")
    conversation.active_draft_json = None
    db_session.add(
        Order(
            store_id=conversation.store_id,
            customer_id=conversation.customer_id,
            conversation_id=conversation.id,
            status=OrderStatus.CONFIRMED,
            subtotal=100,
            shipping_cost=0,
            total=100,
        )
    )
    db_session.commit()
    result = await process(engine, db_session, conversation, "أكد الطلب")

    registry.aexecute.assert_awaited_once()
    assert conversation.metadata_json["commerce_stage"] == "ORDER_CONFIRMED"
    assert result["response"] == "كيف يمكنني مساعدتك بعد تأكيد طلبك؟"


@pytest.mark.asyncio
async def test_failed_confirmation_does_not_mark_order_confirmed(db_session):
    draft_id = str(uuid.uuid4())
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "confirmation_pending": {"draft_id": draft_id},
        },
        draft={
            "draft_id": draft_id,
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 100,
            "shipping_info": {"phone": "0550123456", "wilaya": "الجزائر"},
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=False,
            error="confirmation failed",
            error_code="TOOL_ERROR",
        )
    )

    result = await process(
        make_engine(
            {"intent": "order_confirm", "confirmation_phrase": True},
            registry,
        ),
        db_session,
        conversation,
        "أكد الطلب",
    )

    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert conversation.active_draft_json["draft_id"] == draft_id
    assert conversation.metadata_json["confirmation_pending"] == {
        "draft_id": draft_id
    }
    registry.aexecute.assert_awaited_once()
    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:confirm_order"
    )


@pytest.mark.asyncio
async def test_current_product_search_overrides_stale_selection(db_session):
    old_product_id = uuid.uuid4()
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(old_product_id),
            "selected_product_name": "هاتف قديم",
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(success=True, data={"products": [], "count": 0})
    )

    await process(
        make_engine(
            {
                "intent": "product_search",
                "product_mention": "هاتف سامسونغ",
            },
            registry,
        ),
        db_session,
        conversation,
        "كم سعر هاتف سامسونغ؟",
    )

    assert registry.aexecute.await_args.kwargs["tool_name"] == "search_products"
    assert registry.aexecute.await_args.kwargs["arguments"] == {
        "query": "هاتف سامسونغ"
    }


@pytest.mark.asyncio
async def test_single_search_result_remains_auto_selected(db_session):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="Samsung Galaxy A54",
        base_price=Decimal("75000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()

    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    result = await process(
        make_engine(
            {
                "intent": "product_search",
                "product_mention": "Samsung Galaxy A54",
            },
            registry,
        ),
        db_session,
        conversation,
        "عندكم Samsung Galaxy A54؟",
    )

    assert result["response"] == (
        "وجدت المنتج: Samsung Galaxy A54. السعر: 75,000 دج. "
        "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟"
    )
    assert conversation.metadata_json["commerce_stage"] == "PRODUCT_SELECTED"
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert conversation.metadata_json["last_question_type"] == "PRODUCT_DETAILS_OFFER"


@pytest.mark.asyncio
async def test_single_search_result_uses_only_valid_price_from_tool_result(db_session):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={
                "products": [
                    {
                        "id": str(uuid.uuid4()),
                        "name": "Laptop Test",
                        "price": Decimal("12345.67"),
                    }
                ],
                "count": 1,
            },
        )
    )

    result = await process(
        make_engine(
            {"intent": "product_search", "product_mention": "Laptop"},
            registry,
        ),
        db_session,
        conversation,
        "عندكم Laptop؟",
    )

    assert result["response"] == (
        "وجدت المنتج: Laptop Test. السعر: 12,345.67 دج. "
        "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟"
    )
    assert "12,345.67 دج" in result["response"]
    assert str(registry.aexecute.await_args.kwargs["context"]["conversation_id"]) not in result["response"]


@pytest.mark.asyncio
async def test_single_search_result_without_price_does_not_invent_one(db_session):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"products": [{"name": "Laptop Test", "price": None}], "count": 1},
        )
    )

    result = await process(
        make_engine(
            {"intent": "product_search", "product_mention": "Laptop"},
            registry,
        ),
        db_session,
        conversation,
        "عندكم Laptop؟",
    )

    assert result["response"] == (
        "وجدت المنتج: Laptop Test. "
        "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟"
    )
    assert "السعر" not in result["response"]
    assert "دج" not in result["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("product", "expected_response"),
    [
        (
            {"name": None, "price": 1000},
            "وجدت منتجًا مطابقًا. السعر: 1,000 دج. "
            "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟",
        ),
        (
            {"name": "   ", "price": "غير محدد"},
            "وجدت منتجًا مطابقًا. "
            "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟",
        ),
    ],
)
async def test_single_search_result_with_invalid_name_or_price_omits_bad_facts(
    db_session,
    product,
    expected_response,
):
    conversation = make_conversation(db_session)
    internal_id = str(uuid.uuid4())
    product["id"] = internal_id
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"products": [product], "count": 1},
        )
    )

    result = await process(
        make_engine(
            {"intent": "product_search", "product_mention": "Laptop"},
            registry,
        ),
        db_session,
        conversation,
        "عندكم Laptop؟",
    )

    assert result["response"] == expected_response
    assert internal_id not in result["response"]
    assert "متوفر" not in result["response"]
    if product.get("price") == "غير محدد":
        assert "دج" not in result["response"]


@pytest.mark.asyncio
async def test_product_search_without_results_keeps_clear_search_response(db_session):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=False,
            error="No products found for 'Unknown'.",
            error_code="NO_RESULTS",
        )
    )

    result = await process(
        make_engine(
            {"intent": "product_search", "product_mention": "Unknown"},
            registry,
        ),
        db_session,
        conversation,
        "عندكم Unknown؟",
    )

    assert result["response"] == (
        "لم أجد هذا المنتج في نتائج المتجر. أرسل الموديل أو اطلب عرض قائمة المنتجات."
    )


@pytest.mark.asyncio
async def test_multiple_product_search_results_keep_selection_prompt(db_session):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={
                "products": [
                    {"id": str(uuid.uuid4()), "name": "Samsung A", "price": 1000},
                    {"id": str(uuid.uuid4()), "name": "Samsung B", "price": 2000},
                ],
                "count": 2,
            },
        )
    )

    result = await process(
        make_engine(
            {"intent": "product_search", "product_mention": "Samsung"},
            registry,
        ),
        db_session,
        conversation,
        "عندكم Samsung؟",
    )

    assert result["response"] == "وجدت عدة منتجات: Samsung A, Samsung B. أيّ منتج تقصد؟"


@pytest.mark.asyncio
async def test_catalog_browse_lists_only_active_products_from_the_current_store(
    db_session,
):
    conversation = make_conversation(db_session)
    listed_product = Product(
        store_id=conversation.store_id,
        name="Samsung",
        base_price=Decimal("120000.00"),
        is_active=True,
    )
    inactive_product = Product(
        store_id=conversation.store_id,
        name="Hidden phone",
        base_price=Decimal("1.00"),
        is_active=False,
    )
    other_store = Store(name="Other catalog", slug=f"other-{uuid.uuid4()}")
    db_session.add_all([listed_product, inactive_product, other_store])
    db_session.flush()
    foreign_product = Product(
        store_id=other_store.id,
        name="Foreign phone",
        base_price=Decimal("2.00"),
        is_active=True,
    )
    db_session.add(foreign_product)
    db_session.commit()

    registry = ToolRegistry()
    registry.register(ListCatalogProductsTool())
    engine = make_engine({"intent": "catalog_browse"}, registry)
    engine.reply_composer_enabled = False

    result = await process(engine, db_session, conversation, "وش عندكم منتجات؟")

    assert result["response"] == (
        "من المنتجات المسجلة في المتجر:\n"
        "Samsung — 120,000 دج\n"
        "أي منتج تحب تعرف تفاصيله؟"
    )
    assert "Hidden phone" not in result["response"]
    assert "Foreign phone" not in result["response"]
    assert conversation.metadata_json["commerce_stage"] == "PRODUCT_CANDIDATES"
    assert conversation.metadata_json["candidate_product_ids"] == [
        str(listed_product.id)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "expected_intent", "expected_action"),
    [
        (
            "الاحذية",
            "catalog_browse",
            "EXECUTE_TOOL:list_catalog_products",
        ),
        (
            "عندكم أحذية؟",
            "catalog_browse",
            "EXECUTE_TOOL:list_catalog_products",
        ),
        (
            "نحب نشوف الأحذية",
            "catalog_browse",
            "EXECUTE_TOOL:list_catalog_products",
        ),
        (
            "نشوف وش ممنتجات",
            "catalog_browse",
            "EXECUTE_TOOL:list_catalog_products",
        ),
        (
            "وريني الأحذية",
            "catalog_browse",
            "EXECUTE_TOOL:list_catalog_products",
        ),
        (
            "حذاء Nike رياضي",
            "product_search",
            "EXECUTE_TOOL:search_products",
        ),
        (
            "وريني Samsung A50",
            "product_search",
            "EXECUTE_TOOL:search_products",
        ),
    ],
)
async def test_arabic_category_browse_is_distinct_from_specific_product_search(
    db_session,
    message,
    expected_intent,
    expected_action,
):
    conversation = make_conversation(db_session)
    product, _, _ = add_product_inventory(db_session, conversation.store_id)
    product.name = "حذاء Nike رياضي"
    db_session.commit()

    registry = ToolRegistry()
    registry.register(ListCatalogProductsTool())
    registry.register(SearchProductsTool())
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(llm_provider=None, tool_registry=registry)
    engine.reply_composer_enabled = False

    async def local_nlu(user_message, state, **_kwargs):
        return engine._heuristic_nlu(user_message, state)

    engine._extract_nlu_via_qwen = local_nlu
    result = await process(engine, db_session, conversation, message)

    assert result["turn_diagnostics"]["intent"] == expected_intent
    assert result["turn_diagnostics"]["resolver_action"] == expected_action
    assert registry.aexecute.await_args.kwargs["tool_name"] == (
        expected_action.split(":", 1)[1]
    )


@pytest.mark.asyncio
async def test_arabic_specific_search_no_results_does_not_invent_product_name(
    db_session,
):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    engine = ConversationEngine(llm_provider=None, tool_registry=registry)
    engine.reply_composer_enabled = False

    async def local_nlu(user_message, state, **_kwargs):
        return engine._heuristic_nlu(user_message, state)

    engine._extract_nlu_via_qwen = local_nlu
    result = await process(engine, db_session, conversation, "حذاء Nike رياضي")

    assert result["turn_diagnostics"]["intent"] == "product_search"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:search_products"
    )
    assert "Nike" not in result["response"]
    assert "لم أجد" in result["response"]


@pytest.mark.asyncio
async def test_qwen_tool_loop_may_recover_no_match_with_resolver_gated_catalog(
    db_session,
):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="Samsung",
        base_price=Decimal("120000.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()

    class CatalogRecoveryProvider:
        def __init__(self):
            self.responses = [
                LLMResponse(
                    tool_calls=[
                        {
                            "name": "search_products",
                            "arguments": {"query": "Unlisted Model"},
                            "id": "search-call",
                        }
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(
                    tool_calls=[
                        {
                            "name": "list_catalog_products",
                            "arguments": {},
                            "id": "catalog-call",
                        }
                    ],
                    finish_reason="tool_calls",
                ),
                LLMResponse(
                    content=json.dumps(
                        {
                            "reply": (
                                "I found Samsung. Which product would you like details about?"
                            )
                        },
                        ensure_ascii=False,
                    )
                ),
            ]
            self.calls = []

        async def chat(self, messages, tools=None, system_prompt=None):
            self.calls.append((messages, tools))
            return self.responses.pop(0)

    provider = CatalogRecoveryProvider()
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.register(ListCatalogProductsTool())
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await process(
        engine,
        db_session,
        conversation,
        "Do you have Unlisted Model?",
    )

    assert result["response"] == (
        "I found Samsung. Which product would you like details about?"
    )
    assert len(provider.calls) == 3
    assert [tool["function"]["name"] for tool in provider.calls[1][1]] == [
        "search_products",
        "list_catalog_products",
    ]
    tool_result_message = provider.calls[2][0][-1]
    assert tool_result_message.role == "tool"
    tool_result = json.loads(tool_result_message.content)
    assert tool_result["success"] is True
    assert tool_result["products"] == [{"name": "Samsung", "price": 120000.0}]
    assert str(product.id) not in tool_result_message.content
    assert conversation.metadata_json["candidate_product_ids"] == [
        str(product.id)
    ]


@pytest.mark.asyncio
async def test_catalog_recovery_rejects_malformed_and_repeated_calls(db_session):
    conversation = make_conversation(db_session)

    class CountedCatalogTool(ListCatalogProductsTool):
        def __init__(self):
            self.execution_count = 0

        async def execute(self, *args, **kwargs):
            self.execution_count += 1
            return await super().execute(*args, **kwargs)

    class ToolCallProvider:
        def __init__(self, calls):
            self.responses = [
                LLMResponse(
                    tool_calls=[
                        {
                            "name": "list_catalog_products",
                            "arguments": arguments,
                            "id": f"catalog-{index}",
                        }
                    ],
                    finish_reason="tool_calls",
                )
                for index, arguments in enumerate(calls)
            ]
            self.call_count = 0

        async def chat(self, messages, tools=None, system_prompt=None):
            self.call_count += 1
            return self.responses.pop(0)

    catalog_tool = CountedCatalogTool()
    registry = ToolRegistry()
    registry.register(catalog_tool)
    provider = ToolCallProvider([{"unexpected": "argument"}])
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    rejected, reply = await engine._try_catalog_recovery(
        user_message="Find an item",
        language="en",
        db=db_session,
        store_id=conversation.store_id,
        conversation=conversation,
        customer_id=conversation.customer_id,
        channel="test",
    )

    assert rejected is None
    assert reply is None
    assert catalog_tool.execution_count == 0

    provider = ToolCallProvider([{}, {}])
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True
    recovered, reply = await engine._try_catalog_recovery(
        user_message="Find an item",
        language="en",
        db=db_session,
        store_id=conversation.store_id,
        conversation=conversation,
        customer_id=conversation.customer_id,
        channel="test",
    )

    assert recovered is not None
    assert recovered.success is True
    assert reply is None
    assert provider.call_count == 2
    assert catalog_tool.execution_count == 1


def test_order_for_a_different_named_product_does_not_use_stale_variant(db_session):
    conversation = make_conversation(db_session)
    selected_product = Product(
        store_id=conversation.store_id,
        name="Samsung Galaxy",
        base_price=Decimal("1000.00"),
        is_active=True,
    )
    requested_product = Product(
        store_id=conversation.store_id,
        name="iPhone",
        base_price=Decimal("2000.00"),
        is_active=True,
    )
    db_session.add_all([selected_product, requested_product])
    db_session.flush()
    selected_variant = ProductVariant(
        product_id=selected_product.id,
        name="Default",
        price_adjustment=Decimal("0.00"),
    )
    db_session.add(selected_variant)
    db_session.commit()

    decision = CommerceResolver(db_session).resolve(
        nlu_output={
            "intent": "order_create",
            "product_mention": "iPhone",
            "language": "ar",
        },
        current_state={
            "commerce_stage": "VARIANT_SELECTED",
            "selected_product_id": str(selected_product.id),
            "selected_variant_id": str(selected_variant.id),
        },
        store_id=conversation.store_id,
    )

    assert decision.allowed_action == "EXECUTE_TOOL:search_products"
    assert decision.resolved_entities["query"] == "iPhone"


@pytest.mark.asyncio
async def test_messenger_darija_product_price_and_purchase_flow_uses_database_facts(
    db_session,
):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="سامسونغ Galaxy Test",
        base_price=Decimal("100000.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="256GB أسود",
        price_adjustment=Decimal("2500.00"),
        attributes_json={"storage": "256GB", "color": "black"},
    )
    db_session.add(variant)
    db_session.flush()
    inventory = InventoryItem(
        store_id=conversation.store_id,
        variant_id=variant.id,
        quantity=3,
    )
    db_session.add(inventory)
    db_session.commit()

    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.register(GetProductDetailsTool())
    engine = ConversationEngine(
        llm_provider=ConversationFlowProvider(),
        tool_registry=registry,
    )

    search_result = await process(engine, db_session, conversation, "سامسونغ")
    assert search_result["response"] == (
        "وجدت المنتج: سامسونغ Galaxy Test. السعر: 100,000 دج. "
        "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟"
    )
    assert conversation.metadata_json["selected_product_id"] == str(product.id)

    details_result = await process(engine, db_session, conversation, "نعم")
    assert "سامسونغ Galaxy Test" in details_result["response"]
    assert "100,000 دج" in details_result["response"]
    assert "256GB أسود" in details_result["response"]
    assert "102,500 دج" in details_result["response"]
    assert "المتوفر: 3" in details_result["response"]
    assert conversation.metadata_json["last_question_type"] == "ORDER_CREATE_OFFER"
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert conversation.metadata_json["variant_index_map"]
    assert conversation.metadata_json["variant_index_map_product_id"] == str(product.id)

    price_result = await process(engine, db_session, conversation, "سعر")
    assert "سعر سامسونغ Galaxy Test: 100,000 دج." in price_result["response"]
    assert "102,500 دج" in price_result["response"]
    assert conversation.metadata_json["selected_product_id"] == str(product.id)

    darija_price_result = await process(
        engine,
        db_session,
        conversation,
        "سومة سامسونغ",
    )
    assert "100,000 دج" in darija_price_result["response"]
    assert "سامسونغ Galaxy Test" in darija_price_result["response"]

    for price_question in ("شحال سامسونغ", "بشحال"):
        price_result = await process(
            engine,
            db_session,
            conversation,
            price_question,
        )
        assert "100,000 دج" in price_result["response"]
        assert "سامسونغ Galaxy Test" in price_result["response"]

    purchase_result = await process(
        engine,
        db_session,
        conversation,
        "حبيت نكومندي واحد",
    )
    assert purchase_result["response"].startswith("تم حفظ مسودة الطلب:")
    assert "رقم هاتفك" in purchase_result["response"]
    assert "الولاية" in purchase_result["response"]
    assert conversation.active_draft_json["items"][0]["variant_id"] == str(variant.id)
    assert (
        conversation.metadata_json["last_question_type"]
        == "CUSTOMER_DELIVERY_INFO"
    )
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0

    assert conversation.metadata_json["variant_index_map"]
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0


@pytest.mark.asyncio
async def test_price_request_without_selected_product_asks_for_product(db_session):
    conversation = make_conversation(db_session)
    result = await process(
        make_engine({"intent": "unknown", "language": "ar"}),
        db_session,
        conversation,
        "سعر",
    )

    assert result["response"] == "ما هو المنتج الذي تبحث عنه؟"
    assert result["response"] != "إليك الخيارات المتاحة لهذا المنتج:"


@pytest.mark.asyncio
async def test_numeric_variant_selection_uses_exact_displayed_index(db_session):
    conversation = make_conversation(
        db_session,
        metadata={"commerce_stage": "PRODUCT_SELECTED"},
    )
    product = Product(
        store_id=conversation.store_id,
        name="Indexed Variant Phone",
        base_price=Decimal("50000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    first_variant = ProductVariant(
        product_id=product.id,
        name="128GB أزرق",
        price_adjustment=Decimal("1000"),
        attributes_json={"storage": "128GB", "color": "blue"},
        created_at=datetime(2024, 1, 1),
    )
    second_variant = ProductVariant(
        product_id=product.id,
        name="256GB أسود",
        price_adjustment=Decimal("2500"),
        attributes_json={"storage": "256GB", "color": "black"},
        created_at=datetime(2024, 1, 1) + timedelta(seconds=1),
    )
    db_session.add_all([first_variant, second_variant])
    db_session.flush()
    db_session.add_all(
        [
            InventoryItem(
                store_id=conversation.store_id,
                variant_id=first_variant.id,
                quantity=8,
            ),
            InventoryItem(
                store_id=conversation.store_id,
                variant_id=second_variant.id,
                quantity=3,
            ),
        ]
    )
    conversation.metadata_json.update(
        selected_product_id=str(product.id),
        selected_product_name=product.name,
        last_question_type="PRODUCT_DETAILS_OFFER",
    )
    db_session.commit()

    registry = ToolRegistry()
    registry.register(GetProductDetailsTool())
    engine = ConversationEngine(ConversationFlowProvider(), registry)
    details = await process(engine, db_session, conversation, "نعم")
    assert "1." in details["response"]
    assert "2." in details["response"]
    displayed_map = dict(conversation.metadata_json["variant_index_map"])
    assert conversation.metadata_json["variant_index_map_product_id"] == str(product.id)
    displayed_names = [
        line.split(".", 1)[1].strip()
        for line in details["response"].splitlines()
        if line.startswith(("1.", "2."))
    ]
    assert len(displayed_names) == 2

    for index in (1, 2):
        conversation.metadata_json["last_question_type"] = "VARIANT_SELECTION"
        conversation.metadata_json.pop("selected_variant_id", None)
        db_session.commit()
        selected = await process(engine, db_session, conversation, str(index))
        expected_variant_id = displayed_map[str(index)]
        assert conversation.metadata_json["selected_variant_id"] == expected_variant_id
        assert expected_variant_id == str(
            first_variant.id if index == 1 else second_variant.id
        )
        expected_price = "51000.0" if index == 1 else "52500.0"
        expected_stock = "الكمية المتوفرة: 8" if index == 1 else "الكمية المتوفرة: 3"
        assert expected_price in selected["response"]
        assert expected_stock in selected["response"]
        assert "ORDER_CREATE_OFFER" in conversation.metadata_json["last_question_type"]
        assert conversation.active_draft_json is None
        assert db_session.query(Order).filter(
            Order.conversation_id == conversation.id
        ).count() == 0


@pytest.mark.asyncio
async def test_unknown_message_preserves_variant_question_for_next_numeric_choice(
    db_session,
):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="Context Recovery Phone",
        base_price=Decimal("50000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    first_variant = ProductVariant(
        product_id=product.id,
        name="128GB Blue",
        price_adjustment=Decimal("0"),
        attributes_json={"storage": "128GB", "color": "blue"},
    )
    second_variant = ProductVariant(
        product_id=product.id,
        name="256GB Black",
        price_adjustment=Decimal("1000"),
        attributes_json={"storage": "256GB", "color": "black"},
    )
    db_session.add_all([first_variant, second_variant])
    db_session.flush()
    db_session.add_all(
        [
            InventoryItem(
                store_id=conversation.store_id,
                variant_id=first_variant.id,
                quantity=4,
            ),
            InventoryItem(
                store_id=conversation.store_id,
                variant_id=second_variant.id,
                quantity=3,
            ),
        ]
    )
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(second_variant.id),
        "last_question_type": "VARIANT_SELECTION",
        "variant_index_map": {
            "1": str(first_variant.id),
            "2": str(second_variant.id),
        },
        "variant_index_map_product_id": str(product.id),
    }
    db_session.commit()

    class UnknownThenNumericProvider:
        async def chat(self, messages, tools=None, system_prompt=None):
            message = messages[-1].content
            intent = "unknown" if message == "؟؟" else "variant_selection"
            return LLMResponse(
                content=json.dumps(
                    {"intent": intent, "language": "ar"},
                    ensure_ascii=False,
                )
            )

    engine = ConversationEngine(
        llm_provider=UnknownThenNumericProvider(),
        tool_registry=ToolRegistry(),
    )

    failed_result = await process(
        engine,
        db_session,
        conversation,
        "ما فهمتش",
    )

    assert "رقم الخيار" in failed_result["response"]
    assert conversation.metadata_json["last_question_type"] == "VARIANT_SELECTION"

    selection_result = await process(engine, db_session, conversation, "1")

    assert conversation.metadata_json["selected_variant_id"] == str(first_variant.id)
    assert f"تم اختيار {first_variant.name}." in selection_result["response"]
    assert conversation.metadata_json["last_question_type"] == "ORDER_CREATE_OFFER"


@pytest.mark.parametrize(
    "mapping_kind",
    ["missing", "stale", "foreign_product", "foreign_store"],
)
@pytest.mark.asyncio
async def test_invalid_numeric_variant_mapping_refreshes_options_without_selection(
    db_session,
    mapping_kind,
):
    conversation = make_conversation(
        db_session,
        metadata={"commerce_stage": "PRODUCT_SELECTED"},
    )
    product = Product(
        store_id=conversation.store_id,
        name="Current Indexed Product",
        base_price=Decimal("100"),
        is_active=True,
    )
    foreign_store = None
    other_store_id = conversation.store_id
    if mapping_kind == "foreign_store":
        foreign_store = Store(
            name="Foreign indexed store",
            slug=f"foreign-indexed-{uuid.uuid4()}",
        )
        db_session.add(foreign_store)
        db_session.flush()
        other_store_id = foreign_store.id
    other_product = Product(
        store_id=other_store_id,
        name="Different Indexed Product",
        base_price=Decimal("200"),
        is_active=True,
    )
    db_session.add_all([product, other_product])
    db_session.flush()
    current_variant = ProductVariant(
        product_id=product.id,
        name="Current Option",
        price_adjustment=Decimal("10"),
        attributes_json={"color": "blue"},
    )
    other_variant = ProductVariant(
        product_id=other_product.id,
        name="Foreign Product Option",
        price_adjustment=Decimal("20"),
        attributes_json={"color": "black"},
    )
    db_session.add_all([current_variant, other_variant])
    db_session.flush()
    db_session.add_all(
        [
            InventoryItem(
                store_id=conversation.store_id,
                variant_id=current_variant.id,
                quantity=4,
            ),
            InventoryItem(
                store_id=(
                    other_store_id
                    if mapping_kind == "foreign_store"
                    else conversation.store_id
                ),
                variant_id=other_variant.id,
                quantity=9,
            ),
        ]
    )
    metadata = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "last_question_type": "VARIANT_SELECTION",
    }
    if mapping_kind != "missing":
        metadata["variant_index_map"] = {"1": str(other_variant.id)}
        metadata["variant_index_map_product_id"] = (
            str(other_product.id)
            if mapping_kind == "stale"
            else str(product.id)
        )
    conversation.metadata_json = metadata
    db_session.commit()

    registry = ToolRegistry()
    registry.register(GetProductDetailsTool())
    result = await process(
        ConversationEngine(ConversationFlowProvider(), registry),
        db_session,
        conversation,
        "1",
    )

    assert (
        "اختر رقمًا من قائمة الخيارات الحالية." in result["response"]
        or "Choose a number from the current options list." in result["response"]
    )
    assert "Current Option" in result["response"]
    assert conversation.metadata_json.get("selected_variant_id") is None
    assert conversation.metadata_json["variant_index_map"] == {
        "1": str(current_variant.id)
    }
    assert conversation.metadata_json["variant_index_map_product_id"] == str(product.id)
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
async def test_number_without_pending_variant_question_does_not_select_variant(
    db_session,
):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(uuid.uuid4()),
            "last_question_type": "PRODUCT_DETAILS_OFFER",
            "variant_index_map": {"1": str(uuid.uuid4())},
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()
    result = await process(
        make_engine({"intent": "variant_selection", "attributes": {"size": "1"}}, registry),
        db_session,
        conversation,
        "1",
    )

    registry.aexecute.assert_not_awaited()
    assert result["response"] != "وجدت الاختيار المطلوب."
    assert conversation.metadata_json.get("selected_variant_id") is None


@pytest.mark.asyncio
async def test_product_details_do_not_read_inventory_from_another_store(db_session):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="Tenant Scoped Product",
        base_price=Decimal("50.00"),
        is_active=True,
    )
    foreign_store = Store(name="Foreign inventory store", slug=f"foreign-{uuid.uuid4()}")
    db_session.add_all([product, foreign_store])
    db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="Default",
        price_adjustment=Decimal("0.00"),
    )
    db_session.add(variant)
    db_session.flush()
    db_session.add(
        InventoryItem(
            store_id=foreign_store.id,
            variant_id=variant.id,
            quantity=999,
        )
    )
    db_session.commit()

    result = await GetProductDetailsTool().execute(
        store_id=conversation.store_id,
        arguments={"product_id": str(product.id)},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert result.success
    assert result.data["variants"][0]["stock_available"] is None


@pytest.mark.asyncio
async def test_unrecorded_stock_is_not_rendered_as_zero_or_drafted(db_session):
    conversation = make_conversation(
        db_session,
        metadata={"commerce_stage": "PRODUCT_SELECTED"},
    )
    product = Product(
        store_id=conversation.store_id,
        name="Stock Unknown Product",
        base_price=Decimal("50.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="256GB أسود",
        price_adjustment=Decimal("0.00"),
        attributes_json={"storage": "256GB", "color": "black"},
    )
    db_session.add(variant)
    db_session.flush()
    conversation.metadata_json["selected_product_id"] = str(product.id)
    conversation.metadata_json["selected_product_name"] = product.name
    db_session.commit()

    engine = ConversationEngine(
        llm_provider=ConversationFlowProvider(),
        tool_registry=ToolRegistry(),
    )
    selection_result = await process(
        engine,
        db_session,
        conversation,
        "256GB أسود",
    )

    assert "يجب التحقق من المخزون" in selection_result["response"]
    assert "الكمية المتوفرة: 0" not in selection_result["response"]

    purchase_result = await process(
        engine,
        db_session,
        conversation,
        "حبيت نكومندي واحد",
    )
    assert "مخزون هذا الخيار غير مسجل" in purchase_result["response"]
    assert conversation.active_draft_json is None
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0


@pytest.mark.asyncio
async def test_candidate_name_selects_only_a_current_tenant_candidate(db_session):
    conversation = make_conversation(db_session)
    candidate = Product(
        store_id=conversation.store_id,
        name="Samsung Galaxy A55",
        base_price=Decimal("95000"),
        is_active=True,
    )
    unrelated = Product(
        store_id=conversation.store_id,
        name="Samsung Galaxy S24",
        base_price=Decimal("180000"),
        is_active=True,
    )
    other_store = Store(name="Other store", slug=f"other-{uuid.uuid4()}")
    db_session.add_all([candidate, unrelated, other_store])
    db_session.flush()
    foreign_product = Product(
        store_id=other_store.id,
        name="Samsung Galaxy A55 Ultra",
        base_price=Decimal("120000"),
        is_active=True,
    )
    db_session.add(foreign_product)
    db_session.commit()
    conversation.metadata_json = {
        "candidate_product_ids": [str(candidate.id), str(unrelated.id)],
        "commerce_stage": "PRODUCT_CANDIDATES",
    }
    db_session.commit()

    registry = ToolRegistry()
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"product": {"id": str(candidate.id)}, "variants": []},
        )
    )
    await process(
        make_engine(
            {
                "intent": "product_details",
                "product_mention": "Galaxy A55",
                "language": "en",
            },
            registry,
        ),
        db_session,
        conversation,
        "Galaxy A55",
    )

    assert registry.aexecute.await_args.kwargs["tool_name"] == "get_product_details"
    assert registry.aexecute.await_args.kwargs["arguments"] == {
        "product_id": str(candidate.id)
    }
    assert conversation.metadata_json["selected_product_id"] == str(candidate.id)
    assert conversation.metadata_json["candidate_product_ids"] == []
    assert conversation.metadata_json["selected_product_id"] != str(foreign_product.id)


def test_candidates_prevent_legacy_product_fallback():
    conversation = type(
        "ConversationState",
        (),
        {
            "metadata_json": {
                "candidate_product_ids": [str(uuid.uuid4())],
                "last_product_id": str(uuid.uuid4()),
                "last_product_name": "Stale product",
                "selected_variant_id": str(uuid.uuid4()),
                "selected_attributes": {"color": "black"},
            },
            "active_draft_json": None,
        },
    )()

    state = ConversationEngine._normalize_current_state(
        conversation,
        uuid.uuid4(),
    )

    assert state["selected_product_id"] is None
    assert state["selected_product_name"] is None
    assert state["selected_variant_id"] is None
    assert state["selected_attributes"] == {}
    assert state["commerce_stage"] == "PRODUCT_CANDIDATES"


@pytest.mark.asyncio
async def test_search_tool_classifies_invalid_query_and_no_results(db_session):
    tool = SearchProductsTool()
    store_id = uuid.uuid4()

    invalid = await tool.execute(
        store_id=store_id,
        arguments={"query": "   "},
        context={"db": db_session},
    )
    no_results = await tool.execute(
        store_id=store_id,
        arguments={"query": "missing product"},
        context={"db": db_session},
    )

    assert invalid.error_code == "INVALID_QUERY"
    assert no_results.error_code == "NO_RESULTS"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["Samsung", "سامسونج", "سامسونغ"])
async def test_search_tool_normalizes_samsung_spellings_with_tenant_isolation(
    db_session,
    query,
):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="سامسونغ Galaxy A54",
        base_price=Decimal("75000"),
        is_active=True,
    )
    other_store = Store(name="Other Store", slug=f"other-{uuid.uuid4()}")
    db_session.add_all([product, other_store])
    db_session.flush()
    foreign_product = Product(
        store_id=other_store.id,
        name="Samsung Galaxy A54",
        base_price=Decimal("1"),
        is_active=True,
    )
    db_session.add(foreign_product)
    db_session.commit()

    result = await SearchProductsTool().execute(
        store_id=conversation.store_id,
        arguments={"query": query},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert result.success is True
    assert result.data["count"] == 1
    assert result.data["products"][0]["id"] == str(product.id)
    assert result.data["products"][0]["name"] == "سامسونغ Galaxy A54"
    assert result.data["products"][0]["id"] != str(foreign_product.id)


@pytest.mark.asyncio
async def test_search_tool_does_not_invent_similar_product(db_session):
    conversation = make_conversation(db_session)
    db_session.add(
        Product(
            store_id=conversation.store_id,
            name="سامسونغ Galaxy A54",
            base_price=Decimal("75000"),
            is_active=True,
        )
    )
    db_session.commit()

    result = await SearchProductsTool().execute(
        store_id=conversation.store_id,
        arguments={"query": "Completely Unrelated Item"},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert result.success is False
    assert result.error_code == "NO_RESULTS"


@pytest.mark.asyncio
async def test_repeated_product_search_uses_shorter_verified_reply(db_session):
    conversation = make_conversation(db_session)
    product = Product(
        store_id=conversation.store_id,
        name="Samsung Galaxy A54",
        base_price=Decimal("75000"),
        is_active=True,
    )
    db_session.add(product)
    db_session.commit()
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    engine = make_engine(
        {
            "intent": "product_search",
            "product_mention": "Samsung Galaxy A54",
        },
        registry,
    )

    first = await process(
        engine,
        db_session,
        conversation,
        "عندكم Samsung Galaxy A54؟",
    )
    second = await process(
        engine,
        db_session,
        conversation,
        "عندكم Samsung Galaxy A54؟",
    )

    assert first["response"] != second["response"]
    for response in (first["response"], second["response"]):
        assert "Samsung Galaxy A54" in response
        assert "75,000 دج" in response


@pytest.mark.asyncio
async def test_repeated_unclear_message_rotates_clarification(db_session):
    conversation = make_conversation(
        db_session,
        metadata={"last_question_type": "VARIANT_SELECTION"},
    )
    engine = make_engine({"intent": "unknown"}, ToolRegistry())

    first = await process(engine, db_session, conversation, "???")
    second = await process(engine, db_session, conversation, "???")

    assert first["response"] != second["response"]


@pytest.mark.asyncio
async def test_no_result_search_preserves_existing_product_and_variant_state(db_session):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(uuid.uuid4()),
            "selected_product_name": "Old product",
            "last_product_id": str(uuid.uuid4()),
            "last_product_name": "Legacy old product",
            "selected_variant_id": str(uuid.uuid4()),
            "candidate_product_ids": [],
        },
    )

    result = await SearchProductsTool().execute(
        store_id=conversation.store_id,
        arguments={"query": "no matching product"},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert result.error_code == "NO_RESULTS"
    assert conversation.metadata_json["commerce_stage"] == "PRODUCT_SELECTED"
    assert conversation.metadata_json["selected_product_id"]
    assert conversation.metadata_json["selected_product_name"] == "Old product"
    assert conversation.metadata_json["last_product_id"]
    assert conversation.metadata_json["last_product_name"] == "Legacy old product"
    assert conversation.metadata_json["selected_variant_id"]


@pytest.mark.asyncio
async def test_search_tool_propagates_database_error():
    class BrokenSession:
        def query(self, _model):
            raise SQLAlchemyError("database unavailable")

    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        await SearchProductsTool().execute(
            store_id=uuid.uuid4(),
            arguments={"query": "Samsung"},
            context={"db": BrokenSession()},
        )


@pytest.mark.asyncio
async def test_unverified_delivery_question_gets_safe_store_policy_reply(db_session):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()

    result = await process(
        make_engine({"intent": "unknown", "language": "ar"}, registry),
        db_session,
        conversation,
        "تكلفة التوصيل لسطيف قداه؟",
    )

    assert "ما عنديش معلومة موثقة" in result["response"]
    assert "ما نحبش نخمنها" in result["response"]
    assert "سطيف" not in result["response"]
    assert registry.aexecute.await_count == 0


@pytest.mark.asyncio
async def test_unrecognized_reply_uses_current_variant_question(db_session):
    conversation = make_conversation(
        db_session,
        metadata={
            "commerce_stage": "PRODUCT_SELECTED",
            "selected_product_id": str(uuid.uuid4()),
            "last_question_type": "VARIANT_SELECTION",
        },
    )
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()

    result = await process(
        make_engine({"intent": "unknown", "language": "ar"}, registry),
        db_session,
        conversation,
        "ما فهمتش",
    )

    assert "رقم الخيار" in result["response"]
    assert "ما فهمتش الاختيار" in result["response"]
    assert conversation.metadata_json["last_question_type"] == "VARIANT_SELECTION"
    registry.aexecute.assert_not_awaited()


def test_unsupported_store_policy_topics_are_detected_without_invented_values():
    detect = ConversationEngine._detect_unsupported_store_policy

    assert detect("livraison l Setif ch7al?") == "delivery"
    assert detect("عندكم توصيل؟") == "delivery"
    assert detect("وين عنوان محلكم؟") == "address"
    assert detect("قداه الضمان؟") == "warranty"
    assert detect("هذا الهاتف أصلي؟") == "authenticity"
    assert detect("ما هي سياسة الإرجاع؟") == "returns"
    assert detect("بدل التوصيل", {"active_draft_json": {"items": [{}]}}) is None
    assert detect("لو سمحت أضف اللون الأسود للطلب", {"active_draft_json": {"items": [{}]}}) is None

    response = ConversationEngine._unsupported_policy_response(
        "delivery",
        "ar",
    )
    assert "موثقة" in response
    assert not any(character.isdigit() for character in response)


def test_reply_renderer_omits_invalid_price_and_stock_facts():
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    response = asyncio.run(
        engine._generate_localized_final_text(
            {
                "product": {
                    "name": "Samsung",
                    "base_price": float("nan"),
                },
                "variants": [
                    {
                        "index": 1,
                        "name": "Black",
                        "final_price": float("inf"),
                        "stock_available": -1,
                        "attributes": {
                            "color": "black",
                            "variant_id": str(uuid.uuid4()),
                        },
                    }
                ],
            },
            "اختر أحد الخيارات المتاحة.",
            "اعرض الخيارات",
            "ar",
            "product_details",
        )
    )

    assert "Black" in response
    assert "black" in response
    assert "variant_id" not in response
    assert "nan" not in response.casefold()
    assert "inf" not in response.casefold()
    assert "-1" not in response
    assert "السعر الأساسي" not in response


def test_draft_reply_does_not_substitute_zero_for_missing_total():
    engine = ConversationEngine(llm_provider=None, tool_registry=ToolRegistry())
    response = asyncio.run(
        engine._generate_localized_final_text(
            {"draft_summary": {}},
            "",
            "جهز الطلب",
            "ar",
            "order_create",
        )
    )

    assert "تم حفظ مسودة الطلب" in response
    assert "0 دج" not in response
    assert "راجع المجموع" in response


@pytest.mark.asyncio
async def test_engine_rejects_unregistered_resolver_action(db_session, monkeypatch):
    conversation = make_conversation(db_session)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()
    monkeypatch.setattr(
        CommerceResolver,
        "resolve",
        lambda *args, **kwargs: ResolutionResult(
            allowed_action="CALL_SERVICE:unregistered",
        ),
    )

    result = await process(
        make_engine({"intent": "unknown", "language": "ar"}, registry),
        db_session,
        conversation,
        "؟؟",
    )

    assert result["response"] == (
        "عذراً، لم أتمكن من إكمال طلبك حالياً. يرجى المحاولة مرة أخرى لاحقاً."
    )
    registry.aexecute.assert_not_awaited()
