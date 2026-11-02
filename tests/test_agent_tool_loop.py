import asyncio
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import sessionmaker

from app.agent.conversation_engine import ConversationEngine
from app.agent.commerce_resolver import ResolutionResult
from app.agent.providers.base import LLMResponse
from app.agent.tools.base import ToolResult
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.list_catalog import ListCatalogProductsTool
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.update_order_draft import UpdateOrderDraftTool
from app.agent.reply_composer import ReplyComposer
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


class ScriptedToolProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.calls.append((messages, tools))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def tool_call(name, arguments, call_id=None):
    return LLMResponse(
        tool_calls=[
            {
                "id": call_id or f"call-{uuid.uuid4()}",
                "name": name,
                "arguments": arguments,
            }
        ],
        finish_reason="tool_calls",
    )


def make_fixture(db_session, *, with_draft=False):
    store = Store(name="Agentic test store", slug=f"agentic-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(store_id=store.id, name="Agentic test customer")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="test",
        status=ConversationStatus.ACTIVE,
        metadata_json={},
        active_draft_json=(
            {
                "items": [
                    {
                        "variant_id": str(uuid.uuid4()),
                        "product_name": "Samsung Galaxy",
                        "variant_name": "Black",
                        "quantity": 1,
                        "unit_price": 100,
                        "line_total": 100,
                    }
                ],
                "total_price": 100,
            }
            if with_draft
            else None
        ),
    )
    db_session.add(conversation)
    db_session.flush()
    product = Product(
        store_id=store.id,
        name="Samsung Galaxy",
        description="Test product",
        base_price=Decimal("100.00"),
        is_active=True,
    )
    db_session.add(product)
    db_session.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="Black",
        price_adjustment=Decimal("0.00"),
        attributes_json={"color": "black"},
    )
    db_session.add(variant)
    db_session.flush()
    db_session.add(
        InventoryItem(
            store_id=store.id,
            variant_id=variant.id,
            quantity=5,
        )
    )
    db_session.commit()
    return store, customer, conversation, product, variant


def make_registry():
    registry = ToolRegistry()
    for tool in (
        SearchProductsTool(),
        GetProductDetailsTool(),
        CheckInventoryTool(),
        ListCatalogProductsTool(),
        CreateOrderDraftTool(),
        UpdateOrderDraftTool(),
        ConfirmOrderTool(),
    ):
        registry.register(tool)
    return registry


async def run_turn(engine, db_session, conversation, text):
    return await engine.process_message(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        channel="test",
        user_message=text,
    )


def mark_conversation_order_confirmed(db_session, conversation, product):
    conversation.metadata_json = {
        "commerce_stage": "ORDER_CONFIRMED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "last_question_type": None,
    }
    conversation.active_draft_json = None
    db_session.add(
        Order(
            store_id=conversation.store_id,
            customer_id=conversation.customer_id,
            conversation_id=conversation.id,
            status=OrderStatus.CONFIRMED,
            subtotal=Decimal("100.00"),
            shipping_cost=Decimal("0.00"),
            total=Decimal("100.00"),
            shipping_address="{}",
        )
    )
    db_session.commit()


def prepare_pending_confirmation(conversation, product, variant):
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
        "last_question_type": "ORDER_CONFIRMATION",
    }
    conversation.active_draft_json = {
        "items": [
            {
                "variant_id": str(variant.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "quantity": 1,
                "unit_price": 100,
                "line_total": 100,
                "available_stock": 5,
            }
        ],
        "total_price": 100,
        "shipping_info": {},
    }


def test_agent_facts_expose_verified_variant_choices_without_internal_ids(db_session):
    store, _, _, product, variant = make_fixture(db_session)
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())

    facts = engine._agent_verified_state_facts(
        db_session,
        store.id,
        {
            "selected_product_id": str(product.id),
            "selected_variant_id": str(variant.id),
            "variant_index_map": {"1": str(variant.id)},
            "variant_index_map_product_id": str(product.id),
        },
    )

    assert facts["available_variants"] == [
        {
            "index": 1,
            "name": "Black",
            "attributes": {"color": "black"},
            "price": 100.0,
            "stock_available": 5,
        }
    ]
    assert str(product.id) not in json.dumps(facts)
    assert str(variant.id) not in json.dumps(facts)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirmation",
    [
        "اكدلي الطلب",
        "اكدلي",
        "اكده",
        "اكدهالي",
        "اكد الطلبية",
        "اكدهولنا",
        "أكدلهم",
        "confirme",
        "confirme la commande",
        "اكد",
        "أكد",
        "نعم",
    ],
)
async def test_attached_pronoun_confirmation_creates_order_and_one_reply(
    db_session,
    confirmation,
    caplog,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    prepare_pending_confirmation(conversation, product, variant)
    db_session.commit()
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = False
    caplog.set_level("INFO", logger="app.agent.conversation_engine")
    previous_agent_messages = db_session.query(Message).filter(
        Message.conversation_id == conversation.id,
        Message.role == MessageRole.AGENT,
    ).count()

    result = await run_turn(engine, db_session, conversation, confirmation)

    assert "ORD-" in result["response"]
    assert result["turn_diagnostics"]["intent"] == "order_confirm"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:confirm_order"
    )
    if not ConversationEngine._is_bare_affirmative(confirmation):
        assert provider.calls == []
    assert result["turn_diagnostics"]["response_candidates"] == 1
    assert result["turn_diagnostics"]["responses_returned"] == 1
    assert "conversation_turn" in caplog.text
    assert "intent=order_confirm" in caplog.text
    assert "resolver_action=EXECUTE_TOOL:confirm_order" in caplog.text
    assert "response_candidates=1 responses_returned=1" in caplog.text
    assert confirmation not in caplog.text
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id,
        Order.store_id == store.id,
        Order.status == OrderStatus.CONFIRMED,
    ).count() == 1
    inventory = db_session.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one()
    assert inventory.quantity == 4
    assert db_session.query(Message).filter(
        Message.conversation_id == conversation.id,
        Message.role == MessageRole.AGENT,
    ).count() == previous_agent_messages + 1
    assert conversation.active_draft_json is None


def test_confirmation_normalization_splits_pronouns_and_command_objects():
    normalize = ConversationEngine.normalize_confirmation

    assert normalize("اكدلي الطلب") == "اكد"
    assert normalize("اكده") == "اكد"
    assert normalize("اكدهالي") == "اكد"
    assert normalize("اكدهولنا") == "اكد"
    assert normalize("أكدلهم") == "اكد"
    assert normalize("اكد الطلبية") == "اكد"
    assert normalize("confirme la commande") == "confirme"
    assert not ConversationEngine._is_order_confirmation_reply(
        "طيب اكمل الطلب"
    )


