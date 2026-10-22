import json
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import URL, create_engine, event
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.agent.conversation_engine import ConversationEngine
from app.agent.commerce_resolver import ResolutionResult
from app.agent.providers.base import LLMResponse
from app.agent.tools.base import BaseTool, ToolResult
from app.agent.tools.confirm_order import ConfirmOrderTool
from app.agent.tools.create_order_draft import CreateOrderDraftTool
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.search_products import SearchProductsTool
from app.database import Base
from app.models.conversation import Conversation, ConversationStatus, Message, MessageRole
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store
from app.services.exceptions import NotFoundError, ValidationError
from app.agent.tools import create_order_draft as create_order_draft_module


@pytest.fixture
def integrity_database(tmp_path):
    engine = create_engine(
        URL.create("sqlite", database=str(tmp_path / "session-integrity.sqlite"))
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield engine, session_factory
    finally:
        engine.dispose()


def seed_conversation(db, *, draft=None):
    store = Store(name="Session Integrity", slug=f"session-integrity-{uuid.uuid4()}")
    db.add(store)
    db.flush()
    customer = Customer(store_id=store.id, name="Session Integrity Customer")
    db.add(customer)
    db.flush()
    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="test",
        status=ConversationStatus.ACTIVE,
        metadata_json={},
        active_draft_json=draft,
    )
    db.add(conversation)
    db.commit()
    return store, customer, conversation


class ProductSearchNlu:
    async def chat(self, messages, tools=None, system_prompt=None):
        return LLMResponse(
            content=json.dumps(
                {
                    "intent": "product_search",
                    "product_mention": "Phone",
                    "language": "en",
                    "confidence": 0.95,
                }
            )
        )


class ScriptedNlu:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def chat(self, messages, tools=None, system_prompt=None):
        return LLMResponse(content=json.dumps(next(self.responses)))


class MetadataWritingSearchTool(BaseTool):
    @property
    def name(self):
        return "search_products"

    @property
    def description(self):
        return "Test tool that writes conversation state."

    @property
    def input_schema(self):
        return {}

    async def execute(self, store_id, arguments, context=None):
        conversation = (
            context["db"]
            .query(Conversation)
            .filter(
                Conversation.id == context["conversation_id"],
                Conversation.store_id == store_id,
            )
            .one()
        )
        metadata = dict(conversation.metadata_json or {})
        metadata["tool_write"] = "committed"
        conversation.metadata_json = metadata
        context["db"].flush()
        return ToolResult(
            success=True,
            data={"products": [{"name": "Phone"}], "count": 1},
        )


class DraftErrorProvider:
    def __init__(self):
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.calls.append(messages)
        if len(self.calls) == 1:
            return LLMResponse(
                content=json.dumps(
                    {
                        "intent": "order_create",
                        "quantity": 1,
                        "language": "ar",
                        "confidence": 0.95,
                    }
                )
            )
        return LLMResponse(content="اختر رقماً صحيحاً من الخيارات المعروضة للمتابعة.")


def install_draft_error_engine(monkeypatch, provider, db_session):
    registry = ToolRegistry()
    registry.register(CreateOrderDraftTool())
    engine = ConversationEngine(provider, registry)
    monkeypatch.setattr(
        "app.agent.conversation_engine.CommerceResolver.resolve",
        lambda *_args, **_kwargs: ResolutionResult(
            allowed_action="EXECUTE_TOOL:create_order_draft",
            resolved_entities={"variant_id": str(uuid.uuid4()), "quantity": 1},
        ),
    )
    monkeypatch.setattr(
        engine,
        "_prepare_safe_tool_args",
        lambda *_args, **_kwargs: {
            "items": [{"variant_index": 9, "quantity": 1}]
        },
    )
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("business_error", "expected_text"),
    [
        (
            ValidationError("Variant index 9 not found. Valid indices are: ['1']."),
            "الخيار المطلوب غير موجود",
        ),
        (
            ValidationError("Insufficient stock for Phone. Available: 0"),
            "الكمية المطلوبة غير متوفرة",
        ),
        (NotFoundError("Conversation not found"), "لم يتم العثور على المحادثة"),
    ],
)
async def test_expected_draft_error_is_preserved_and_given_to_model(
    integrity_database,
    monkeypatch,
    business_error,
    expected_text,
):
    _, session_factory = integrity_database
    db = session_factory()
    store, customer, conversation = seed_conversation(db)
    conversation.metadata_json = {"prior_valid_state": "preserve"}
    db.commit()
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="حضّرلي الطلب",
            external_message_id=f"draft-business-error-{uuid.uuid4()}",
        )
    )
    provider = DraftErrorProvider()
    engine = install_draft_error_engine(monkeypatch, provider, db)

    def raise_expected_error(**_kwargs):
        raise business_error

    monkeypatch.setattr(
        create_order_draft_module,
        "save_draft_safe",
        raise_expected_error,
    )
    result = await engine.process_message(
        db=db,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="حضّرلي الطلب",
    )

    assert result.get("processing_failed") is not True
    assert "اختر رقماً صحيحاً" in result["response"]
    error_context = provider.calls[1][-1].content
    assert "Verified backend validation result:" in error_context
    assert expected_text in error_context
    with session_factory() as reader:
        persisted_conversation = reader.get(Conversation, conversation.id)
        assert persisted_conversation.metadata_json["prior_valid_state"] == "preserve"
        messages = (
            reader.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .all()
        )
        assert {message.role for message in messages} == {
            MessageRole.CUSTOMER,
            MessageRole.AGENT,
        }
    db.close()


