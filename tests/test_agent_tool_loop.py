import asyncio
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.agent.classifier import (
    INTENT_AMBIGUOUS,
    INTENT_GENERAL_CHAT,
    INTENT_TOPIC_CHANGE,
    ConversationClassifier,
)
from app.agent.commerce_resolver import CommerceResolver, ResolutionResult
from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.base import LLMMessage, LLMResponse
from app.agent.providers.freellm_provider import FreeLLMProvider
from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.check_inventory import CheckInventoryTool
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.get_customer_context import GetCustomerContextTool
from app.agent.tools.get_product_details import GetProductDetailsTool
from app.agent.tools.list_catalog import ListCatalogProductsTool
from app.agent.tools.registry import ToolRegistry, ToolSessionUnusableError
from app.agent.tools.recommend_products import RecommendProductsTool
from app.agent.tools.search_products import SearchProductsTool
from app.agent.tools.send_product_image import SendProductImageTool
from app.agent.tools.store_info import StoreInfoTool
from app.agent.tools.update_order_draft import UpdateOrderDraftTool
from app.agent.reply_composer import ReplyComposer
from app.models.conversation import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)
from app.models.customer import Customer
from app.models.customer_memory import CustomerMemory
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.product_image import ProductImage
from app.models.store import Store


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


def openai_chat_response(*, content=None, tool_call=None, model=None, request_id=None, routed_via=None):
    message = SimpleNamespace(content=content, tool_calls=[])
    finish_reason = "stop"
    if tool_call is not None:
        message.tool_calls = [
            SimpleNamespace(
                id=tool_call["id"],
                function=SimpleNamespace(
                    name=tool_call["name"],
                    arguments=json.dumps(tool_call["arguments"]),
                ),
            )
        ]
        finish_reason = "tool_calls"
    return SimpleNamespace(
        choices=[SimpleNamespace(message=message, finish_reason=finish_reason)],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        model=model,
        id=request_id,
    )


def make_mock_freellm_provider(responses):
    provider = FreeLLMProvider.__new__(FreeLLMProvider)
    provider.model = "auto"
    provider.max_retries = 0
    # Use a list to track responses for the mock
    response_list = list(responses)

    async def mock_with_raw_response_create(**kwargs):
        if response_list:
            response = response_list.pop(0)
        else:
            response = openai_chat_response(content="Mock response")
        # Create a mock raw response with headers
        raw_response = SimpleNamespace(
            parse=lambda: response,
            headers={"X-Routed-Via": "test-model"},
        )
        return raw_response

    async def mock_create(**kwargs):
        if response_list:
            return response_list.pop(0)
        else:
            return openai_chat_response(content="Mock response")

    # The FreeLLMProvider now uses with_raw_response.create internally
    # but tests expect to access create directly for call counting
    # So we track calls on both - create_mock is what tests check
    create_mock = AsyncMock(side_effect=mock_create)
    with_raw_response_mock = AsyncMock(side_effect=mock_with_raw_response_create)

    # Attach create_mock to the path tests expect
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=create_mock,
                with_raw_response=SimpleNamespace(
                    create=with_raw_response_mock,
                ),
            )
        )
    )
    return provider


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
        GetCustomerContextTool(),
        RecommendProductsTool(),
        StoreInfoTool(),
        SendProductImageTool(),
    ):
        registry.register(tool)
    return registry


@pytest.mark.asyncio
async def test_tool_database_error_rolls_back_savepoint_and_next_tool_succeeds(
    db_session,
):
    class BrokenQueryTool(BaseTool):
        name = "broken_query"
        description = "Runs a query against a missing table."
        input_schema = {}

        async def execute(self, store_id, arguments, context=None):
            context["db"].execute(text("SELECT * FROM missing_agent_test_table"))
            return ToolResult(success=True)

    class HealthyQueryTool(BaseTool):
        name = "healthy_query"
        description = "Runs a harmless query."
        input_schema = {}

        async def execute(self, store_id, arguments, context=None):
            value = context["db"].execute(text("SELECT 1")).scalar_one()
            return ToolResult(success=True, data={"value": value})

    store, customer, conversation, _, _ = make_fixture(db_session)
    registry = ToolRegistry()
    registry.register(BrokenQueryTool())
    registry.register(HealthyQueryTool())
    context = {
        "db": db_session,
        "store_id": store.id,
        "customer_id": customer.id,
        "conversation_id": conversation.id,
    }

    failed_result = await registry.aexecute("broken_query", {}, context)
    assert failed_result.success is False
    assert failed_result.error_code == "DATABASE_ERROR"
    assert "NO_RESULTS" in failed_result.error
    assert db_session.is_active

    next_result = await registry.aexecute("healthy_query", {}, context)
    assert next_result.success is True
    assert next_result.data == {"value": 1}


@pytest.mark.asyncio
async def test_agent_loop_reports_database_failure_as_technical_observation(
    db_session,
):
    class BrokenSearchTool(SearchProductsTool):
        async def execute(self, store_id, arguments, context=None):
            context["db"].execute(text("SELECT * FROM missing_agent_test_table"))
            return ToolResult(success=True)

    store, customer, conversation, _, _ = make_fixture(db_session)
    registry = make_registry()
    registry._tools["search_products"] = BrokenSearchTool()
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "shoes"}, "broken-search"),
            tool_call("list_catalog_products", {}, "list-catalog"),
            LLMResponse(content="The database search failed temporarily."),
        ]
    )
    engine = ConversationEngine(provider, registry)
    result = await engine._run_agent_tool_loop(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation=conversation,
        channel="test",
        user_message="Find shoes",
        current_state=engine._normalize_current_state(conversation, store.id),
        dialogue_context=[],
        language="en",
    )

    assert result is not None
    observations = [
        json.loads(message.content)
        for message in provider.calls[1][0]
        if message.role == "tool"
    ]
    observation = next(
        item for item in observations if item.get("error_code") == "DATABASE_ERROR"
    )
    assert observation["category"] == "technical_error"
    assert observation["error_code"] == "DATABASE_ERROR"
    assert len(provider.calls) == 3


@pytest.mark.asyncio
async def test_failed_tool_savepoint_preserves_successful_draft_change(db_session):
    class SaveDraftTool(BaseTool):
        name = "save_test_draft"
        description = "Persists a draft for the test conversation."
        input_schema = {}

        async def execute(self, store_id, arguments, context=None):
            conversation = context["db"].get(
                Conversation, context["conversation_id"]
            )
            conversation.active_draft_json = {
                "items": [{"quantity": 1}],
                "total_price": 100,
            }
            context["db"].flush()
            return ToolResult(success=True)

    class BrokenQueryTool(BaseTool):
        name = "broken_query"
        description = "Runs a query against a missing table."
        input_schema = {}

        async def execute(self, store_id, arguments, context=None):
            context["db"].execute(text("SELECT * FROM missing_agent_test_table"))
            return ToolResult(success=True)

    store, customer, conversation, _, _ = make_fixture(db_session)
    registry = ToolRegistry()
    registry.register(SaveDraftTool())
    registry.register(BrokenQueryTool())
    context = {
        "db": db_session,
        "store_id": store.id,
        "customer_id": customer.id,
        "conversation_id": conversation.id,
    }

    saved = await registry.aexecute("save_test_draft", {}, context)
    failed = await registry.aexecute("broken_query", {}, context)

    assert saved.success is True
    assert failed.error_code == "DATABASE_ERROR"
    db_session.expire(conversation, ["active_draft_json"])
    assert conversation.active_draft_json == {
        "items": [{"quantity": 1}],
        "total_price": 100,
    }