@pytest.mark.asyncio
async def test_post_confirmation_thanks_gets_short_greeting(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    mark_conversation_order_confirmed(db_session, conversation, product)
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "شكرا")

    assert result["response"] == "العفو! كيف نقدر نعاونك؟"
    assert "تم تأكيد طلبك" not in result["response"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_post_confirmation_new_order_resets_conversation_state(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    mark_conversation_order_confirmed(db_session, conversation, product)
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "حبيت ندير طلب اخر")

    assert "طلباً جديداً" in result["response"]
    assert "المنتج" in result["response"]
    assert conversation.metadata_json["commerce_stage"] == "EMPTY"
    assert conversation.metadata_json.get("selected_product_id") is None
    assert conversation.active_draft_json is None
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 1


@pytest.mark.asyncio
async def test_post_confirmation_edit_explains_order_is_locked(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    mark_conversation_order_confirmed(db_session, conversation, product)
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "حبيت نغير الطلب")

    assert "لا يمكن تعديله" in result["response"]
    assert "طلباً جديداً" in result["response"]
    assert provider.calls == []


@pytest.mark.asyncio
async def test_post_confirmation_unclear_message_asks_how_to_help(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    mark_conversation_order_confirmed(db_session, conversation, product)
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "؟؟")

    assert result["response"] == "كيف يمكنني مساعدتك بعد تأكيد طلبك؟"


@pytest.mark.asyncio
async def test_post_confirmation_product_name_starts_new_search(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    mark_conversation_order_confirmed(db_session, conversation, product)
    registry = make_registry()
    executed_tools = []
    original_execute = registry.aexecute

    async def capture_execute(*, tool_name, arguments, context):
        executed_tools.append(tool_name)
        return await original_execute(
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

    registry.aexecute = capture_execute
    engine = ConversationEngine(ScriptedToolProvider([]), registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "سامسونغ")

    assert executed_tools == ["search_products"]
    assert "Samsung Galaxy" in result["response"]
    assert conversation.metadata_json["commerce_stage"] in {
        "PRODUCT_SELECTED",
        "PRODUCT_CANDIDATES",
    }


@pytest.mark.asyncio
async def test_agent_tool_loop_executes_one_resolver_authorized_call(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            LLMResponse(
                content=(
                    "I found Samsung Galaxy. Price: 100 DZD. "
                    "Would you like to see its options?"
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert result["response"] == (
        "I found Samsung Galaxy. Price: 100 DZD. "
        "Would you like to see its options?"
    )
    assert len(provider.calls) == 2
    assert [entry["function"]["name"] for entry in provider.calls[0][1]] == [
        "search_products",
        "get_product_details",
        "check_inventory",
        "list_catalog_products",
        "create_order_draft",
        "update_order_draft",
        "confirm_order",
    ]
    tool_result = provider.calls[1][0][-1]
    assert tool_result.role == "tool"
    assert "Samsung Galaxy" in tool_result.content
    assert str(product.id) not in tool_result.content


@pytest.mark.asyncio
async def test_agent_loop_uses_verified_fallback_for_corrupt_generated_text(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            LLMResponse(content="商品価格は100円です"),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "ابحث عن Samsung")

    assert "Samsung Galaxy" in result["response"]
    assert "100" in result["response"]
    assert "商品" not in result["response"]
    assert "円" not in result["response"]
    assert str(product.id) not in result["response"]


@pytest.mark.asyncio
async def test_arabic_customer_does_not_receive_english_agent_reply(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            LLMResponse(
                content=(
                    "I found Samsung Galaxy. Price: 100 DZD. "
                    "Would you like its details?"
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "ابحث عن Samsung")

    assert "Samsung Galaxy" in result["response"]
    assert any("\u0600" <= char <= "\u06ff" for char in result["response"])
    assert "I found" not in result["response"]
    assert str(product.id) not in result["response"]


@pytest.mark.asyncio
async def test_clear_product_lookup_routes_to_resolver_if_agent_only_clarifies(
    db_session,
):
    _, _, conversation, product, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [LLMResponse(content="ما هو المنتج الذي تبحث عنه؟")]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "عندكم Samsung Galaxy؟",
    )

    assert "Samsung Galaxy" in result["response"]
    assert "100" in result["response"]
    assert conversation.metadata_json["selected_product_id"] == str(product.id)


@pytest.mark.asyncio
async def test_get_product_details_preserves_resolved_variant_selection(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    db_session.flush()

    result = await GetProductDetailsTool().execute(
        store_id=store.id,
        arguments={"product_id": str(product.id)},
        context={
            "db": db_session,
            "conversation_id": conversation.id,
        },
    )

    assert result.success is True
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)


@pytest.mark.asyncio
async def test_single_variant_purchase_creates_draft_without_customer_index(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.flush()

    provider = ScriptedToolProvider(
        [
            tool_call("create_order_draft", {"quantity": 1}, "create-draft"),
            LLMResponse(content="تم حفظ مسودة الطلب. المجموع: 100 دج. هل تؤكد الطلب؟"),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "حبيت نشري هذا")

    assert "تم حفظ مسودة الطلب" in result["response"]
    assert "100" in result["response"]
    assert "سعر" not in result["response"]
    assert conversation.active_draft_json["items"][0]["variant_id"] == str(variant.id)
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"
    assert conversation.metadata_json["variant_index_map_product_id"] == str(product.id)


@pytest.mark.asyncio
async def test_clear_purchase_intent_routes_to_resolver_if_agent_skips_tool(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.flush()
    provider = ScriptedToolProvider(
        [LLMResponse(content="ما فهمت طلبك. وضح لي أكثر.")]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "حبيت نشري واحد")

    assert conversation.active_draft_json["items"][0]["variant_id"] == str(variant.id)
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert "تم حفظ مسودة الطلب" in result["response"]


@pytest.mark.asyncio
async def test_bare_yes_routes_to_pending_product_details_question(db_session):
    store, _, conversation, product, _ = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "last_question_type": "PRODUCT_DETAILS_OFFER",
    }
    db_session.flush()
    provider = ScriptedToolProvider(
        [LLMResponse(content="I don't understand. Could you clarify?")]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "ايه")

    assert "Samsung Galaxy" in result["response"]
    assert "Black" in result["response"]
    assert conversation.metadata_json["variant_index_map"]
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
async def test_agent_purchase_resolves_selected_variant_without_existing_index_map(
    db_session,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    db_session.flush()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    state = engine._normalize_current_state(conversation, store.id)

    execution = await engine._execute_agent_tool_call(
        tool_name="create_order_draft",
        arguments={"quantity": 1},
        user_message="I want to buy this",
        language="en",
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation=conversation,
        channel="test",
        state=state,
    )

    assert execution is not None
    _, _, tool_name, tool_result = execution
    assert tool_name == "create_order_draft"
    assert tool_result.success is True
    assert conversation.active_draft_json["items"][0]["variant_id"] == str(variant.id)


def test_agent_reply_validator_rejects_placeholders_and_foreign_scripts():
    verified_facts = {
        "products": [{"name": "Samsung Galaxy", "price": 100}],
    }

    assert not ReplyComposer.is_safe_agent_reply(
        "سامسونغ Samsung Galaxy [السعر هنا]",
        "ar",
        verified_facts,
    )
    assert not ReplyComposer.is_safe_agent_reply(
        "سامسونغ Samsung Galaxy 価格は100 DZDです",
        "ar",
        verified_facts,
    )
    assert not ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy is available for you",
        "ar",
        verified_facts,
    )
    assert ReplyComposer.is_safe_agent_reply(
        "وجدت Samsung Galaxy.",
        "ar",
        verified_facts,
    )


@pytest.mark.asyncio
async def test_already_confirmed_without_active_draft_is_not_reported_as_new_confirmation(
    db_session,
):
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    fallback = await engine._agent_loop_safe_fallback(
        "ar",
        "نعم",
        ResolutionResult(
            allowed_action="EXECUTE_TOOL:confirm_order",
            context_updates={},
            response_hint="",
        ),
        {"intent": "order_confirm"},
        "confirm_order",
        ToolResult(
            success=True,
            data={"already_confirmed": True},
        ),
    )

    assert "لا توجد مسودة نشطة" in fallback["response"]
    assert "تم تأكيد طلبك بنجاح" not in fallback["response"]


@pytest.mark.asyncio
async def test_agent_tool_loop_supports_two_tool_rounds(db_session):
    _, _, conversation, product, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            tool_call("get_product_details", {}),
            LLMResponse(
                content=(
                    "Samsung Galaxy has Black option 1: 100 DZD, stock 5."
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert result["response"] == (
        "Samsung Galaxy has Black option 1: 100 DZD, stock 5."
    )
    assert len(provider.calls) == 3
    details_result = provider.calls[2][0][-1]
    assert details_result.role == "tool"
    assert "variant_id_map" not in details_result.content
    assert str(product.id) not in details_result.content


@pytest.mark.asyncio
async def test_agent_loop_resolves_variant_before_inventory_lookup(db_session):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call("get_product_details", {}, "details"),
            tool_call(
                "check_inventory",
                {"variant_index": 1, "quantity": 2},
                "inventory",
            ),
            LLMResponse(
                content="Samsung Galaxy option 1 has 5 in stock for requested 2."
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Is option one available for two?",
    )

    assert "5 in stock" in result["response"]
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    inventory_result = provider.calls[2][0][-1]
    assert inventory_result.role == "tool"
    assert str(variant.id) not in inventory_result.content
    assert json.loads(inventory_result.content)["available_quantity"] == 5


@pytest.mark.asyncio
async def test_agent_loop_draft_then_confirmation_uses_existing_tools(db_session):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call("get_product_details", {}, "details"),
            tool_call(
                "create_order_draft",
                {"variant_index": 1, "quantity": 1},
                "draft",
            ),
            LLMResponse(content="Draft saved. Total: 100 DZD. Confirm if you wish."),
            tool_call("confirm_order", {}, "confirm"),
            LLMResponse(content="Samsung Galaxy order confirmed for 100 DZD."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    draft_result = await run_turn(
        engine,
        db_session,
        conversation,
        "Prepare one Samsung Galaxy",
    )
    assert "100" in draft_result["response"]
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"
    assert conversation.active_draft_json["items"]

    confirm_result = await run_turn(
        engine,
        db_session,
        conversation,
        "yes",
    )
    assert "تم تأكيد طلبك بنجاح" in confirm_result["response"]
    assert conversation.active_draft_json is None
    order = (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .one()
    )
    assert order.status == OrderStatus.CONFIRMED
    inventory = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.variant_id == variant.id)
        .one()
    )
    assert inventory.quantity == 4


@pytest.mark.asyncio
async def test_agent_usage_does_not_rollback_order_confirmation_on_sqlite(db_engine):
    db_session = sessionmaker(bind=db_engine, expire_on_commit=False)()
    try:
        _, _, conversation, product, variant = make_fixture(db_session)
        conversation.metadata_json = {
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "selected_product_id": str(product.id),
        }
        conversation.active_draft_json = {
            "items": [
                {
                    "variant_id": str(variant.id),
                    "product_name": product.name,
                    "variant_name": variant.name,
                    "quantity": 1,
                    "unit_price": 100,
                    "line_total": 100,
                }
            ],
            "total_price": 100,
        }
        db_session.commit()
        usage = {
            "model": "qwen/qwen-2.5-72b-instruct",
            "input_tokens": 10,
            "output_tokens": 5,
            "latency_ms": 1,
        }
        provider = ScriptedToolProvider(
            [
                LLMResponse(
                    tool_calls=[
                        {
                            "id": "confirm",
                            "name": "confirm_order",
                            "arguments": {},
                        }
                    ],
                    finish_reason="tool_calls",
                    usage=usage,
                ),
                LLMResponse(
                    content="Samsung Galaxy order confirmed for 100 DZD.",
                    usage=usage,
                ),
            ]
        )
        engine = ConversationEngine(provider, make_registry())
        engine.agent_tool_loop_enabled = True

        result = await run_turn(engine, db_session, conversation, "نعم")

        assert "رقم الطلب" in result["response"]
        assert conversation.active_draft_json is None
        order = (
            db_session.query(Order)
            .filter(Order.conversation_id == conversation.id)
            .one()
        )
        assert order.status == OrderStatus.CONFIRMED
        inventory = (
            db_session.query(InventoryItem)
            .filter(InventoryItem.variant_id == variant.id)
            .one()
        )
        assert inventory.quantity == 4
    finally:
        db_session.close()


@pytest.mark.asyncio
async def test_draft_does_not_block_product_questions_or_mutate_draft(db_session):
    _, _, conversation, product, _ = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.commit()
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    provider = ScriptedToolProvider(
        [
            tool_call(
                "get_product_details",
                {"product_name": "Samsung Galaxy"},
            ),
            LLMResponse(
                content=(
                    "Samsung Galaxy has a Black option for 100 DZD, "
                    "with 5 in stock."
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Do you have this in black?",
    )

    assert "Black" in result["response"]
    assert "100 DZD" in result["response"]
    assert provider.calls == []
    assert conversation.active_draft_json == original_draft
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"


@pytest.mark.asyncio
async def test_searching_another_product_preserves_open_draft(db_session):
    store, _, conversation, product, variant = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    other_product = Product(
        store_id=store.id,
        name="Wireless Headphones",
        description="Audio accessory",
        base_price=Decimal("200.00"),
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "headphones"}),
            LLMResponse(
                content=(
                    "I found Wireless Headphones for 200 DZD. "
                    "Your current draft remains available."
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Show me another product, headphones.",
    )

    assert "Wireless Headphones" in result["response"]
    assert "200 DZD" in result["response"]
    assert conversation.active_draft_json == original_draft
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)


@pytest.mark.asyncio
async def test_variant_availability_question_uses_verified_stock_without_draft_change(
    db_session,
):
    _, _, conversation, product, variant = make_fixture(
        db_session,
        with_draft=True,
    )
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "variant_index_map": {"1": str(variant.id)},
        "variant_index_map_product_id": str(product.id),
    }
    db_session.commit()
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    provider = ScriptedToolProvider(
        [
            tool_call(
                "check_inventory",
                {"variant_index": 1, "quantity": 1},
            ),
            LLMResponse(content="The Black option has 5 in stock."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Is the black one available?",
    )

    assert "5 in stock" in result["response"]
    assert conversation.active_draft_json == original_draft
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"


@pytest.mark.asyncio
async def test_arabic_variant_availability_answers_from_verified_facts_without_selection(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
        "last_question_type": "VARIANT_SELECTION",
    }
    db_session.commit()
    provider = ScriptedToolProvider([])
    registry = make_registry()
    executed_tools = []
    original_execute = registry.aexecute

    async def capture_execute(*, tool_name, arguments, context):
        executed_tools.append(tool_name)
        return await original_execute(
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

    registry.aexecute = capture_execute
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "عندكم لون أسود؟")

    assert "نعم" in result["response"]
    assert "Black" in result["response"]
    assert "100 دج" in result["response"]
    assert "5" in result["response"]
    assert executed_tools == []
    assert provider.calls == []
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert conversation.metadata_json["commerce_stage"] == "PRODUCT_SELECTED"
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
async def test_unmatched_variant_availability_does_not_choose_a_different_option(
    db_session,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    variant.name = "Standard"
    variant.attributes_json = {"size": "standard"}
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"size": "standard"},
    }
    db_session.commit()
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "كاين باللون الأسود؟")

    assert "لا أجد خيارًا موثقًا" in result["response"]
    assert "Standard" in result["response"]
    assert "نعم" not in result["response"]
    assert provider.calls == []
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
async def test_explicit_variant_selection_updates_only_after_stock_verification(
    db_session,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": None,
    }
    db_session.commit()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())

    result = await run_turn(engine, db_session, conversation, "خليه أسود")

    assert f"تم اختيار {variant.name}." in result["response"]
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert conversation.metadata_json["commerce_stage"] == "VARIANT_SELECTED"


@pytest.mark.asyncio
async def test_explicit_variant_selection_without_stock_keeps_previous_selection(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    db_session.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one().quantity = 0
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": None,
    }
    db_session.commit()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())

    result = await run_turn(engine, db_session, conversation, "خليه أسود")

    assert "غير متوفر" in result["response"]
    assert conversation.metadata_json["selected_variant_id"] is None
    assert conversation.metadata_json["commerce_stage"] == "PRODUCT_SELECTED"


@pytest.mark.asyncio
async def test_unmatched_explicit_variant_keeps_existing_selection(db_session):
    _, _, conversation, product, black_variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(black_variant.id),
        "selected_attributes": {"color": "black"},
    }
    db_session.commit()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())

    result = await run_turn(engine, db_session, conversation, "خليه أبيض")

    assert "لم أجد خيارًا مطابقًا" in result["response"]
    assert conversation.metadata_json["selected_variant_id"] == str(black_variant.id)
    assert conversation.metadata_json["commerce_stage"] == "VARIANT_SELECTED"
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("وين عنوان محلكم؟", "عنوان موثق"),
        ("عندكم توصيل؟", "معلومة موثقة"),
    ],
)
async def test_store_policy_questions_do_not_search_or_change_selection(
    db_session,
    question,
    expected,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    db_session.commit()
    provider = ScriptedToolProvider([])
    registry = make_registry()
    executed_tools = []
    original_execute = registry.aexecute

    async def capture_execute(*, tool_name, arguments, context):
        executed_tools.append(tool_name)
        return await original_execute(
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

    registry.aexecute = capture_execute
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, question)

    assert expected in result["response"]
    assert executed_tools == []
    assert provider.calls == []
    assert conversation.metadata_json["commerce_stage"] == "PRODUCT_SELECTED"
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)


@pytest.mark.asyncio
async def test_post_confirmation_delivery_question_preserves_confirmed_order(
    db_session,
):
    _, _, conversation, product, _ = make_fixture(db_session)
    mark_conversation_order_confirmed(db_session, conversation, product)
    original_metadata = dict(conversation.metadata_json)
    original_orders = db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count()
    original_order = db_session.query(Order).filter(
        Order.conversation_id == conversation.id,
        Order.store_id == conversation.store_id,
    ).one()
    original_order_facts = (
        original_order.id,
        original_order.status,
        original_order.subtotal,
        original_order.shipping_cost,
        original_order.total,
        original_order.shipping_address,
    )
    provider = ScriptedToolProvider([])
    registry = make_registry()
    executed_tools = []
    original_execute = registry.aexecute

    async def capture_execute(*, tool_name, arguments, context):
        executed_tools.append(tool_name)
        return await original_execute(
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

    registry.aexecute = capture_execute
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "عندكم توصيل؟")

    assert "معلومة موثقة" in result["response"]
    assert executed_tools == []
    assert provider.calls == []
    assert conversation.metadata_json["commerce_stage"] == "ORDER_CONFIRMED"
    assert conversation.metadata_json["selected_product_id"] == original_metadata[
        "selected_product_id"
    ]
    assert conversation.active_draft_json is None
    unchanged_order = db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).one()
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == original_orders
    assert (
        unchanged_order.id,
        unchanged_order.status,
        unchanged_order.subtotal,
        unchanged_order.shipping_cost,
        unchanged_order.total,
        unchanged_order.shipping_address,
    ) == original_order_facts


@pytest.mark.asyncio
async def test_store_policy_question_during_draft_is_read_only(db_session):
    store, _, conversation, product, variant = make_fixture(
        db_session,
        with_draft=True,
    )
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()
    original_metadata = dict(conversation.metadata_json)
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    original_stock = db_session.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one().quantity
    registry = make_registry()
    executed_tools = []
    original_execute = registry.aexecute

    async def capture_execute(*, tool_name, arguments, context):
        executed_tools.append(tool_name)
        return await original_execute(
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

    registry.aexecute = capture_execute
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "عندكم توصيل؟")

    assert "معلومة موثقة" in result["response"]
    assert executed_tools == []
    assert provider.calls == []
    assert conversation.active_draft_json == original_draft
    assert conversation.metadata_json["commerce_stage"] == original_metadata[
        "commerce_stage"
    ]
    assert conversation.metadata_json["selected_variant_id"] == original_metadata[
        "selected_variant_id"
    ]
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"
    assert db_session.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one().quantity == original_stock


@pytest.mark.asyncio
async def test_full_engine_failed_search_preserves_open_draft_and_selection(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
        "last_question_type": "ORDER_CONFIRMATION",
        "candidate_product_ids": [],
    }
    db_session.commit()
    original_metadata = dict(conversation.metadata_json)
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    original_stock = db_session.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one().quantity
    registry = make_registry()
    executed_tools = []
    original_execute = registry.aexecute

    async def capture_execute(*, tool_name, arguments, context):
        executed_tools.append(tool_name)
        return await original_execute(
            tool_name=tool_name,
            arguments=arguments,
            context=context,
        )

    registry.aexecute = capture_execute
    engine = ConversationEngine(ScriptedToolProvider([]), registry)
    engine.agent_tool_loop_enabled = False

    async def fixed_search_nlu(*args, **kwargs):
        return {
            "intent": "product_search",
            "intent_guess": "product_search",
            "product_mention": "missing product",
            "attributes": {},
            "quantity": None,
            "confirmation_phrase": False,
            "language": "en",
            "confidence": 0.9,
        }

    engine._extract_nlu_via_qwen = fixed_search_nlu
    result = await run_turn(engine, db_session, conversation, "Find missing product")

    assert "couldn't find" in result["response"]
    assert executed_tools == ["search_products"]
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert conversation.metadata_json["selected_product_id"] == original_metadata[
        "selected_product_id"
    ]
    assert conversation.metadata_json["selected_variant_id"] == original_metadata[
        "selected_variant_id"
    ]
    assert conversation.metadata_json["selected_attributes"] == {"color": "black"}
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"
    assert conversation.active_draft_json == original_draft
    assert db_session.query(InventoryItem).filter(
        InventoryItem.store_id == store.id,
        InventoryItem.variant_id == variant.id,
    ).one().quantity == original_stock


@pytest.mark.asyncio
async def test_explicit_variant_change_updates_only_the_requested_draft_item(
    db_session,
):
    store, _, conversation, product, black_variant = make_fixture(db_session)
    blue_variant = ProductVariant(
        product_id=product.id,
        name="Blue",
        price_adjustment=Decimal("10.00"),
        attributes_json={"color": "blue"},
    )
    db_session.add(blue_variant)
    db_session.flush()
    db_session.add(
        InventoryItem(
            store_id=store.id,
            variant_id=blue_variant.id,
            quantity=5,
        )
    )
    conversation.active_draft_json = {
        "items": [
            {
                "variant_id": str(black_variant.id),
                "product_name": product.name,
                "variant_name": black_variant.name,
                "unit_price": 100,
                "quantity": 2,
                "line_total": 200,
                "available_stock": 5,
            }
        ],
        "shipping_info": {},
        "total_price": 200,
        "currency": "DZD",
    }
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(black_variant.id),
        "variant_index_map": {
            "1": str(black_variant.id),
            "2": str(blue_variant.id),
        },
        "variant_index_map_product_id": str(product.id),
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call(
                "update_order_draft",
                {
                    "action": "replace",
                    "item_index": 1,
                    "variant_index": 2,
                },
            ),
            LLMResponse(
                content=(
                    "Samsung Galaxy draft updated to Blue, "
                    "2 units at 110 DZD."
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Change the draft item to the blue option.",
    )

    initial_context = json.loads(
        provider.calls[0][0][1].content.partition("\n")[2]
    )
    updated_item = conversation.active_draft_json["items"][0]
    assert "Blue" in result["response"]
    assert "110 DZD" in result["response"]
    assert initial_context["active_draft"] is True
    assert initial_context["verified_facts"]["draft_summary"]["items"][0][
        "variant_name"
    ] == "Black"
    assert str(black_variant.id) not in json.dumps(initial_context)
    assert updated_item["variant_id"] == str(blue_variant.id)
    assert updated_item["quantity"] == 2
    assert updated_item["unit_price"] == 110
    assert conversation.active_draft_json["total_price"] == 220
    assert db_session.query(InventoryItem).filter(
        InventoryItem.variant_id == blue_variant.id
    ).one().quantity == 5
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"


@pytest.mark.asyncio
async def test_non_order_interruption_does_not_confirm_or_change_draft(db_session):
    _, _, conversation, _, _ = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    provider = ScriptedToolProvider(
        [LLMResponse(content="Take your time. We can continue whenever you are ready.")]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Let me think.")

    assert "The order is not confirmed." in result["response"]
    assert len(provider.calls) == 1
    assert conversation.active_draft_json == original_draft
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"
    assert not db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).all()


@pytest.mark.asyncio
async def test_customer_can_return_to_draft_after_an_interruption(db_session):
    _, _, conversation, _, _ = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    provider = ScriptedToolProvider(
        [
            LLMResponse(content="Take your time; your draft is still open."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    first_result = await run_turn(
        engine,
        db_session,
        conversation,
        "Let me think.",
    )
    assert "The order is not confirmed." in first_result["response"]

    provider.responses.append(
        LLMResponse(
            content="Your draft is still open. We can continue whenever you are ready."
        )
    )
    next_result = await run_turn(
        engine,
        db_session,
        conversation,
        "Okay, continue.",
    )

    assert "review the order summary" in next_result["response"].casefold()
    assert conversation.active_draft_json == original_draft
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"


@pytest.mark.asyncio
async def test_unconfigured_delivery_policy_is_honest_and_preserves_draft(db_session):
    _, _, conversation, _, _ = make_fixture(db_session, with_draft=True)
    original_draft = json.loads(json.dumps(conversation.active_draft_json))
    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Do you deliver to Guelma?",
    )

    assert "verified delivery" in result["response"]
    assert not provider.calls
    assert conversation.active_draft_json == original_draft


@pytest.mark.asyncio
async def test_agent_loop_stops_at_three_tool_rounds_and_uses_safe_template(
    db_session,
):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            tool_call("list_catalog_products", {}),
            tool_call("get_product_details", {"product_name": "Samsung Galaxy"}),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert len(provider.calls) == 3
    assert "Samsung Galaxy" in result["response"]
    assert "100" in result["response"]


@pytest.mark.asyncio
async def test_agent_loop_does_not_execute_repeated_tool_call(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)

    class CountedSearchTool(SearchProductsTool):
        def __init__(self):
            self.execution_count = 0

        async def execute(self, *args, **kwargs):
            self.execution_count += 1
            return await super().execute(*args, **kwargs)

    search_tool = CountedSearchTool()
    registry = make_registry()
    registry._tools["search_products"] = search_tool
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}, "first"),
            tool_call("search_products", {"query": "Samsung"}, "repeat"),
        ]
    )
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert search_tool.execution_count == 1
    assert len(provider.calls) == 2
    assert "Samsung Galaxy" in result["response"]


@pytest.mark.asyncio
async def test_agent_loop_does_not_confirm_without_the_pending_confirmation(
    db_session,
):
    _, _, conversation, _, _ = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {"last_question_type": "ORDER_CONFIRMATION"}
    db_session.commit()

    class CountedConfirmationTool(ConfirmOrderTool):
        def __init__(self):
            self.execution_count = 0

        async def execute(self, *args, **kwargs):
            self.execution_count += 1
            return await super().execute(*args, **kwargs)

    confirmation_tool = CountedConfirmationTool()
    registry = make_registry()
    registry._tools["confirm_order"] = confirmation_tool
    provider = ScriptedToolProvider(
        [
            tool_call("confirm_order", {}),
            LLMResponse(content="Your order is confirmed."),
        ]
    )
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "How much?")

    assert confirmation_tool.execution_count == 0
    assert conversation.active_draft_json["items"]
    assert "غير مؤكد" in result["response"]


@pytest.mark.asyncio
async def test_agent_provider_failure_uses_deterministic_fallback(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider([RuntimeError("provider unavailable")])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نحوس على هاتف سامسونغ",
    )

    assert result.get("processing_failed") is not True
    assert len(provider.calls) == 1
    assert "Samsung Galaxy" in result["response"]


@pytest.mark.asyncio
async def test_agent_provider_timeout_uses_deterministic_fallback(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)

    class SlowProvider(ScriptedToolProvider):
        async def chat(self, messages, tools=None, system_prompt=None):
            self.calls.append((messages, tools))
            await asyncio.sleep(0.02)
            return LLMResponse(content="This reply is too late.")

    provider = SlowProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True
    engine.agent_tool_loop_timeout_seconds = 0.001

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نحوس على هاتف سامسونغ",
    )

    assert result.get("processing_failed") is not True
    assert len(provider.calls) == 1
    assert "Samsung Galaxy" in result["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    (
        "{not-json}",
        '{"unknown":"I found Samsung Galaxy."}',
        '{"reply":"I found Samsung Galaxy.","extra":true}',
    ),
)
async def test_agent_rejects_invalid_or_unrecognized_json_reply(
    db_session,
    content,
):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider([LLMResponse(content=content)])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نحوس على هاتف سامسونغ",
    )

    assert result.get("processing_failed") is not True
    assert len(provider.calls) == 1
    assert "Samsung Galaxy" in result["response"]


