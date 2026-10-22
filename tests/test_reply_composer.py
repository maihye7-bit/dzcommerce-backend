import asyncio
import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.agent.conversation_engine import ConversationEngine
from app.agent.providers.base import LLMResponse
from app.agent.reply_composer import ReplyComposer
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.product import Product
from app.models.store import Store


class FixedProvider:
    def __init__(self, content=None, *, error=None, delay=0):
        self.content = content
        self.error = error
        self.delay = delay
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.calls.append((messages, tools))
        if self.error:
            raise self.error
        if self.delay:
            await asyncio.sleep(self.delay)
        return LLMResponse(content=self.content)


@pytest.mark.asyncio
async def test_composer_accepts_verified_product_and_exact_price():
    provider = FixedProvider(
        '{"reply":"I found Samsung Galaxy A54. Price: 75,000 DZD. '
        'Would you like its details?"}'
    )
    composer = ReplyComposer(provider)

    reply = await composer.compose(
        customer_message="How much is the Samsung?",
        intent="product_details",
        language="en",
        conversation_context={"commerce_stage": "EMPTY", "last_question_type": None},
        products=[{"name": "Samsung Galaxy A54", "price": "75,000"}],
    )

    assert reply is not None
    assert "75,000 DZD" in reply
    assert len(provider.calls) == 1
    assert provider.calls[0][1] is None


@pytest.mark.asyncio
async def test_composer_accepts_missing_price_without_inventing_one():
    provider = FixedProvider(
        '{"reply":"I found Laptop Pro. Would you like to see its details?"}'
    )

    reply = await ReplyComposer(provider).compose(
        customer_message="Show me Laptop Pro",
        intent="product_search",
        language="en",
        conversation_context={"commerce_stage": "EMPTY", "last_question_type": None},
        products=[{"name": "Laptop Pro", "price": None}],
    )

    assert reply == "I found Laptop Pro. Would you like to see its details?"


@pytest.mark.parametrize(
    ("language", "reply"),
    [
        (
            "ar",
            "وجدت المنتج Widget A. السعر: 1,250 دج. هل تريد معرفة تفاصيله؟",
        ),
        (
            "fr",
            "J’ai trouvé Widget A. Prix : 1,250 DZD. Voulez-vous voir ses détails ?",
        ),
    ],
)
@pytest.mark.asyncio
async def test_composer_accepts_validated_arabic_and_french_replies(language, reply):
    provider = FixedProvider(json.dumps({"reply": reply}, ensure_ascii=False))

    result = await ReplyComposer(provider).compose(
        customer_message="Widget A",
        intent="product_search",
        language=language,
        conversation_context={"commerce_stage": "EMPTY", "last_question_type": None},
        products=[{"name": "Widget A", "price": "1,250"}],
    )

    assert result == reply


@pytest.mark.parametrize(
    "reply",
    [
        "I found Samsung Galaxy A54 and iPhone. Would you like details?",
        "I found Samsung Galaxy A54 and آيفون. Would you like details?",
        "Samsung Galaxy A54 is in stock.",
        "Samsung Galaxy A54 costs 99,000 DZD.",
        "Samsung Galaxy A54 costs 75,000 USD.",
        "Samsung Galaxy A54 product_id 123e4567-e89b-42d3-a456-426614174000.",
        "",
    ],
)
@pytest.mark.asyncio
async def test_composer_rejects_unverified_or_invalid_claims(reply):
    provider = FixedProvider(json.dumps({"reply": reply}))

    result = await ReplyComposer(provider).compose(
        customer_message="Find a phone",
        intent="product_search",
        language="en",
        conversation_context={"commerce_stage": "EMPTY", "last_question_type": None},
        products=[{"name": "Samsung Galaxy A54", "price": "75,000"}],
    )

    assert result is None


@pytest.mark.asyncio
async def test_composer_requires_all_returned_products_to_be_named():
    provider = FixedProvider(
        '{"reply":"I found Samsung Galaxy A54. Which one do you want?"}'
    )

    result = await ReplyComposer(provider).compose(
        customer_message="Samsung",
        intent="product_search",
        language="en",
        conversation_context={"commerce_stage": "EMPTY", "last_question_type": None},
        products=[
            {"name": "Samsung Galaxy A54", "price": "75,000"},
            {"name": "Samsung Galaxy S24", "price": None},
        ],
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider",
    [
        FixedProvider(error=RuntimeError("provider failure")),
        FixedProvider(content="not JSON"),
        FixedProvider(content='{"reply":"I found Laptop Pro."}', delay=0.05),
    ],
)
async def test_composer_rejects_provider_errors_invalid_json_and_timeout(provider):
    composer = ReplyComposer(provider, timeout_seconds=0.005)

    result = await composer.compose(
        customer_message="Find Laptop Pro",
        intent="product_search",
        language="en",
        conversation_context={"commerce_stage": "EMPTY", "last_question_type": None},
        products=[{"name": "Laptop Pro", "price": None}],
    )

    assert result is None


class SearchPilotProvider:
    def __init__(self, reply='{"reply":"I found Widget A. Would you like details?"}'):
        self.reply = reply
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.calls.append((messages, tools))
        if len(self.calls) == 1:
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": "product_search",
                        "product_mention": "Widget",
                        "language": "en",
                        "confidence": 0.95,
                    }
                )
            )
        return LLMResponse(content=self.reply)