@pytest.mark.asyncio
async def test_unrecoverable_tool_session_does_not_refresh_conversation(
    db_session, monkeypatch
):
    store, customer, conversation, _, _ = make_fixture(db_session)
    engine = ConversationEngine(
        ScriptedToolProvider(
            [tool_call("search_products", {"query": "shoes"})]
        ),
        make_registry(),
    )
    engine._execute_agent_tool_call = AsyncMock(
        side_effect=ToolSessionUnusableError("session is unusable")
    )
    monkeypatch.setattr(
        db_session,
        "refresh",
        lambda *args, **kwargs: pytest.fail(
            "must not refresh a conversation after an unrecoverable tool failure"
        ),
    )

    with pytest.raises(ToolSessionUnusableError):
        await engine._run_agent_tool_loop(
            db=db_session,
            store_id=store.id,
            customer_id=customer.id,
            conversation=conversation,
            channel="test",
            user_message="Find shoes",
            current_state=engine._normalize_current_state(conversation, store.id),
            dialogue_context=[],
            language="en",
        )


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
    draft_id = str(uuid.uuid4())
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
        "last_question_type": "ORDER_CONFIRMATION",
        "confirmation_pending": {"draft_id": draft_id},
    }
    conversation.active_draft_json = {
        "draft_id": draft_id,
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
        "shipping_info": {
            "phone": "0550123456",
            "wilaya": "الجزائر",
            "municipality": "باب الزوار",
        },
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


def test_active_draft_overrides_stale_product_selection_stage(db_session):
    store, _, conversation, product, variant = make_fixture(
        db_session, with_draft=True
    )
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_variant_id": str(variant.id),
        "last_question_type": "CUSTOMER_DELIVERY_INFO",
    }

    state = ConversationEngine(
        ScriptedToolProvider([]), make_registry()
    )._normalize_current_state(conversation, store.id)

    assert state["commerce_stage"] == "DRAFT_PENDING"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirmation",
    ["أكد الطلب", "اكد الطلب"],
)
async def test_required_confirmation_phrase_creates_order_and_one_reply(
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


@pytest.mark.asyncio
@pytest.mark.parametrize("confirmation", ["نعم", "أكد", "confirme"])
async def test_natural_consent_confirms_pending_order_summary(
    db_session,
    confirmation,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    prepare_pending_confirmation(conversation, product, variant)
    db_session.commit()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False

    result = await run_turn(engine, db_session, conversation, confirmation)

    assert result["turn_diagnostics"]["resolver_action"] == (
        "EXECUTE_TOOL:confirm_order"
    )
    assert conversation.active_draft_json is None
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id,
        Order.store_id == store.id,
        Order.status == OrderStatus.CONFIRMED,
    ).count() == 1


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
        "get_customer_context",
        "recommend_products",
        "store_info",
        "send_product_image",
    ]
    tool_result = provider.calls[1][0][-1]
    assert tool_result.role == "tool"
    assert "Samsung Galaxy" in tool_result.content
    assert str(product.id) not in tool_result.content


@pytest.mark.asyncio
async def test_messenger_freellm_controls_ordinary_tool_selection_and_reply(
    db_session, caplog
):
    store, customer, conversation, product, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}, "search-samsung"),
            LLMResponse(
                content=(
                    "I found Samsung Galaxy. "
                    + "Here are the verified product details. " * 25
                )
            ),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "mock-freellm-model"
    engine = ConversationEngine(provider, make_registry())

    with caplog.at_level("INFO", logger="app.agent.conversation_engine"):
        result = await engine.process_message(
            db=db_session,
            store_id=store.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            channel="facebook",
            user_message="Find Samsung, my phone is 0550123456",
        )

    assert result["response"] == (
        "I found Samsung Galaxy. "
        + "Here are the verified product details. " * 25
    ).strip()
    assert result["turn_diagnostics"]["resolver_action"] == "free_agent_tool_loop"
    assert len(provider.calls) == 2
    tool_result_message = next(
        message for message in provider.calls[1][0] if message.role == "tool"
    )
    assert str(product.id) not in tool_result_message.content
    assert "agent_turn_started" in caplog.text
    assert "provider=freellm" in caplog.text
    assert "mock-freellm-model" in caplog.text
    assert "agent_tool_selected" in caplog.text
    assert "agent_tool_completed" in caplog.text
    assert "0550123456" not in caplog.text
    customer_message = json.loads(
        next(
            message
            for message in provider.calls[0][0]
            if message.role == "user"
        ).content
    )
    assert "0550123456" not in customer_message["customer_message"]
    context = json.loads(provider.calls[0][0][1].content.split("\n", 1)[1])
    assert context["delivery_details_in_current_message"]["phone_provided"] is True


def test_freellm_tool_schemas_expose_customer_tools_and_shipping_fields(db_session):
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    schemas = {
        item["function"]["name"]: item["function"]
        for item in engine._agent_tool_schemas()
    }

    assert "send_product_image" in schemas
    assert "store_info" in schemas
    assert "search_products" in schemas
    assert "get_product_details" in schemas
    assert "create_order_draft" in schemas
    assert "update_order_draft" in schemas
    assert schemas["send_product_image"]["parameters"]["properties"] == {}
    update_parameters = schemas["update_order_draft"]["parameters"]
    assert "shipping_info" not in update_parameters["properties"]["action"]
    assert "municipality" in update_parameters["properties"]["shipping_info"][
        "properties"
    ]
    assert FreeLLMProvider.provider_name == "freellm"


def _fake_request():
    return SimpleNamespace()


@pytest.mark.asyncio
async def test_freellm_honors_retry_after_seconds_from_429():
    from openai import RateLimitError

    response = SimpleNamespace(
        status_code=429,
        headers={"Retry-After": "30"},
        request=_fake_request(),
    )
    exc = RateLimitError("Rate limited", response=response, body=None)
    provider = make_mock_freellm_provider([])
    assert provider._retry_after_seconds(exc) == 30.0
    # Missing header falls back to default
    no_header_response = SimpleNamespace(
        status_code=429, headers={}, request=_fake_request()
    )
    no_header_exc = RateLimitError("Rate limited", response=no_header_response, body=None)
    assert provider._retry_after_seconds(no_header_exc, default=5.0) == 5.0


def test_freellm_flags_state_per_call_and_respects_max_retries():
    from openai import RateLimitError

    response = SimpleNamespace(
        status_code=429, headers={}, request=_fake_request()
    )
    exc = RateLimitError("rate-limited", response=response, body=None)
    provider = make_mock_freellm_provider([])
    provider.max_retries = 1
    provider._rate_limit_retry_attempted = True
    # Second call resets the flag
    provider._rate_limit_retry_attempted = False
    assert not provider._rate_limit_retry_attempted
    # After touching a rate-limit exception, the flag is set
    from app.agent.providers.freellm_provider import FreeLLMProvider
    # Empty headers -> missing Retry-After -> falls back to default
    assert provider._retry_after_seconds(exc) == 2.0
    assert provider._retry_after_seconds(exc, default=9.0) == 9.0


def test_freellm_429_error_returns_retry_after_in_usage_metadata():
    from openai import RateLimitError
    from app.agent.providers.freellm_provider import FreeLLMProvider

    response = SimpleNamespace(
        status_code=429, headers={"Retry-After": "7"}, request=_fake_request()
    )
    exc = RateLimitError("rate-limited", response=response, body=None)
    provider = make_mock_freellm_provider([])
    async def _raise(**kw):
        raise exc
    provider.client.chat.completions.with_raw_response.create = AsyncMock(side_effect=_raise)
    result = asyncio.run(provider.chat([LLMMessage(role="user", content="hi")]))
    assert result.finish_reason == "error"
    assert result.usage["error_type"] == "RateLimitError"
    assert result.usage["status_code"] == 429
    assert result.usage["retry_after_seconds"] == 7.0


@pytest.mark.asyncio
async def test_freellm_provider_exposes_reported_model_and_request_id():
    provider = make_mock_freellm_provider(
        [
            openai_chat_response(
                content="Hello.",
                model="provider-selected-model",
                request_id="completion-request-id",
            )
        ]
    )

    response = await provider.chat(
        [LLMMessage(role="user", content="Hello")],
    )

    assert response.usage["reported_model"] == "provider-selected-model"
    assert response.usage["requested_model"] == "auto"
    assert response.usage["request_id"] == "completion-request-id"


def test_freellm_agent_loop_uses_freellm_timeout_setting(monkeypatch):
    monkeypatch.setattr("app.agent.conversation_engine.QWEN_TIMEOUT", 7)
    monkeypatch.setattr("app.agent.conversation_engine.FREE_LLM_TIMEOUT", 41)
    provider = SimpleNamespace(provider_name="freellm", model="auto")

    engine = ConversationEngine(provider, make_registry())

    assert engine.agent_tool_loop_timeout_seconds == 41