@pytest.mark.asyncio
async def test_agent_forged_price_is_rejected_for_verified_template(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            LLMResponse(
                content="Samsung Galaxy costs 999 DZD. It has a warranty."
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert "999" not in result["response"]
    assert "100" in result["response"]
    assert "Samsung Galaxy" in result["response"]


@pytest.mark.asyncio
async def test_cross_store_isolation_prevents_accessing_other_store_products(db_session):
    """
    Regression test: ensure that a conversation with one store cannot
    access or reference products from another store, even through the
    LLM's output or context.
    """
    from app.models.store import Store

    # Create two separate stores
    store_a = Store(name="Store A", slug="store-a")
    store_b = Store(name="Store B", slug="store-b")
    db_session.add_all([store_a, store_b])
    db_session.flush()

    # Create products in each store
    product_a = Product(
        store_id=store_a.id,
        name="Product A",
        description="From store A",
        base_price=Decimal("50.00"),
        is_active=True,
    )
    product_b = Product(
        store_id=store_b.id,
        name="Product B",
        description="From store B",
        base_price=Decimal("75.00"),
        is_active=True,
    )
    db_session.add_all([product_a, product_b])
    db_session.flush()

    # Create variants for each product
    variant_a = ProductVariant(
        product_id=product_a.id,
        name="Variant A",
        price_adjustment=Decimal("0.00"),
        attributes_json={},
    )
    variant_b = ProductVariant(
        product_id=product_b.id,
        name="Variant B",
        price_adjustment=Decimal("0.00"),
        attributes_json={},
    )
    db_session.add_all([variant_a, variant_b])
    db_session.flush()

    # Add inventory for each variant
    db_session.add_all([
        InventoryItem(store_id=store_a.id, variant_id=variant_a.id, quantity=10),
        InventoryItem(store_id=store_b.id, variant_id=variant_b.id, quantity=3),
    ])
    db_session.commit()

    # Create customers for each store
    customer_a = Customer(store_id=store_a.id, name="Customer A")
    customer_b = Customer(store_id=store_b.id, name="Customer B")
    db_session.add_all([customer_a, customer_b])
    db_session.flush()

    # Create conversations for each store
    conversation_a = Conversation(
        store_id=store_a.id,
        customer_id=customer_a.id,
        channel="test",
        status="active",
        metadata_json={},
    )
    conversation_b = Conversation(
        store_id=store_b.id,
        customer_id=customer_b.id,
        channel="test",
        status="active",
        metadata_json={},
    )
    db_session.add_all([conversation_a, conversation_b])
    db_session.commit()

    # Set up conversation A with product A selected
    conversation_a.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product_a.id),
        "selected_product_name": product_a.name,
        "selected_variant_id": str(variant_a.id),
        "selected_attributes": {"color": "default"},
    }
    db_session.commit()

    # Set up registry and engine for store A
    registry = make_registry()
    engine = ConversationEngine(ScriptedToolProvider([]), registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    # Now simulate a message from store A's customer
    result = await engine.process_message(
        db=db_session,
        store_id=store_a.id,
        customer_id=customer_a.id,
        conversation_id=conversation_a.id,
        channel="test",
        user_message="What about Product B?",
    )

    # Verify store A cannot return or retain store B's product.
    assert "Product B" not in result["response"]
    assert product_a.name in result["response"]
    assert str(product_b.id) not in json.dumps(conversation_a.metadata_json)

    # Verify store B's conversation is untouched
    result_b = await engine.process_message(
        db=db_session,
        store_id=store_b.id,
        customer_id=customer_b.id,
        conversation_id=conversation_b.id,
        channel="test",
        user_message="What about Product A?",
    )
    assert "Product A" not in result_b["response"]
    assert product_b.name in result_b["response"]
    assert str(product_a.id) not in json.dumps(conversation_b.metadata_json)


def test_agent_reply_validator_rejects_unverified_price_and_policy():
    from app.agent.reply_composer import ReplyComposer

    facts = {"products": [{"name": "Samsung Galaxy", "price": 100}]}

    assert not ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy costs 999 DZD.",
        "en",
        facts,
    )
    assert not ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy comes with free delivery.",
        "en",
        facts,
    )
    assert ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy costs 100 DZD.",
        "en",
        facts,
    )
    inventory_facts = {
        "products": [{"name": "Samsung Galaxy", "price": 100}],
        "inventory": [{"available_quantity": 5, "is_available": True}],
    }
    assert not ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy has only 2 in stock.",
        "en",
        inventory_facts,
    )
    assert ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy has 5 in stock.",
        "en",
        inventory_facts,
    )
    assert not ReplyComposer.is_safe_agent_reply(
        "Your order is confirmed.",
        "en",
        facts,
    )
    assert not ReplyComposer.is_safe_agent_reply(
        "Your order has been delivered.",
        "en",
        facts,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["حبيت نشري الحذاء", "حبيت ندير طلب"],
)
async def test_messenger_order_intent_updates_existing_draft(
    db_session,
    message,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    product.name = "الحذاء"
    conversation.active_draft_json = {
        "items": [
            {
                "variant_id": str(variant.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "quantity": 1,
                "unit_price": 100,
                "line_total": 100,
                "available_stock": 5,
            }
        ],
        "total_price": 100,
        "shipping_info": {},
    }
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()

    provider = ScriptedToolProvider([])
    registry = make_registry()
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False

    async def local_nlu(user_message, state, **_kwargs):
        return engine._heuristic_nlu(user_message, state)

    engine._extract_nlu_via_qwen = local_nlu
    result = await engine.process_message(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        channel="messenger",
        user_message=message,
    )

    assert result["turn_diagnostics"]["intent"] == "order_create"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:update_order_draft"
    )
    assert result["response"].startswith("تم تحديث مسودة الطلب.")
    assert conversation.active_draft_json["items"][0]["quantity"] == 2
    assert conversation.active_draft_json["total_price"] == 200
    assert provider.calls == []
    registry.aexecute.assert_awaited_once()
    tool_call = registry.aexecute.await_args.kwargs
    assert tool_call["tool_name"] == "update_order_draft"
    assert tool_call["arguments"] == {
        "action": "add",
        "variant_id": str(variant.id),
        "quantity": 1,
    }


@pytest.mark.asyncio
async def test_messenger_first_purchase_saves_draft_without_confirming(db_session):
    store, customer, conversation, product, variant = make_fixture(db_session)
    product.name = "الحذاء"
    product.base_price = Decimal("137.50")
    variant.price_adjustment = Decimal("12.50")
    inventory = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.variant_id == variant.id)
        .one()
    )
    inventory.quantity = 3
    conversation.active_draft_json = None
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    db_session.commit()

    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False

    async def local_nlu(user_message, state, **_kwargs):
        return engine._heuristic_nlu(user_message, state)

    engine._extract_nlu_via_qwen = local_nlu
    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="messenger",
        user_message="حبيت نشري الحذاء",
    )

    db_session.refresh(conversation)
    draft = conversation.active_draft_json

    assert result["turn_diagnostics"]["intent"] == "order_create"
    assert result["turn_diagnostics"]["resolver_action"] == "CALL_SERVICE:create_draft"
    assert "هذا الإجراء غير متاح حاليًا" not in result["response"]
    assert "تم حفظ مسودة الطلب" in result["response"]
    assert draft is not None
    assert len(draft["items"]) == 1
    assert draft["items"][0] == {
        "variant_id": str(variant.id),
        "product_name": "الحذاء",
        "variant_name": variant.name,
        "unit_price": 150.0,
        "quantity": 1,
        "line_total": 150.0,
        "available_stock": 3,
    }
    assert draft["total_price"] == 150.0
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .count()
        == 0
    )
    assert provider.calls == []