def create_conversation(db_session, store_name):
    store = Store(name=store_name, slug=f"reply-{uuid.uuid4()}")
    db_session.add(store)
    db_session.flush()
    customer = Customer(store_id=store.id, name="Test")
    db_session.add(customer)
    db_session.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="test",
        status=ConversationStatus.ACTIVE,
        metadata_json={},
    )
    db_session.add(conversation)
    db_session.commit()
    return store, customer, conversation


@pytest.mark.asyncio
async def test_search_composer_disabled_path_keeps_template(db_session):
    store, customer, conversation = create_conversation(db_session, "Disabled store")
    db_session.add(
        Product(
            store_id=store.id,
            name="Widget A",
            base_price=Decimal("1250"),
            is_active=True,
        )
    )
    db_session.commit()
    provider = SearchPilotProvider()
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(provider, registry)
    engine.reply_composer_enabled = False

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="Do you have Widget?",
    )

    assert result["response"] == (
        "I found: Widget A. Price: 1,250 DZD. "
        "Would you like its details or choose an option to order?"
    )
    assert len(provider.calls) == 1
    registry.aexecute.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_composer_receives_only_this_store_verified_search_facts(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("DZCOMMERCE_REPLY_COMPOSER_ENABLED", raising=False)
    store, customer, conversation = create_conversation(db_session, "Store A")
    other_store, _, _ = create_conversation(db_session, "Store B")
    own_product = Product(
        store_id=store.id,
        name="Widget A",
        base_price=Decimal("1250"),
        sku="PRIVATE-SKU-A",
        is_active=True,
    )
    other_product = Product(
        store_id=other_store.id,
        name="Widget B",
        base_price=Decimal("9999"),
        sku="PRIVATE-SKU-B",
        is_active=True,
    )
    db_session.add_all([own_product, other_product])
    db_session.commit()
    provider = SearchPilotProvider(
        '{"reply":"I found Widget A. Price: 1,250 DZD. Would you like details?"}'
    )
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(provider, registry)
    assert engine.reply_composer_enabled is True

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="Do you have Widget?",
    )

    assert result["response"] == (
        "I found Widget A. Price: 1,250 DZD. Would you like details?"
    )
    assert registry.aexecute.await_count == 1
    assert provider.calls[1][1] is None
    payload = json.loads(provider.calls[1][0][-1].content)
    assert payload["verified_products"] == [
        {"name": "Widget A", "price": "1,250"}
    ]
    serialized_payload = json.dumps(payload)
    assert str(own_product.id) not in serialized_payload
    assert str(other_product.id) not in serialized_payload
    assert "PRIVATE-SKU" not in serialized_payload
    assert "Store A" not in serialized_payload
    assert "Widget B" not in serialized_payload


class GreetingPilotProvider:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.calls.append((messages, tools))
        if len(self.calls) == 1:
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": "greeting",
                        "language": "ar",
                        "confidence": 0.95,
                    }
                )
            )
        return LLMResponse(
            content='{"reply":"وعليكم السلام! كيف نقدر نعاونك؟"}'
        )


@pytest.mark.asyncio
async def test_greeting_uses_model_reply_without_calling_commerce_tools(
    db_session,
    monkeypatch,
):
    monkeypatch.delenv("DZCOMMERCE_REPLY_COMPOSER_ENABLED", raising=False)
    store, customer, conversation = create_conversation(db_session, "Greeting store")
    provider = GreetingPilotProvider()
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()
    engine = ConversationEngine(provider, registry)

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="السلام عليكم",
    )

    assert result["response"] == "وعليكم السلام! كيف نقدر نعاونك؟"
    assert len(provider.calls) == 2
    assert provider.calls[1][1] is None
    registry.aexecute.assert_not_called()


@pytest.mark.asyncio
async def test_rejected_composer_response_uses_template_without_extra_tool_calls(
    db_session,
):
    store, customer, conversation = create_conversation(db_session, "Fallback store")
    db_session.add(
        Product(
            store_id=store.id,
            name="Widget A",
            base_price=Decimal("1250"),
            is_active=True,
        )
    )
    db_session.commit()
    provider = SearchPilotProvider(
        '{"reply":"Widget A is guaranteed and costs 9,999 DZD."}'
    )
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    registry.aexecute = AsyncMock(wraps=registry.aexecute)
    engine = ConversationEngine(provider, registry)
    engine.reply_composer_enabled = True

    result = await engine.process_message(
        db=db_session,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="Do you have Widget?",
    )

    assert result["response"] == (
        "I found: Widget A. Price: 1,250 DZD. "
        "Would you like its details or choose an option to order?"
    )
    assert len(provider.calls) == 2
    assert registry.aexecute.await_count == 1


def test_composer_feature_flag_can_be_enabled_or_disabled(monkeypatch):
    provider = FixedProvider(content="{}")
    registry = ToolRegistry()

    monkeypatch.setenv("DZCOMMERCE_REPLY_COMPOSER_ENABLED", "true")
    assert ConversationEngine(provider, registry).reply_composer_enabled is True

    monkeypatch.setenv("DZCOMMERCE_REPLY_COMPOSER_ENABLED", "off")
    assert ConversationEngine(provider, registry).reply_composer_enabled is False