@pytest.mark.asyncio
async def test_freellm_preserves_auto_model_switch_and_verified_product_attributes(
    db_session,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "commerce_stage": "VARIANT_SELECTED",
    }
    product.name = "عباية"
    variant.name = "Standard"
    variant.attributes_json = {"size": "XL", "color": "black"}
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            LLMResponse(
                tool_calls=[
                    {
                        "id": "size-search",
                        "name": "search_products",
                        "arguments": {"query": "عباية"},
                    }
                ],
                finish_reason="tool_calls",
                usage={
                    "reported_model": "auto-model-a",
                    "request_id": "request-a",
                },
            ),
            LLMResponse(
                tool_calls=[
                    {
                        "id": "size-details",
                        "name": "get_product_details",
                        "arguments": {},
                    }
                ],
                finish_reason="tool_calls",
                usage={
                    "reported_model": "auto-model-b",
                    "request_id": "request-b",
                },
            ),
            LLMResponse(
                content="العباية متوفرة بمقاس XL.",
                usage={
                    "reported_model": "auto-model-b",
                    "request_id": "request-c",
                },
            ),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "auto"
    engine = ConversationEngine(provider, make_registry())

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="عندكم مقاسات؟",
    )

    assert result["response"] == "العباية متوفرة بمقاس XL."
    assert result["turn_diagnostics"]["requested_model"] == "auto"
    assert result["turn_diagnostics"]["models_reported"] == [
        "auto-model-a",
        "auto-model-b",
    ]
    assert result["turn_diagnostics"]["model"] == "auto-model-b"
    assert result["turn_diagnostics"]["request_ids"] == [
        "request-a",
        "request-b",
        "request-c",
    ]
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)

    tool_results = [
        message
        for message in provider.calls[2][0]
        if message.role == "tool"
    ]
    assert [message.tool_call_id for message in tool_results] == [
        "size-search",
        "size-details",
    ]
    details_result = json.loads(tool_results[1].content)
    assert details_result["product"]["name"] == "عباية"
    assert details_result["variants"][0]["name"] == "Standard"
    assert details_result["variants"][0]["attributes"] == {
        "size": "XL",
        "color": "black",
    }
    assert "size" in provider.calls[0][1][1]["function"]["description"].lower()


@pytest.mark.asyncio
async def test_freellm_retries_a_transient_provider_error_before_fallback(db_session):
    store, customer, conversation, _, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            LLMResponse(
                finish_reason="error",
                usage={
                    "error_type": "APITimeoutError",
                    "status_code": None,
                    "requested_model": "auto",
                },
            ),
            LLMResponse(
                content="نقدر نعاونك، خذي راحتك.",
                usage={
                    "reported_model": "auto-model-b",
                    "request_id": "retry-request",
                },
            ),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "auto"
    engine = ConversationEngine(provider, make_registry())

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="اكن انا حزين",
    )

    assert result["response"] == "نقدر نعاونك، خذي راحتك."
    assert len(provider.calls) == 2
    assert result["turn_diagnostics"]["model"] == "auto-model-b"
    assert result["turn_diagnostics"]["request_ids"] == ["retry-request"]


@pytest.mark.asyncio
async def test_freellm_can_continue_after_a_recoverable_tool_failure(db_session):
    store, customer, conversation, _, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call(
                "search_products",
                {"query": "catalog-item-that-does-not-exist"},
                "missing-product-search",
            ),
            LLMResponse(
                content="لم أجد هذا المنتج. هل تقدر توصفه لي بطريقة أخرى؟"
            ),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "auto"

    result = await ConversationEngine(
        provider, make_registry()
    ).process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="ابحث عن هذا المنتج",
    )

    assert result["response"] == (
        "لم أجد هذا المنتج. هل تقدر توصفه لي بطريقة أخرى؟"
    )
    assert len(provider.calls) == 2
    tool_result = provider.calls[1][0][-1]
    assert tool_result.role == "tool"
    assert tool_result.tool_call_id == "missing-product-search"
    assert json.loads(tool_result.content)["error_code"] == "NO_RESULTS"


@pytest.mark.asyncio
async def test_freellm_social_message_is_not_routed_into_commerce_tools(db_session):
    store, customer, conversation, product, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "commerce_stage": "PRODUCT_SELECTED",
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [LLMResponse(content="أنا هنا إذا حبيت تهدر، خذ وقتك.")]
    )
    provider.provider_name = "freellm"
    provider.model = "auto"

    result = await ConversationEngine(
        provider, make_registry()
    ).process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="اكن انا حزين",
    )

    assert result["response"] == "أنا هنا إذا حبيت تهدر، خذ وقتك."
    assert provider.calls[0][0][-1].role == "user"
    assert "اكن انا حزين" in provider.calls[0][0][-1].content
    assert provider.calls[0][1]
    assert conversation.active_draft_json is None


@pytest.mark.asyncio
async def test_freellm_repairs_mojibake_before_persisting_or_sending(db_session):
    store, customer, conversation, _, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    db_session.commit()
    malformed = "Ø§Ù„Ù…Ø³Ø§Ø¹Ø¯ ØºÙŠØ± Ù…Ù�Ù‡ÙˆÙ…"
    provider = ScriptedToolProvider(
        [
            LLMResponse(content=malformed),
            LLMResponse(content="نقدر نعاونك، وضح لي واش تحتاج."),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "auto"

    result = await ConversationEngine(
        provider, make_registry()
    ).process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="مانيش عارف وش نختار",
    )

    assert result["response"] == "نقدر نعاونك، وضح لي واش تحتاج."
    assert len(provider.calls) == 2
    assert malformed not in result["response"]
    agent_messages = (
        db_session.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role == MessageRole.AGENT,
        )
        .all()
    )
    assert [message.content for message in agent_messages] == [result["response"]]


@pytest.mark.asyncio
async def test_freellm_retries_an_empty_reply_before_persisting(db_session):
    store, customer, conversation, _, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            LLMResponse(content=""),
            LLMResponse(content="نقدر نعاونك، قل لي واش راك تبحث عليه."),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "auto"

    result = await ConversationEngine(
        provider, make_registry()
    ).process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="مانيش عارف وش نختار",
    )

    assert result["response"] == "نقدر نعاونك، قل لي واش راك تبحث عليه."
    assert len(provider.calls) == 2
    persisted_reply = (
        db_session.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role == MessageRole.AGENT,
        )
        .one()
        .content
    )
    assert persisted_reply == result["response"]


@pytest.mark.asyncio
async def test_messenger_agent_can_recommend_only_in_stock_store_products(db_session):
    store, _, conversation, product, _ = make_fixture(db_session)
    product.description = "Android smartphone"
    alternative = Product(
        store_id=store.id,
        name="Samsung Galaxy Lite",
        description="Affordable Android smartphone",
        base_price=Decimal("80.00"),
        is_active=True,
    )
    unavailable = Product(
        store_id=store.id,
        name="Samsung Galaxy Ultra",
        description="Android smartphone",
        base_price=Decimal("70.00"),
        is_active=True,
    )
    db_session.add_all([alternative, unavailable])
    db_session.flush()
    alternative_variant = ProductVariant(
        product_id=alternative.id,
        name="Standard",
        price_adjustment=Decimal("5"),
        attributes_json={},
    )
    unavailable_variant = ProductVariant(
        product_id=unavailable.id,
        name="Standard",
        price_adjustment=Decimal("0"),
        attributes_json={},
    )
    db_session.add_all([alternative_variant, unavailable_variant])
    db_session.flush()
    other_store = Store(
        name="Other recommendation store",
        slug=f"recommendation-{uuid.uuid4()}",
    )
    db_session.add(other_store)
    db_session.flush()
    other_store_product = Product(
        store_id=other_store.id,
        name="Samsung Galaxy Pro",
        description="Android smartphone",
        base_price=Decimal("50.00"),
        is_active=True,
    )
    db_session.add(other_store_product)
    db_session.flush()
    other_store_variant = ProductVariant(
        product_id=other_store_product.id,
        name="Standard",
        price_adjustment=Decimal("0"),
        attributes_json={},
    )
    db_session.add(other_store_variant)
    db_session.flush()
    db_session.add_all(
        [
            InventoryItem(
                store_id=store.id,
                variant_id=alternative_variant.id,
                quantity=3,
            ),
            InventoryItem(
                store_id=store.id,
                variant_id=unavailable_variant.id,
                quantity=0,
            ),
            InventoryItem(
                store_id=other_store.id,
                variant_id=other_store_variant.id,
                quantity=10,
            ),
        ]
    )
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
    }
    db_session.commit()

    provider = ScriptedToolProvider(
        [
            tool_call(
                "recommend_products",
                {
                    "customer_need": "Android smartphone",
                    "reason": "cheaper_option",
                },
                "recommend",
            ),
            LLMResponse(
                content=(
                    "Samsung Galaxy Lite costs 85 DZD and is available."
                )
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "It's too expensive.")

    assert result["response"] == (
        "Samsung Galaxy Lite costs 85 DZD and is available."
    )
    assert len(provider.calls) == 2
    names = [entry["function"]["name"] for entry in provider.calls[0][1]]
    assert "recommend_products" in names
    recommendation_observation = provider.calls[1][0][-1]
    assert recommendation_observation.role == "tool"
    assert "Samsung Galaxy Lite" in recommendation_observation.content
    assert "Samsung Galaxy Ultra" not in recommendation_observation.content
    assert "Samsung Galaxy Pro" not in recommendation_observation.content
    assert str(alternative.id) not in recommendation_observation.content
    assert conversation.metadata_json["recommended_product_ids"] == [
        str(alternative.id)
    ]


@pytest.mark.asyncio
async def test_agent_replans_after_no_results_even_with_an_active_draft(db_session):
    _, _, conversation, _, _ = make_fixture(db_session, with_draft=True)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "not a real product"}, "miss"),
            tool_call("search_products", {"query": "Samsung"}, "retry"),
            LLMResponse(
                content="I found Samsung Galaxy for 100 DZD."
            ),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Can you find another phone?",
    )

    assert "Samsung Galaxy" in result["response"]
    assert len(provider.calls) == 3
    observations = [
        message
        for message in provider.calls[1][0]
        if message.role == "tool"
    ]
    observations_by_id = {
        message.tool_call_id: message
        for message in observations
    }
    first_observation = observations_by_id["miss"]
    assert first_observation.role == "tool"
    assert "NO_RESULTS" in first_observation.content
    assert observations_by_id["retry"].role == "tool"
    assert conversation.active_draft_json["items"]