@pytest.mark.asyncio
async def test_compound_variant_selection_and_delivery_question_preserve_selection(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    store.delivery_policy_text = "التوصيل متاح إلى الولايات المسجلة."
    store.served_wilayas = "وهران، الجزائر"
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "variant_index_map": {"1": str(variant.id)},
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "VARIANT_SELECTION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نختار الخيار رقم 01، وبالمناسبة قداش التوصيل؟",
    )

    assert result["turn_diagnostics"]["intent"] == "variant_selection"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "CALL_SERVICE:resolve_variant"
    )
    assert result["turn_diagnostics"]["turn_plan"]["information_requests"] == [
        "delivery"
    ]
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert variant.name in result["response"]
    assert "100" in result["response"]
    assert store.delivery_policy_text in result["response"]
    assert "وهران، الجزائر" in result["response"]


@pytest.mark.asyncio
async def test_compound_turn_keeps_selection_when_delivery_lookup_fails(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "variant_index_map": {"1": str(variant.id)},
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "VARIANT_SELECTION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )
    engine.registry.get("store_info").execute = AsyncMock(
        side_effect=RuntimeError("local store info mock failure")
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نختار الخيار رقم 01، وقداش التوصيل؟",
    )

    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert variant.name in result["response"]
    assert "ما عنديش معلومة موثقة" in result["response"]
    assert "هذا الإجراء غير متاح حاليًا" not in result["response"]


@pytest.mark.asyncio
async def test_compound_variant_selection_and_quantity_creates_draft(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "variant_index_map": {"1": str(variant.id)},
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "VARIANT_SELECTION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نختار الخيار رقم 01 وخلي الكمية 2",
    )

    assert result["turn_diagnostics"]["resolver_action"] == (
        "CALL_SERVICE:create_draft"
    )
    assert conversation.active_draft_json is not None, result
    assert conversation.active_draft_json["items"] == [
        {
            "variant_id": str(variant.id),
            "product_name": product.name,
            "variant_name": variant.name,
            "unit_price": 100.0,
            "quantity": 2,
            "line_total": 200.0,
            "available_stock": 5,
        }
    ]
    assert conversation.active_draft_json["total_price"] == 200.0
    assert (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .count()
        == 0
    )


@pytest.mark.asyncio
async def test_explicit_variant_correction_replaces_draft_item(db_session):
    store, _, conversation, product, first_variant = make_fixture(db_session)
    second_variant = ProductVariant(
        product_id=product.id,
        name="Premium",
        price_adjustment=Decimal("25"),
        attributes_json={"style": "premium"},
    )
    db_session.add(second_variant)
    db_session.flush()
    db_session.add(
        InventoryItem(
            store_id=store.id,
            variant_id=second_variant.id,
            quantity=4,
        )
    )
    conversation.active_draft_json = {
        "items": [
            {
                "variant_id": str(first_variant.id),
                "product_name": product.name,
                "variant_name": first_variant.name,
                "quantity": 1,
                "unit_price": 100.0,
                "line_total": 100.0,
                "available_stock": 5,
            }
        ],
        "total_price": 100.0,
        "shipping_info": {},
    }
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(first_variant.id),
        "variant_index_map": {
            "1": str(first_variant.id),
            "2": str(second_variant.id),
        },
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "لا، أقصد الخيار 02",
    )

    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:update_order_draft"
    )
    assert conversation.active_draft_json["items"][0]["variant_id"] == str(
        second_variant.id
    )
    assert conversation.active_draft_json["items"][0]["variant_name"] == "Premium"
    assert conversation.active_draft_json["items"][0]["quantity"] == 1
    assert conversation.active_draft_json["total_price"] == 125.0