@pytest.mark.asyncio
async def test_unexpected_draft_error_rolls_back_and_returns_safe_fallback(
    integrity_database, monkeypatch
):
    _, session_factory = integrity_database
    db = session_factory()
    store, customer, conversation = seed_conversation(db)
    conversation.metadata_json = {"prior_valid_state": "preserve"}
    db.commit()
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="حضّرلي الطلب",
            external_message_id="draft-unexpected-error",
        )
    )
    provider = DraftErrorProvider()
    engine = install_draft_error_engine(monkeypatch, provider, db)

    def raise_unexpected_error(**_kwargs):
        raise RuntimeError("unexpected database failure")

    monkeypatch.setattr(
        create_order_draft_module,
        "save_draft_safe",
        raise_unexpected_error,
    )
    rollbacks = []
    event.listen(db, "after_rollback", lambda *_: rollbacks.append("rollback"))

    result = await engine.process_message(
        db=db,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="حضّرلي الطلب",
    )

    assert result["processing_failed"] is True
    assert result["response"] == (
        "عذراً، لم أتمكن من إكمال طلبك حالياً. يرجى المحاولة مرة أخرى لاحقاً."
    )
    assert rollbacks
    with session_factory() as reader:
        persisted_conversation = reader.get(Conversation, conversation.id)
        assert persisted_conversation.metadata_json["prior_valid_state"] == "preserve"
        assert (
            reader.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .count()
            == 0
        )
    db.close()


@pytest.mark.asyncio
async def test_successful_turn_commits_inbound_tool_and_reply_once(integrity_database):
    _, session_factory = integrity_database
    db = session_factory()
    store, customer, conversation = seed_conversation(db)
    commits = []
    event.listen(db, "before_commit", lambda *_: commits.append("commit"))

    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="Find a phone",
            external_message_id="test-message-success",
        )
    )
    registry = ToolRegistry()
    registry.register(MetadataWritingSearchTool())
    engine = ConversationEngine(ProductSearchNlu(), registry)

    result = await engine.process_message(
        db=db,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="Find a phone",
    )

    assert result.get("processing_failed") is not True
    assert len(commits) == 1

    with session_factory() as reader:
        persisted_conversation = reader.get(Conversation, conversation.id)
        assert persisted_conversation.metadata_json["tool_write"] == "committed"
        messages = (
            reader.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .order_by(Message.role)
            .all()
        )
        assert [(message.role, message.content) for message in messages] == [
            (MessageRole.AGENT, result["response"]),
            (MessageRole.CUSTOMER, "Find a phone"),
        ]
    db.close()