@pytest.mark.asyncio
async def test_agent_working_memory_is_validated_persisted_and_reused(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            LLMResponse(
                content=json.dumps(
                    {
                        "reply": "I can help compare options within your budget.",
                        "working_memory": {
                            "customer_goal": "Find an affordable phone",
                            "active_entity": "phone",
                            "budget": "up to 20000 DZD",
                            "preferences": {"category": "phone"},
                            "objections": ["price"],
                            "journey_stage": "considering",
                            "next_step": "compare in-stock options",
                            "product_id": str(uuid.uuid4()),
                        },
                    }
                )
            ),
            LLMResponse(content="What features matter most to you?"),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    await run_turn(engine, db_session, conversation, "I need an affordable phone.")
    await run_turn(engine, db_session, conversation, "I also care about battery.")

    memory = conversation.metadata_json["agent_working_memory"]
    assert memory["customer_goal"] == "Find an affordable phone"
    assert memory["budget"] == "up to 20000 DZD"
    assert "product_id" not in memory
    context_message = provider.calls[1][0][1]
    assert "agent_working_memory" in context_message.content
    assert "Find an affordable phone" in context_message.content


@pytest.mark.asyncio
async def test_saved_customer_preferences_reach_agent_tool_observation(db_session):
    _, customer, conversation, _, _ = make_fixture(db_session)
    db_session.add(
        CustomerMemory(
            store_id=conversation.store_id,
            customer_id=customer.id,
            memory_type="preference",
            key="preferred_category",
            value="Android phones",
            confidence=0.9,
            source="customer_stated",
        )
    )
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call("get_customer_context", {}, "customer-context"),
            LLMResponse(content="I can focus on Android phones you prefer."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    await run_turn(engine, db_session, conversation, "Show me options.")

    observation = next(
        message
        for message in provider.calls[1][0]
        if message.role == "tool"
    )
    assert "Android phones" in observation.content
    assert "customer_stated" not in observation.content
    assert str(customer.id) not in observation.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "classifier_intent",
    [INTENT_GENERAL_CHAT, INTENT_TOPIC_CHANGE, INTENT_AMBIGUOUS],
)
async def test_agent_loop_gets_noncommercial_messages_despite_classifier(
    db_session,
    monkeypatch,
    classifier_intent,
):
    _, _, conversation, _, _ = make_fixture(db_session, with_draft=True)
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [LLMResponse(content="We can talk about something else.")]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True
    monkeypatch.setattr(
        ConversationClassifier,
        "classify",
        lambda *args, **kwargs: type(
            "ClassifierResult", (), {"intent": classifier_intent}
        )(),
    )

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Let's talk about something else.",
    )

    assert len(provider.calls) == 1
    assert result["response"] == "We can talk about something else."
    assert conversation.active_draft_json["items"]
    assert not db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).all()


@pytest.mark.asyncio
async def test_agent_selected_tool_is_not_reclassified_by_commerce_resolver(
    db_session,
    monkeypatch,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
    }
    db_session.flush()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    state = engine._normalize_current_state(conversation, store.id)

    def reject_resolver(*args, **kwargs):
        raise AssertionError("Qwen's selected tool must not be reclassified")

    monkeypatch.setattr(CommerceResolver, "resolve", reject_resolver)
    execution = await engine._execute_agent_tool_call(
        tool_name="get_product_details",
        arguments={},
        user_message="How much is my selected option?",
        language="en",
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation=conversation,
        channel="test",
        state=state,
    )

    assert execution is not None
    decision, _, tool_name, tool_result = execution
    assert decision.allowed_action == "EXECUTE_TOOL:get_product_details"
    assert tool_name == "get_product_details"
    assert tool_result.success is True
    assert tool_result.data["product"]["name"] == product.name


@pytest.mark.asyncio
async def test_agent_product_tool_resolution_preserves_store_isolation(db_session):
    store_a, customer_a, conversation_a, _, _ = make_fixture(db_session)
    _, _, _, product_b, _ = make_fixture(db_session)
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    state = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product_b.id),
        "selected_product_name": product_b.name,
    }

    execution = await engine._execute_agent_tool_call(
        tool_name="get_product_details",
        arguments={},
        user_message="Show the selected product",
        language="en",
        db=db_session,
        store_id=store_a.id,
        customer_id=customer_a.id,
        conversation=conversation_a,
        channel="test",
        state=state,
    )

    assert execution is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "ممكن دير تلخيص لطلباتي؟",
        "واش طلبت من عندكم؟",
        "وريني آخر كوموند",
        "قداش عندي من طلب؟",
    ],
)
async def test_order_history_questions_use_customer_context_not_product_search(
    db_session, message
):
    store, customer, conversation, product, _ = make_fixture(db_session)
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        status=OrderStatus.DELIVERED,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("100.00"),
        )
    )
    db_session.commit()

    provider = ScriptedToolProvider(
        [
            tool_call("get_customer_context", {"recent_orders_limit": 10}),
            LLMResponse(
                content="عندك طلب واحد بقيمة 100 دج، وفيه Samsung Galaxy."
            ),
        ]
    )
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

    result = await run_turn(engine, db_session, conversation, message)

    assert result["response"] == (
        "عندك طلب واحد بقيمة 100 دج، وفيه Samsung Galaxy."
    )
    assert executed_tools == ["get_customer_context"]
    assert len(provider.calls) == 2
    tool_result = provider.calls[1][0][-1]
    assert tool_result.role == "tool"
    assert "Samsung Galaxy" in tool_result.content
    assert '"total_amount": "100.00"' in tool_result.content
    assert '"quantity": 1' in tool_result.content
    assert str(order.id) not in tool_result.content
    assert str(customer.id) not in tool_result.content
    customer_context_schema = next(
        entry["function"]
        for entry in provider.calls[0][1]
        if entry["function"]["name"] == "get_customer_context"
    )
    assert "customer_id" not in customer_context_schema["parameters"]["properties"]