@pytest.mark.asyncio
async def test_failed_draft_update_preserves_corrected_selection(db_session):
    store, _, conversation, product, first_variant = make_fixture(db_session)
    second_variant = ProductVariant(
        product_id=product.id,
        name="Premium",
        price_adjustment=Decimal("25"),
        attributes_json={"style": "premium"},
    )
    db_session.add(second_variant)
    db_session.flush()
    db_session.add(
        InventoryItem(
            store_id=store.id,
            variant_id=second_variant.id,
            quantity=4,
        )
    )
    original_draft = {
        "items": [
            {
                "variant_id": str(first_variant.id),
                "product_name": product.name,
                "variant_name": first_variant.name,
                "quantity": 1,
                "unit_price": 100.0,
                "line_total": 100.0,
                "available_stock": 5,
            }
        ],
        "total_price": 100.0,
        "shipping_info": {},
    }
    conversation.active_draft_json = original_draft
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(first_variant.id),
        "variant_index_map": {
            "1": str(first_variant.id),
            "2": str(second_variant.id),
        },
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )
    engine.registry.aexecute = AsyncMock(
        side_effect=RuntimeError("local draft update mock failure")
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "لا، أقصد الخيار 02",
    )

    assert conversation.metadata_json["selected_variant_id"] == str(second_variant.id)
    assert conversation.active_draft_json == original_draft
    assert "تم حفظ اختيارك" in result["response"]
    assert "هذا الإجراء غير متاح حاليًا" not in result["response"]