@pytest.mark.asyncio
async def test_variant_correction_then_price_uses_current_variant(integrity_database):
    _, session_factory = integrity_database
    db = session_factory()
    store, customer, conversation = seed_conversation(db)
    product = Product(
        store_id=store.id,
        name="Samsung Galaxy",
        base_price=1000,
        is_active=True,
    )
    db.add(product)
    db.flush()
    black_variant = ProductVariant(
        product_id=product.id,
        name="Black",
        price_adjustment=100,
        attributes_json={"color": "black"},
    )
    blue_variant = ProductVariant(
        product_id=product.id,
        name="Blue",
        price_adjustment=500,
        attributes_json={"color": "blue"},
    )
    db.add_all([black_variant, blue_variant])
    db.flush()
    db.add_all(
        [
            InventoryItem(
                store_id=store.id,
                variant_id=black_variant.id,
                quantity=9,
            ),
            InventoryItem(
                store_id=store.id,
                variant_id=blue_variant.id,
                quantity=3,
            ),
        ]
    )
    db.commit()

    provider = ScriptedNlu(
        [
            {
                "intent": "product_search",
                "product_mention": "Samsung",
                "language": "en",
                "confidence": 0.95,
            },
            {
                "intent": "variant_selection",
                "attributes": {"color": "black"},
                "language": "en",
                "confidence": 0.95,
            },
            {
                "intent": "variant_selection",
                "attributes": {"color": "blue"},
                "language": "en",
                "confidence": 0.95,
            },
            {
                "intent": "product_details",
                "language": "en",
                "confidence": 0.95,
            },
        ]
    )
    registry = ToolRegistry()
    registry.register(SearchProductsTool())
    engine = ConversationEngine(provider, registry)
    engine.reply_composer_enabled = False

    async def send(message):
        return await engine.process_message(
            db=db,
            store_id=store.id,
            customer_id=customer.id,
            conversation_id=conversation.id,
            channel="test",
            user_message=message,
        )

    await send("Samsung?")
    await send("Black")
    await send("No, blue")
    result = await send("How much?")

    assert conversation.metadata_json["selected_variant_id"] == str(blue_variant.id)
    assert "السعر: 1500.0 دج" in result["response"]
    assert "الكمية المتوفرة: 3" in result["response"]
    assert "السعر: 1100.0 دج" not in result["response"]
    db.close()


@pytest.mark.asyncio
async def test_late_failure_rolls_back_tool_and_message_writes(
    integrity_database, monkeypatch
):
    _, session_factory = integrity_database
    db = session_factory()
    store, customer, conversation = seed_conversation(db)
    rollbacks = []
    event.listen(db, "after_rollback", lambda *_: rollbacks.append("rollback"))
    db.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.CUSTOMER,
            content="Find a phone",
            external_message_id="test-message-failure",
        )
    )

    registry = ToolRegistry()
    registry.register(MetadataWritingSearchTool())
    engine = ConversationEngine(ProductSearchNlu(), registry)

    async def fail_after_tool(*_args, **_kwargs):
        raise RuntimeError("late response generation failure")

    monkeypatch.setattr(engine, "_generate_localized_final_text", fail_after_tool)
    result = await engine.process_message(
        db=db,
        store_id=store.id,
        customer_id=customer.id,
        conversation_id=conversation.id,
        channel="test",
        user_message="Find a phone",
    )

    assert result["processing_failed"] is True
    assert rollbacks
    with session_factory() as reader:
        persisted_conversation = reader.get(Conversation, conversation.id)
        assert "tool_write" not in persisted_conversation.metadata_json
        assert (
            reader.query(Message)
            .filter(Message.conversation_id == conversation.id)
            .count()
            == 0
        )
    db.close()


@pytest.mark.asyncio
async def test_repeated_confirmation_deducts_stock_and_creates_order_once(
    integrity_database,
):
    _, session_factory = integrity_database
    db = session_factory()
    store, customer, _ = seed_conversation(db)
    product = Product(
        store_id=store.id,
        name="Confirmable Phone",
        base_price=Decimal("100.00"),
        is_active=True,
    )
    db.add(product)
    db.flush()
    variant = ProductVariant(
        product_id=product.id,
        name="Default",
        price_adjustment=Decimal("0"),
    )
    db.add(variant)
    db.flush()
    inventory = InventoryItem(
        store_id=store.id,
        variant_id=variant.id,
        quantity=8,
    )
    db.add(inventory)
    conversation = db.query(Conversation).filter(
        Conversation.store_id == store.id,
        Conversation.customer_id == customer.id,
    ).one()
    conversation.active_draft_json = {
        "items": [{"variant_id": str(variant.id), "quantity": 2}],
        "total_price": "200.00",
    }
    db.commit()

    commits = []
    event.listen(db, "before_commit", lambda *_: commits.append("commit"))
    tool = ConfirmOrderTool()
    context = {
        "db": db,
        "conversation_id": conversation.id,
        "customer_id": customer.id,
    }
    first = await tool.execute(store.id, {}, context)
    second = await tool.execute(store.id, {}, context)
    db.commit()

    assert first.success
    assert second.success
    assert second.data["already_confirmed"] is True
    assert len(commits) == 1

    with session_factory() as reader:
        orders = (
            reader.query(Order)
            .filter(
                Order.conversation_id == conversation.id,
                Order.status == OrderStatus.CONFIRMED,
            )
            .all()
        )
        assert len(orders) == 1
        assert (
            reader.query(OrderItem)
            .filter(OrderItem.order_id == orders[0].id)
            .count()
            == 1
        )
        persisted_inventory = reader.get(InventoryItem, inventory.id)
        assert persisted_inventory.quantity == 6
        assert reader.get(Conversation, conversation.id).active_draft_json is None
    db.close()