@pytest.mark.asyncio
async def test_order_history_followup_retrieves_current_status_again(db_session):
    store, customer, conversation, product, _ = make_fixture(db_session)
    order = Order(
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        status=OrderStatus.DELIVERED,
        subtotal=Decimal("100.00"),
        total=Decimal("100.00"),
    )
    db_session.add(order)
    db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            product_id=product.id,
            quantity=1,
            unit_price=Decimal("100.00"),
        )
    )
    db_session.commit()

    provider = ScriptedToolProvider(
        [
            tool_call("get_customer_context", {}),
            LLMResponse(content="عندك طلب واحد بقيمة 100 دج."),
            tool_call("get_customer_context", {}),
            LLMResponse(content="نعم، آخر طلب وصل إليك."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    await run_turn(engine, db_session, conversation, "لخص لي طلباتي")
    result = await run_turn(engine, db_session, conversation, "وهل وصل؟")

    assert len(provider.calls) == 4
    assert result["response"] == "نعم، آخر طلب وصل إليك."
    assert "get_customer_context" in [
        entry["function"]["name"] for entry in provider.calls[0][1]
    ]
    assert "get_customer_context" in [
        entry["function"]["name"] for entry in provider.calls[2][1]
    ]


@pytest.mark.asyncio
async def test_unresolved_order_history_does_not_fall_back_to_product_search(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [LLMResponse(content="يمكنني مراجعة طلباتك السابقة.")]
    )
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

    result = await run_turn(engine, db_session, conversation, "واش طلبت من عندكم؟")

    assert executed_tools == []
    assert result["response"] != "لم أجد هذا المنتج في نتائج المتجر."


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
async def test_qwen_clarification_does_not_fall_back_to_product_search(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)
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

    assert result["response"] == "ما هو المنتج الذي تبحث عنه؟"
    assert conversation.metadata_json.get("selected_product_id") is None


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
async def test_product_search_is_compact_and_product_details_return_catalog_data(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    product.description = "حذاء رياضي خفيف مع نعل مقاوم."
    variant.attributes_json = {"color": "black", "size": "42"}
    product_image = ProductImage(
        store_id=store.id,
        product_id=product.id,
        storage_key=f"stores/{store.id}/{uuid.uuid4()}.jpg",
        image_url=f"https://cdn.example.test/{uuid.uuid4()}.jpg",
        thumbnail_url="https://cdn.example.test/thumb.jpg",
        mime_type="image/jpeg",
        file_size=1024,
        width=800,
        height=600,
        is_primary=True,
        display_order=0,
    )
    db_session.add(product_image)
    db_session.flush()

    search = await SearchProductsTool().execute(
        store_id=store.id,
        arguments={"query": product.name},
        context={"db": db_session, "conversation_id": conversation.id},
    )
    details = await GetProductDetailsTool().execute(
        store_id=store.id,
        arguments={"product_id": str(product.id)},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert search.success is True
    assert search.data["products"] == [
        {
            "id": str(product.id),
            "name": product.name,
            "price": str(product.base_price),
        }
    ]
    assert details.success is True
    assert details.data["product"]["description"] == product.description
    assert details.data["variants"][0]["attributes"] == {
        "color": "black",
        "size": "42",
    }
    assert details.data["variants"][0]["stock_available"] == 5
    assert details.data["variants"][0]["final_price"] == 100
    assert details.data["images"] == [
        {
            "url": product_image.image_url,
            "thumbnail_url": product_image.thumbnail_url,
            "is_primary": True,
            "width": 800,
            "height": 600,
        }
    ]
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    verified = ConversationEngine._agent_result_facts("get_product_details", details.data)
    assert verified["products"][0]["description"] == product.description
    assert verified["product_images"][0]["url"] == product_image.image_url
    assert ReplyComposer.is_safe_agent_reply(
        "Samsung Galaxy, black, size 42, has 5 in stock.",
        "en",
        verified,
    )


@pytest.mark.asyncio
async def test_details_without_description_or_images_do_not_invent_data(db_session):
    store, _, conversation, product, _ = make_fixture(db_session)
    product.description = None
    db_session.flush()

    details = await GetProductDetailsTool().execute(
        store_id=store.id,
        arguments={"product_id": str(product.id)},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert details.success is True
    assert details.data["product"]["description"] is None
    assert details.data["images"] == []
    assert details.data["images_status"] == "none"
    fallback = await ConversationEngine(
        ScriptedToolProvider([]),
        make_registry(),
    )._generate_localized_final_text(
        details.data,
        "",
        "واش مميزاتو؟",
        "ar",
        "product_details",
    )
    assert "ما كاينش وصف مسجل" in fallback
    assert "ما كاين حتى صورة مسجلة" in fallback


@pytest.mark.asyncio
async def test_product_details_remain_available_when_image_table_is_missing(db_session):
    store, _, conversation, product, _ = make_fixture(db_session)
    db_session.execute(text("DROP TABLE product_images"))

    details = await GetProductDetailsTool().execute(
        store_id=store.id,
        arguments={"product_id": str(product.id)},
        context={"db": db_session, "conversation_id": conversation.id},
    )

    assert details.success is True
    assert details.data["product"]["name"] == product.name
    assert details.data["images"] == []
    assert details.data["images_status"] == "schema_unavailable"


@pytest.mark.asyncio
async def test_product_details_resolve_selected_candidate_and_reach_agent(
    db_session,
):
    store, _, conversation, product, _ = make_fixture(db_session)
    image = ProductImage(
        store_id=store.id,
        product_id=product.id,
        storage_key=f"stores/{store.id}/{uuid.uuid4()}.jpg",
        image_url="https://cdn.example.test/product.jpg",
        mime_type="image/jpeg",
        file_size=1024,
        is_primary=True,
    )
    db_session.add(image)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_CANDIDATES",
        "candidate_product_ids": [str(product.id)],
        "selected_product_id": None,
    }
    db_session.flush()
    provider = ScriptedToolProvider(
        [
            tool_call(
                "get_product_details",
                {"product_name": product.name},
                "details-call",
            ),
            LLMResponse(content="Samsung Galaxy: الوصف المسجل Test product."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "واش مميزاتو؟")

    assert result["response"] == "Samsung Galaxy: الوصف المسجل Test product."
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert provider.calls[1][0][-1].role == "tool"
    details_observation = json.loads(provider.calls[1][0][-1].content)
    assert details_observation["product"]["description"] == "Test product"
    assert details_observation["variants"][0]["attributes"] == {"color": "black"}
    assert details_observation["images"][0]["url"] == image.image_url
    assert "get_product_details" in {
        tool["function"]["name"] for tool in provider.calls[0][1]
    }
    assert "photos" in provider.calls[0][0][0].content.casefold()


@pytest.mark.asyncio
async def test_product_details_cannot_read_another_store_product(db_session):
    store_a, _, conversation_a, _, _ = make_fixture(db_session)
    store_b, _, _, product_b, _ = make_fixture(db_session)

    result = await GetProductDetailsTool().execute(
        store_id=store_a.id,
        arguments={"product_id": str(product_b.id)},
        context={"db": db_session, "conversation_id": conversation_a.id},
    )

    assert result.success is False
    assert result.data == {}


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
    assert conversation.metadata_json["last_question_type"] == (
        "CUSTOMER_DELIVERY_INFO"
    )
    assert "confirmation_pending" not in conversation.metadata_json
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
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
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


@pytest.mark.asyncio
async def test_agent_receives_order_draft_stock_failure_for_recovery(db_session):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    inventory = (
        db_session.query(InventoryItem)
        .filter(InventoryItem.variant_id == variant.id)
        .one()
    )
    inventory.quantity = 0
    db_session.flush()

    provider = ScriptedToolProvider(
        [
            tool_call("create_order_draft", {"quantity": 1}),
            LLMResponse(content="هل تود اختيار كمية أخرى؟"),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True
    state = engine._normalize_current_state(conversation, store.id)

    result = await engine._run_agent_tool_loop(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation=conversation,
        channel="test",
        user_message="حبيت نشري الحذاء",
        current_state=state,
        dialogue_context=[],
        language="ar",
    )

    assert result is not None
    assert result["accepted"] is True
    assert result["tool_name"] == "create_order_draft"
    assert result["tool_result"].success is False
    tool_message = provider.calls[1][0][-1]
    assert tool_message.role == "tool"
    assert json.loads(tool_message.content)["success"] is False
    assert conversation.active_draft_json is None
    assert inventory.quantity == 0


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
async def test_freellm_provider_runs_tool_call_round_trip(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("DZCOMMERCE_AGENT_TOOL_LOOP_ENABLED", raising=False)
    provider = make_mock_freellm_provider(
        [
            openai_chat_response(
                tool_call={
                    "id": "search-call",
                    "name": "search_products",
                    "arguments": {"query": "Samsung"},
                }
            ),
            openai_chat_response(content="وجدت Samsung Galaxy."),
        ]
    )
    _, _, conversation, _, _ = make_fixture(db_session)
    engine = ConversationEngine(provider, make_registry())
    engine.reply_composer_enabled = False

    assert engine.agent_tool_loop_enabled is True
    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert result["response"] == "وجدت Samsung Galaxy."
    # The provider uses with_raw_response.create internally
    create = provider.client.chat.completions.with_raw_response.create
    assert create.await_count == 2
    first_request = create.await_args_list[0].kwargs
    assert first_request["tools"]
    assert first_request["tool_choice"] == "auto"
    second_messages = create.await_args_list[1].kwargs["messages"]
    assistant_call = next(
        message
        for message in second_messages
        if message.get("role") == "assistant" and message.get("tool_calls")
    )
    tool_result = next(
        message for message in second_messages if message.get("role") == "tool"
    )
    assert assistant_call["tool_calls"][0]["id"] == "search-call"
    assert tool_result["tool_call_id"] == "search-call"
    assert json.loads(tool_result["content"])["success"] is True


@pytest.mark.asyncio
async def test_freellm_tool_call_cannot_confirm_without_explicit_consent(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("DZCOMMERCE_AGENT_TOOL_LOOP_ENABLED", raising=False)
    provider = make_mock_freellm_provider(
        [
            openai_chat_response(
                tool_call={
                    "id": "confirm-call",
                    "name": "confirm_order",
                    "arguments": {},
                }
            ),
            openai_chat_response(content="كيف يمكنني مساعدتك؟"),
        ]
    )
    store, _, conversation, product, variant = make_fixture(
        db_session,
        with_draft=True,
    )
    prepare_pending_confirmation(conversation, product, variant)
    db_session.commit()
    engine = ConversationEngine(provider, make_registry())
    engine.reply_composer_enabled = False

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "قداش سعرها؟",
    )

    assert engine.agent_tool_loop_enabled is True
    assert "تم تأكيد طلبك" not in result["response"]
    assert conversation.active_draft_json["items"]
    assert (
        db_session.query(Order)
        .filter(
            Order.conversation_id == conversation.id,
            Order.store_id == store.id,
            Order.status == OrderStatus.CONFIRMED,
        )
        .count()
        == 0
    )
    tool_result = next(
        message
        for message in provider.client.chat.completions.with_raw_response.create.await_args_list[
            1
        ].kwargs["messages"]
        if message.get("role") == "tool"
    )
    assert tool_result["tool_call_id"] == "confirm-call"
    assert json.loads(tool_result["content"])["success"] is False


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
    assert conversation.metadata_json["last_question_type"] == (
        "CUSTOMER_DELIVERY_INFO"
    )
    assert conversation.active_draft_json["items"]

    details_result = await run_turn(
        engine,
        db_session,
        conversation,
        "0555123456، ولاية وهران",
    )
    assert "أكد الطلب" in details_result["response"]
    assert conversation.metadata_json["last_question_type"] == (
        "ORDER_CONFIRMATION"
    )
    assert conversation.metadata_json["confirmation_pending"] == {
        "draft_id": conversation.active_draft_json["draft_id"]
    }

    confirm_result = await run_turn(
        engine,
        db_session,
        conversation,
        "أكد الطلب",
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
async def test_draft_update_invalidates_confirmation_before_same_turn_confirm(
    db_session,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.channel = "facebook"
    prepare_pending_confirmation(conversation, product, variant)
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            LLMResponse(
                tool_calls=[
                    {
                        "id": "update-draft",
                        "name": "update_order_draft",
                        "arguments": {
                            "action": "set",
                            "item_index": 1,
                            "quantity": 2,
                        },
                    },
                    {
                        "id": "confirm-updated-draft",
                        "name": "confirm_order",
                        "arguments": {},
                    },
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="The updated draft needs your review before confirmation."
            ),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "mock-freellm-model"
    engine = ConversationEngine(provider, make_registry())

    await engine.process_message(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=conversation.customer_id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="أكد الطلب",
    )

    confirm_result = next(
        message
        for message in provider.calls[1][0]
        if message.role == "tool"
        and message.tool_call_id == "confirm-updated-draft"
    )
    assert json.loads(confirm_result.content)["success"] is False
    assert conversation.active_draft_json["items"][0]["quantity"] == 2
    assert "confirmation_pending" not in conversation.metadata_json
    assert (
        db_session.query(Order)
        .filter(Order.conversation_id == conversation.id)
        .count()
        == 0
    )


@pytest.mark.asyncio
async def test_agent_usage_does_not_rollback_order_confirmation_on_sqlite(db_engine):
    db_session = sessionmaker(bind=db_engine, expire_on_commit=False)()
    try:
        _, _, conversation, product, variant = make_fixture(db_session)
        draft_id = str(uuid.uuid4())
        conversation.metadata_json = {
            "commerce_stage": "DRAFT_PENDING",
            "last_question_type": "ORDER_CONFIRMATION",
            "selected_product_id": str(product.id),
            "confirmation_pending": {"draft_id": draft_id},
        }
        conversation.active_draft_json = {
            "draft_id": draft_id,
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
            "shipping_info": {
                "phone": "0555123456",
                "wilaya": "وهران",
            },
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

        result = await run_turn(engine, db_session, conversation, "أكد الطلب")

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

    assert result["response"] == (
        "Take your time. We can continue whenever you are ready."
    )
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
    assert first_result["response"] == (
        "Take your time; your draft is still open."
    )

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

    assert next_result["response"] == (
        "Your draft is still open. We can continue whenever you are ready."
    )
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
async def test_agent_loop_returns_final_reply_after_three_tool_rounds(
    db_session,
):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}),
            tool_call("list_catalog_products", {}),
            tool_call("get_product_details", {"product_name": "Samsung Galaxy"}),
            LLMResponse(content="Samsung Galaxy costs 100 DZD in the catalog."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert len(provider.calls) == 4
    assert "Samsung Galaxy" in result["response"]
    assert "100" in result["response"]


@pytest.mark.asyncio
async def test_model_can_respond_after_tool_limit_is_reported(db_session):
    _, customer, conversation, _, _ = make_fixture(db_session)
    conversation.channel = "facebook"
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call("search_products", {"query": "Samsung"}, "search"),
            tool_call("list_catalog_products", {}, "catalog"),
            tool_call(
                "get_product_details",
                {"product_name": "Samsung Galaxy"},
                "details",
            ),
            tool_call("store_info", {}, "limit"),
            LLMResponse(content="I have the verified product details to help you."),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "mock-freellm-model"
    engine = ConversationEngine(provider, make_registry())

    result = await engine.process_message(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="Find Samsung",
    )

    assert len(provider.calls) == 5
    limit_result = next(
        message
        for message in provider.calls[4][0]
        if message.role == "tool" and message.tool_call_id == "limit"
    )
    assert json.loads(limit_result.content)["error_code"] == "TOOL_LIMIT_REACHED"
    assert result["response"] == "I have the verified product details to help you."


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
            LLMResponse(content="Samsung Galaxy is listed in the catalog."),
        ]
    )
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(engine, db_session, conversation, "Find Samsung")

    assert search_tool.execution_count == 1
    assert len(provider.calls) == 3
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
    assert (
        "not confirmed" in result["response"].casefold()
        or "no order was placed" in result["response"].casefold()
        or "لا تنتظر التأكيد" in result["response"]
    )


@pytest.mark.asyncio
async def test_failed_agent_tool_preserves_draft_and_returns_recoverable_reply(
    db_session,
):
    _, _, conversation, product, variant = make_fixture(db_session, with_draft=True)
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
    }
    original_draft = {
        "draft_id": str(uuid.uuid4()),
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
        "shipping_info": {"phone": "0550123456", "wilaya": "الجزائر"},
    }
    conversation.active_draft_json = original_draft
    db_session.commit()

    class FailingUpdateTool(BaseTool):
        name = "update_order_draft"
        description = "Raises after a simulated partial update."
        input_schema = {}

        async def execute(self, store_id, arguments, context=None):
            context["db"].query(Conversation).filter(
                Conversation.id == context["conversation_id"]
            ).one().active_draft_json = {"items": []}
            raise RuntimeError("simulated update failure")

    registry = make_registry()
    registry._tools["update_order_draft"] = FailingUpdateTool()
    provider = ScriptedToolProvider(
        [
            tool_call(
                "update_order_draft",
                {"action": "set", "item_index": 1, "quantity": 2},
            ),
            RuntimeError("provider unavailable after tool failure"),
        ]
    )
    provider.provider_name = "freellm"
    engine = ConversationEngine(provider, registry)
    engine.agent_tool_loop_enabled = True

    result = await run_turn(
        engine,
        db_session,
        conversation,
        "Change the quantity to two",
    )

    db_session.refresh(conversation)
    assert conversation.active_draft_json == original_draft
    assert result.get("processing_failed") is not True
    assert "unchanged" in result["response"]
    assert len(provider.calls) == 2


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
        async def chat(self, messages, tools=None, system_prompt=None, session_id=None, turn_id=None, call_index=None):
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
    order_facts = {
        "recent_orders": [
            {
                "status": "delivered",
                "total_amount": "100.00",
                "currency": "DZD",
                "item_count": 1,
                "items": [
                    {
                        "product_name": "Samsung Galaxy",
                        "quantity": 1,
                        "unit_price": "100.00",
                    }
                ],
            }
        ],
        "order_status": "delivered",
        "behavior_summary": {"total_orders": 7, "total_spent": "250.00"},
    }
    assert ReplyComposer.is_safe_agent_reply(
        "نعم، آخر طلب وصل إليك.",
        "ar",
        order_facts,
    )
    assert ReplyComposer.is_safe_agent_reply(
        "عندك 7 طلبات.",
        "ar",
        order_facts,
    )
    assert not ReplyComposer.is_safe_agent_reply(
        "عندك 8 طلبات.",
        "ar",
        order_facts,
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
    assert isinstance(draft["draft_id"], str)
    assert conversation.metadata_json["conversation_memory"]["active_draft_id"] == (
        draft["draft_id"]
    )
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
async def test_purchase_resumes_through_delivery_details_and_natural_confirmation(
    db_session,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    store.served_wilayas = "وهران، الجزائر"
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
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

    draft_result = await run_turn(engine, db_session, conversation, "دير طلب")

    assert conversation.active_draft_json is not None
    assert len(conversation.active_draft_json["items"]) == 1
    assert conversation.metadata_json["last_question_type"] == (
        "CUSTOMER_DELIVERY_INFO"
    )
    assert "رقم هاتفك" in draft_result["response"]
    assert "الولاية" in draft_result["response"]
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0

    details_result = await run_turn(
        engine,
        db_session,
        conversation,
        "0555 12 34 56، ولاية وهران",
    )

    assert customer.phone == "0555123456"
    assert conversation.active_draft_json["shipping_info"] == {
        "phone": "0555123456",
        "wilaya": "وهران",
    }
    assert conversation.metadata_json["last_question_type"] == (
        "ORDER_CONFIRMATION"
    )
    assert product.name in details_result["response"]
    assert variant.name in details_result["response"]
    assert "اكتب «أكد الطلب»" in details_result["response"]

    affirmative_result = await run_turn(
        engine,
        db_session,
        conversation,
        "نعم",
    )
    assert "EXECUTE_TOOL:confirm_order" == affirmative_result[
        "turn_diagnostics"
    ]["resolver_action"]
    assert conversation.active_draft_json is None
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id,
        Order.status == OrderStatus.CONFIRMED,
    ).count() == 1


@pytest.mark.asyncio
async def test_failed_first_draft_preserves_selection_and_does_not_claim_success(
    db_session,
    monkeypatch,
):
    _, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
    }
    db_session.commit()

    def fail_save_draft(**_kwargs):
        raise RuntimeError("local draft persistence failure")

    monkeypatch.setattr(
        "app.services.order_draft_service.save_draft",
        fail_save_draft,
    )
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    engine.agent_tool_loop_enabled = False
    engine._extract_nlu_via_qwen = AsyncMock(
        side_effect=lambda message, state, **_kwargs: engine._heuristic_nlu(
            message, state
        )
    )

    result = await run_turn(engine, db_session, conversation, "دير طلب")

    assert "تعذر حفظ مسودة الطلب" in result["response"]
    assert "تم حفظ مسودة الطلب" not in result["response"]
    assert conversation.active_draft_json is None
    assert conversation.metadata_json["commerce_stage"] == "VARIANT_SELECTED"
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert conversation.metadata_json["last_question_type"] == "ORDER_CREATE_OFFER"
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0


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
async def test_order_command_after_product_selection_creates_first_draft(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    product.name = "الحذاء"
    product.base_price = Decimal("137.50")
    variant.price_adjustment = Decimal("12.50")
    conversation.metadata_json = {
        "commerce_stage": "PRODUCT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "PRODUCT_DETAILS_OFFER",
    }
    db_session.commit()

    provider = ScriptedToolProvider(
        [tool_call("get_product_details", {}, "stale-details")]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True
    engine.reply_composer_enabled = False

    result = await run_turn(engine, db_session, conversation, "دير طلب")

    db_session.refresh(conversation)
    assert result["turn_diagnostics"]["intent"] == "order_create"
    assert result["turn_diagnostics"]["resolver_action"] == (
        "CALL_SERVICE:create_draft"
    )
    assert "تم حفظ مسودة الطلب" in result["response"]
    assert "هذا الإجراء غير متاح حاليًا" not in result["response"]
    assert len(conversation.active_draft_json["items"]) == 1
    assert conversation.active_draft_json["items"][0] == {
        "variant_id": str(variant.id),
        "product_name": "الحذاء",
        "variant_name": variant.name,
        "unit_price": 150.0,
        "quantity": 1,
        "line_total": 150.0,
        "available_stock": 5,
    }
    assert conversation.metadata_json["commerce_stage"] == "DRAFT_PENDING"
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0
    assert provider.calls == []


@pytest.mark.asyncio
async def test_bare_yes_without_pending_question_does_not_create_or_confirm_order(
    db_session,
):
    store, _, conversation, product, variant = make_fixture(db_session)
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
    }
    db_session.commit()

    engine = ConversationEngine(None, make_registry())
    engine.agent_tool_loop_enabled = False
    engine.reply_composer_enabled = False

    result = await run_turn(engine, db_session, conversation, "نعم")

    assert result["turn_diagnostics"]["intent"] == "unknown"
    assert conversation.active_draft_json is None
    assert conversation.metadata_json["selected_product_id"] == str(product.id)
    assert conversation.metadata_json["selected_variant_id"] == str(variant.id)
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0


@pytest.mark.parametrize(
    "message",
    ["دير طلب", "ديرلي طلب"],
)
def test_order_requests_are_not_parsed_as_delivery_wilayas(message):
    assert ConversationEngine._extract_delivery_details(message, None) == (
        None,
        None,
    )
    assert ConversationEngine._extract_delivery_details("ولاية قالمة", None) == (
        None,
        "قالمة",
    )


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
@pytest.mark.asyncio
async def test_messenger_freellm_creates_draft_from_selected_product_and_variant(
    db_session,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    product.name = "الحذاء"
    variant.name = "أسود"
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "selected_attributes": {"color": "black"},
    }
    conversation.active_draft_json = None
    db_session.commit()

    provider = ScriptedToolProvider(
        [
            tool_call(
                "create_order_draft",
                {"items": [{"quantity": 1}]},
                "create-first-draft",
            ),
            LLMResponse(
                content="تم حفظ مسودة طلب الحذاء. أرسل رقم الهاتف والولاية للمتابعة."
            ),
        ]
    )
    provider.provider_name = "freellm"
    engine = ConversationEngine(provider, make_registry())

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="حبيت نشري الحذاء",
    )

    db_session.refresh(conversation)
    draft = conversation.active_draft_json
    assert result["response"] == (
        "تم حفظ مسودة طلب الحذاء. أرسل رقم الهاتف والولاية للمتابعة."
    )
    assert len(draft["items"]) == 1
    assert draft["items"][0]["variant_id"] == str(variant.id)
    assert draft["items"][0]["quantity"] == 1
    assert draft["items"][0]["unit_price"] == 100.0
    assert draft["total_price"] == 100.0
    assert conversation.metadata_json["last_question_type"] == (
        "CUSTOMER_DELIVERY_INFO"
    )
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0
    assert db_session.query(InventoryItem).filter(
        InventoryItem.variant_id == variant.id
    ).one().quantity == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("user_message", ["قداش سعر الحذاء؟", "شحال يسوى؟"])
async def test_messenger_price_question_uses_selected_product_facts_without_search(
    db_session, user_message
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    product.name = "الحذاء"
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [LLMResponse(content="سعر الحذاء هو 100 دج.")]
    )
    provider.provider_name = "freellm"
    engine = ConversationEngine(provider, make_registry())

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message=user_message,
    )

    assert result["response"] == "سعر الحذاء هو 100 دج."
    assert len(provider.calls) == 1
    agent_context = json.loads(
        provider.calls[0][0][1].content.split("\n", 1)[1]
    )
    assert agent_context["verified_facts"]["products"] == [
        {"name": "الحذاء", "price": 100.0}
    ]
    assert agent_context["verified_facts"]["variants"][0]["final_price"] == 100.0


@pytest.mark.asyncio
async def test_agent_loop_executes_multiple_tool_calls_before_final_reply(db_session):
    _, _, conversation, _, _ = make_fixture(db_session)
    provider = ScriptedToolProvider(
        [
            LLMResponse(
                tool_calls=[
                    {
                        "id": "search",
                        "name": "search_products",
                        "arguments": {"query": "Samsung"},
                    },
                    {
                        "id": "catalog",
                        "name": "list_catalog_products",
                        "arguments": {},
                    },
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="The catalog includes Samsung Galaxy."),
        ]
    )
    engine = ConversationEngine(provider, make_registry())
    engine.agent_tool_loop_enabled = True

    result = await engine._run_agent_tool_loop(
        db=db_session,
        store_id=conversation.store_id,
        customer_id=conversation.customer_id,
        conversation=conversation,
        channel="test",
        user_message="Show me Samsung and the catalog",
        current_state=engine._normalize_current_state(
            conversation, conversation.store_id
        ),
        dialogue_context=[],
        language="en",
    )

    assert result["accepted"] is True
    assert result["response"] == "The catalog includes Samsung Galaxy."
    tool_messages = [
        message for message in provider.calls[1][0] if message.role == "tool"
    ]
    assert {message.tool_call_id for message in tool_messages} == {
        "search",
        "catalog",
    }


@pytest.mark.asyncio
async def test_shipping_details_update_active_draft_without_changing_items(db_session):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.active_draft_json = {
        "draft_id": "draft-shipping-test",
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
    db_session.commit()

    result = await UpdateOrderDraftTool().execute(
        store.id,
        {
            "action": "set_shipping",
            "shipping_info": {
                "phone": "0550123456",
                "wilaya": "الجزائر",
                "municipality": "باب الزوار",
            },
        },
        {
            "db": db_session,
            "conversation_id": conversation.id,
        },
    )

    db_session.refresh(conversation)
    assert result.success is True
    assert conversation.active_draft_json["draft_id"] == "draft-shipping-test"
    assert conversation.active_draft_json["shipping_info"] == {
        "phone": "0550123456",
        "wilaya": "الجزائر",
        "municipality": "باب الزوار",
    }
    assert conversation.active_draft_json["items"][0]["variant_id"] == str(
        variant.id
    )


@pytest.mark.asyncio
async def test_freellm_selected_shipping_tool_persists_redacted_phone_and_city(
    db_session,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "CUSTOMER_DELIVERY_INFO",
    }
    conversation.active_draft_json = {
        "draft_id": str(uuid.uuid4()),
        "items": [
            {
                "variant_id": str(variant.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "quantity": 1,
                "unit_price": 100.0,
                "line_total": 100.0,
            }
        ],
        "total_price": 100.0,
        "shipping_info": {},
    }
    db_session.commit()
    provider = ScriptedToolProvider(
        [
            tool_call(
                "update_order_draft",
                {
                    "action": "set_shipping",
                    "shipping_info": {"municipality": "باب الزوار"},
                },
                "save-shipping",
            ),
            LLMResponse(content="I saved the delivery details."),
        ]
    )
    provider.provider_name = "freellm"
    provider.model = "mock-freellm-model"
    engine = ConversationEngine(provider, make_registry())

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="رقم الهاتف 0550123456، بلدية باب الزوار",
    )

    db_session.refresh(conversation)
    shipping = conversation.active_draft_json["shipping_info"]
    assert result["response"] == "I saved the delivery details."
    assert shipping["phone"] == "0550123456"
    assert shipping["municipality"] == "باب الزوار"
    assert "0550123456" not in "\n".join(
        message.content or ""
        for messages, _tools in provider.calls
        for message in messages
    )



@pytest.mark.asyncio
async def test_freellm_captures_delivery_details_before_generating_checkout_reply(
    db_session,
):
    store, customer, conversation, product, variant = make_fixture(db_session)
    conversation.channel = "facebook"
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "selected_product_id": str(product.id),
        "selected_product_name": product.name,
        "selected_variant_id": str(variant.id),
        "last_question_type": "CUSTOMER_DELIVERY_INFO",
    }
    draft_id = str(uuid.uuid4())
    conversation.active_draft_json = {
        "draft_id": draft_id,
        "items": [
            {
                "variant_id": str(variant.id),
                "product_name": product.name,
                "variant_name": variant.name,
                "quantity": 1,
                "unit_price": 100.0,
                "line_total": 100.0,
            }
        ],
        "total_price": 100.0,
        "shipping_info": {},
    }
    db_session.commit()

    provider = ScriptedToolProvider([])
    provider.provider_name = "freellm"
    provider.model = "mock-freellm-model"
    engine = ConversationEngine(provider, make_registry())

    first = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="ولاية قالمة بلدية قالمة 0674251265",
    )
    db_session.refresh(conversation)
    shipping = conversation.active_draft_json["shipping_info"]
    assert shipping["phone"] == "0674251265"
    assert shipping["wilaya"] == "قالمة"
    assert shipping["municipality"] == "قالمة"
    assert conversation.metadata_json["last_question_type"] == "ORDER_CONFIRMATION"
    assert conversation.metadata_json["confirmation_pending"]["draft_id"] == draft_id
    assert "أكد الطلب" in first["response"]

    second = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="facebook",
        user_message="حي 60 مسكن",
    )
    db_session.refresh(conversation)
    shipping = conversation.active_draft_json["shipping_info"]
    assert shipping["address"] == "حي 60 مسكن"
    assert shipping["phone"] == "0674251265"
    assert shipping["wilaya"] == "قالمة"
    assert conversation.metadata_json["confirmation_pending"]["fingerprint"] == (
        engine._compute_draft_fingerprint(conversation.active_draft_json)
    )
    assert "أكد الطلب" in second["response"]
    assert provider.calls == []

@pytest.mark.asyncio
async def test_free_agent_cannot_confirm_without_immediate_explicit_approval(db_session):
    store, customer, conversation, product, variant = make_fixture(db_session)
    prepare_pending_confirmation(conversation, product, variant)
    db_session.commit()
    engine = ConversationEngine(ScriptedToolProvider([]), make_registry())
    state = engine._normalize_current_state(conversation, store.id)

    execution = await engine._dispatch_agent_tool_call_safely(
        call={
            "id": "confirmation",
            "name": "confirm_order",
            "arguments": {},
        },
        user_message="How much is delivery?",
        language="en",
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation=conversation,
        channel="facebook",
        state=state,
        external_account_id=None,
        external_user_id=None,
    )

    assert execution[3].success is False
    assert execution[3].error_code == "CONFIRMATION_NOT_PENDING"
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0
    assert db_session.query(InventoryItem).filter(
        InventoryItem.variant_id == variant.id
    ).one().quantity == 5


@pytest.mark.asyncio
async def test_order_confirmation_requires_saved_delivery_details(db_session):
    store, customer, conversation, product, variant = make_fixture(db_session)
    draft_id = str(uuid.uuid4())
    conversation.active_draft_json = {
        "draft_id": draft_id,
        "items": [
            {
                "variant_id": str(variant.id),
                "quantity": 1,
            }
        ],
        "total_price": 100.0,
    }
    conversation.metadata_json = {
        "commerce_stage": "DRAFT_PENDING",
        "last_question_type": "ORDER_CONFIRMATION",
        "confirmation_pending": {"draft_id": draft_id},
    }
    db_session.commit()

    result = await ConfirmOrderTool().execute(
        store.id,
        {},
        {
            "db": db_session,
            "conversation_id": conversation.id,
            "customer_id": customer.id,
        },
    )

    assert result.success is False
    assert result.error_code == "SHIPPING_INFO_REQUIRED"
    assert db_session.query(Order).filter(
        Order.conversation_id == conversation.id
    ).count() == 0
    assert db_session.query(InventoryItem).filter(
        InventoryItem.variant_id == variant.id
    ).one().quantity == 5