@pytest.mark.asyncio
async def test_selection_and_add_product_request_keeps_selection_and_clarifies(
    db_session,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "variant_index_map": {"1": str(variant.id)},
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "VARIANT_SELECTION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "نختار الخيار 01 ونحب نزيد منتج آخر",
    )

    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert "ما المنتج الآخر الذي تريد إضافته؟" in result["response"]


@pytest.mark.asyncio
async def test_explicit_quantity_update_changes_only_requested_draft_item(db_session):
    _, _, conversation, product, variant = make_fixture(db_session)
    draft = {
        "items": [
            {
                "variant_id": str(variant.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "quantity": 1,
                "unit_price": 100.0,
                "line_total": 100.0,
                "available_stock": 5,
            }
        ],
        "total_price": 100.0,
        "shipping_info": {},
    }
    conversation.active_draft_json = draft
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "خلي الكمية 2",
    )

    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:update_order_draft"
    )
    assert conversation.active_draft_json["items"][0]["quantity"] == 2
    assert conversation.active_draft_json["total_price"] == 200.0


@pytest.mark.asyncio
async def test_order_change_question_does_not_mutate_draft(db_session):
    _, _, conversation, product, variant = make_fixture(db_session)
    draft = {
        "items": [
            {
                "variant_id": str(variant.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "quantity": 1,
                "unit_price": 100.0,
                "line_total": 100.0,
                "available_stock": 5,
            }
        ],
        "total_price": 100.0,
        "shipping_info": {},
    }
    conversation.active_draft_json = draft
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()

    registry = make_registry()
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(ScriptedToolProvider([]), registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(engine, db_session, conversation, "كيفاش نعدل طلبي؟")

    assert conversation.active_draft_json == draft
    registry.aexecute.assert_not_awaited()
    assert "ما عنديش سياسة موثقة" in result["response"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["قداش سعر الحذاء؟", "شحال يسوى؟"],
)
async def test_messenger_price_followup_uses_selected_product_id(
    db_session,
    message,
):
    _, _, conversation, product, _ = make_fixture(db_session)
    product.name = "الحذاء"
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.commit()

    provider = ScriptedToolProvider([])
    registry = make_registry()
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False

    async def local_nlu(user_message, state, **_kwargs):
        return engine._heuristic_nlu(user_message, state)

    engine._extract_nlu_via_qwen = local_nlu
    result = await engine.process_message(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        channel="messenger",
        user_message=message,
    )

    assert result["turn_diagnostics"]["intent"] == "product_details"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:get_product_details"
    )
    assert "100" in result["response"]
    assert provider.calls == []
    registry.aexecute.assert_awaited_once()
    tool_call = registry.aexecute.await_args.kwargs
    assert tool_call["tool_name"] == "get_product_details"
    assert tool_call["arguments"] == {"product_id": str(product.id)}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    ["رقم 1", "1", "الخيار رقم 1", "الخيار الأول", "الأول", "نختار الأول"],
)
async def test_variant_selection_accepts_numeric_and_ordinal_forms(
    db_session,
    message,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "variant_index_map": {"1": str(variant.id)},
        "variant_index_map_product_id": str(product.id),
        "last_question_type": "VARIANT_SELECTION",
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda text, state, **_kwargs: engine._heuristic_nlu(
            text, state
        )
    )

    result = await run_turn(engine, db_session, conversation, message)

    assert result["turn_diagnostics"]["intent"] == "variant_selection"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "CALL_SERVICE:resolve_variant"
    )
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)


@pytest.mark.asyncio
async def test_single_available_variant_is_selected_when_details_are_shown(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    unavailable_variant = ProductVariant(
        product_id=product.id,
        name="Out of stock",
        price_adjustment=Decimal("10"),
        attributes_json={"color": "white"},
    )
    db_session.add(unavailable_variant)
    db_session.flush()
    db_session.add(
        InventoryItem(
            store_id=store.id,
            variant_id=unavailable_variant.id,
            quantity=0,
        )
    )
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.commit()

    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        return_value={
            "intent": "product_details",
            "intent_guess": "product_details",
            "product_mention": None,
            "attributes": {},
            "quantity": None,
            "confirmation_phrase": False,
            "language": "ar",
            "confidence": 0.9,
        }
    )

    result = await run_turn(engine, db_session, conversation, "وريني الخيارات")

    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert conversation.metadata_json["commerce_stage"] == "VARIANT_SELECTED"
    assert conversation.metadata_json["last_question_type"] == "ORDER_CREATE_OFFER"
    assert "تم اختيار الخيار الوحيد المتاح تلقائيًا" in result["response"]
    assert "اختر" not in result["response"]
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
async def test_purchase_request_creates_one_draft_and_repeats_are_idempotent(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "ORDER_CREATE_OFFER",
    }
    db_session.commit()

    registry = make_registry()
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(ScriptedToolProvider([]), registry)
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    first_result = await run_turn(engine, db_session, conversation, "دير طلب")

    assert first_result["turn_diagnostics"]["intent"] == "order_create"
    assert first_result["turn_diagnostics"]["resolver_action"] == (
        "CALL_SERVICE:create_draft"
    )
    assert conversation.active_draft_json is not None
    assert len(conversation.active_draft_json["items"]) == 1
    assert conversation.active_draft_json["items"][0]["variant_id"] == str(variant.id)
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .count()
        == 0
    )
    registry.aexecute.assert_not_awaited()

    draft_after_first_request = json.loads(
        json.dumps(conversation.active_draft_json)
    )
    second_result = await run_turn(
        engine,
        db_session,
        conversation,
        "ديرلي طلب",
    )

    assert second_result["turn_diagnostics"]["intent"] == "order_create"
    assert second_result["turn_diagnostics"]["resolver_action"] == "RESPOND:text_only"
    assert conversation.active_draft_json == draft_after_first_request
    assert len(conversation.active_draft_json["items"]) == 1
    assert (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .count()
        == 0
    )
    registry.aexecute.assert_not_awaited()


@pytest.mark.asyncio
async def test_yes_advances_pending_purchase_offer_to_draft(db_session):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "ORDER_CREATE_OFFER",
    }
    db_session.commit()

    provider = ScriptedToolProvider([])
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True
    engine.reply_composer_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(engine, db_session, conversation, "نعم")

    assert result["turn_diagnostics"]["intent"] == "order_create"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "CALL_SERVICE:create_draft"
    )
    assert conversation.active_draft_json is not None
    assert len(conversation.active_draft_json["items"]) == 1
    assert provider.calls == []


def test_order_create_offer_fallback_does_not_repeat_stale_question():
    response = ConversationEngine._contextual_clarification(
        {
            "commerce_stage": "VARIANT_SELECTED",
            "selected_variant_id": str(uuid.uuid4()),
            "last_question_type": "ORDER_CREATE_OFFER",
        },
        "ar",
    )

    assert response is not None
    assert "نواصل بالخيار" not in response
    assert "دير طلب" in response
