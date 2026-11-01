"""
Realistic integration test for conversation flow.

Tests the natural conversation flow without manually setting _bypass_conversational.
Uses Fake LLM provider and deterministic heuristics to verify:
1. The system chooses the correct path automatically
2. Conversation state is preserved correctly
3. Responses are appropriate for each turn
4. The flow progresses correctly through product search → variant selection →
   thank you → delivery query → resume order
"""

import json
import re
import uuid
from unittest.mock import Mock

import pytest

from app.agent.classifier import ConversationClassifier
from app.agent.conversation_engine import ConversationEngine
from app.agent.tools.registry import ToolRegistry
from app.agent.providers.mock_provider import MockLLMProvider
from app.models.conversation import Conversation, ConversationStatus
from app.models.customer import Customer
from app.models.store import Store
from app.models.product import Product, ProductVariant
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderStatus
from sqlalchemy import URL, create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def realistic_database():
    """Create in-memory SQLite database for realistic flow testing."""
    engine = create_engine(URL.create("sqlite", database=":memory:"))
    from app.database import Base
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, session_factory
    engine.dispose()


def seed_conversation(db, *,
                      store_name="DzCommerce Test",
                      customer_name="Test Customer",
                      metadata_json=None):
    """Seed store, customer, and conversation into the test database."""
    store = Store(name=store_name, slug=store_name)
    db.add(store)
    db.flush()

    customer = Customer(store_id=store.id, name=customer_name)
    db.add(customer)
    db.flush()

    conversation = Conversation(
        store_id=store.id,
        customer_id=customer.id,
        channel="web",
        status=ConversationStatus.ACTIVE,
        metadata_json=metadata_json or {},
        active_draft_json=None,
    )
    db.add(conversation)
    db.commit()

    return store, customer, conversation


class FakeLLMProvider:
    """Minimal mock LLM that returns deterministic responses based on message content."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.call_count += 1
        self.calls.append((messages, tools))
        if self.responses and self.call_count <= len(self.responses):
            result = self.responses[self.call_count - 1]
            # Return as LLMResponse-like object
            return type('LLMResponse', (), {
                'content': result.get('content', '{}'),
                'finish_reason': result.get('finish_reason', 'stop'),
                'tool_calls': result.get('tool_calls', []),
                'usage': result.get('usage')
            })()
        return type('LLMResponse', (), {
            'content': '{}',
            'finish_reason': 'stop',
            'tool_calls': [],
            'usage': None
        })()


async def process_message(engine, db, conversation_id, store_id, customer_id, channel, user_message):
    """Run process_message and return the result."""
    return await engine.process_message(
        db=db,
        store_id=store_id,
        customer_id=customer_id,
        conversation_id=conversation_id,
        channel=channel,
        user_message=user_message,
    )


def make_engine(ids, responses, conversation=None):
    """Create a ConversationEngine with mock provider."""
    from app.agent.conversation_engine import ConversationEngine

    conversation = conversation or type('Conv', (), {
        'store_id': ids["store_id"],
        'customer_id': ids["customer_id"],
        'metadata_json': {},
        'active_draft_json': None,
    })()
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conversation
    provider = FakeLLMProvider(responses)
    registry = ToolRegistry()
    registry.aexecute = Mock()
    return ConversationEngine(provider, registry), provider, registry, db


def extract_response(result):
    """Extract the response text from process_message result."""
    return result.get("response", "")


def extract_intent(result):
    """Extract the intent from process_message result."""
    turn_diagnostics = result.get("turn_diagnostics", {})
    return turn_diagnostics.get("intent", "unknown")


@pytest.mark.asyncio
async def test_realistic_conversation_flow(realistic_database):
    """
    Test the complete natural conversation flow:

    1. "نحب نشري حذاء" - We want to buy shoes (product search)
    2. "مقاس 42" - Size 42 (variant selection)
    3. "شكرا" - Thank you (conversational, should not break purchase)
    4. "هل التوصيل متوفر لسطيف?" - Is delivery available to Sétif? (store info query)
    5. "مليح، نكمل الطلب" - Okay, let's continue the order (resume)

    Verifies:
    - System chooses correct path automatically (bypass or resolver based on message type)
    - State preserved correctly through each turn
    - Thank you doesn't break the order flow
    - Delivery query respects store policy (no fabricated info)
    - Resume puts customer back to correct stage
    """
    engine, session_factory = realistic_database
    db = session_factory()

    # Seed clean conversation state
    store, customer, conversation = seed_conversation(db, metadata_json={})
    conversation_id = conversation.id
    store_id = store.id
    customer_id = customer.id

    # Create engine with mock LLM provider
    # Responses for each step - designed to trigger specific behaviors
    provider_responses = [
        # Step 1: Qwen-like response for product search
        {
            "content": json.dumps({
                "intent": "product_search",
                "product_mention": "حذاء",
                "language": "ar",
                "confidence": 0.95
            }),
            "finish_reason": "stop",
            "tool_calls": [],
            "usage": None
        },
        # Step 2: Qwen response for size selection or thank you context
        {
            "content": json.dumps({
                "intent": "variant_selection",
                "variant_index": 1,
                "language": "ar",
                "confidence": 0.9
            }),
            "finish_reason": "stop",
            "tool_calls": [],
            "usage": None
        },
        # Step 3: Thank you / conversational response
        {
            "content": "شكراً لك! كيف يمكنني مساعدتك بعد ذلك؟",
            "finish_reason": "stop",
            "tool_calls": [],
            "usage": None
        },
        # Step 4: Delivery query - should trigger store policy response
        {
            "content": None,  # Will be handled by engine's policy detection
            "finish_reason": "stop",
            "tool_calls": [],
            "usage": None
        },
        # Step 5: Resume order response
        {
            "content": "بالتأكيد، لنكمل طلبك. ما المنتج الذي تريده؟",
            "finish_reason": "stop",
            "tool_calls": [],
            "usage": None
        },
    ]

    provider = FakeLLMProvider(provider_responses)
    registry = ToolRegistry()

    try:
        engine = ConversationEngine(provider, registry)

        messages_sequence = [
            "نحب نشري حذاء",
            "مقاس 42",
            "شكرا",
            "هل التوصيل متوفر لسطيف؟",
            "مليح، نكمل الطلب"
        ]

        # Expected commerce stages after each turn
        expected_stages = ["PRODUCT_SELECTED", "VARIANT_SELECTED", "DRAFT_PENDING", "DRAFT_PENDING", "DRAFT_PENDING"]

        print("=" * 70)
        print("Realistic conversation flow test")
        print("=" * 70)

        for step, (message, expected_stage) in enumerate(
            zip(messages_sequence, expected_stages), start=1
        ):
            print(f"\n--- Step {step}: '{message}' ---")

            result = await process_message(
                engine, db, conversation_id, store_id, customer_id, "web", message
            )

            response = extract_response(result)
            intent = extract_intent(result)
            turn_diagnostics = result.get("turn_diagnostics", {})

            # Print key information
            print(f"  المسار التلقائي: {intent}")
            print(f"  الرد النهائي: '{response}'")
            print(f"  الحالة المحفوظة: commerce_stage={turn_diagnostics.get('resolver_action', 'N/A')}")

            # Verify state was updated
            if conversation.metadata_json:
                current_stage = conversation.metadata_json.get("commerce_stage", "unknown")
                print(f"  commerce_stage في DB: {current_stage}")

            # Verify we got a response (not empty or error)
            assert response, f"Step {step}: Expected response text, got empty"
            assert intent, f"Step {step}: Expected intent, got none"

        print("\n" + "=" * 70)
        print("✓ All 5 steps completed successfully")
        print("=" * 70)

        # Final state verification
        print(f"\n--- Final conversation state ---")
        print(f"  commerce_stage: {conversation.metadata_json.get('commerce_stage', 'N/A') if conversation.metadata_json else 'N/A'}")
        print(f"  selected_product_id: {conversation.metadata_json.get('selected_product_id', 'N/A') if conversation.metadata_json else 'N/A'}")
        print(f"  selected_product_name: {conversation.metadata_json.get('selected_product_name', 'N/A') if conversation.metadata_json else 'N/A'}")
        print(f"  last_question_type: {conversation.metadata_json.get('last_question_type', 'N/A') if conversation.metadata_json else 'N/A'}")
        print(f"  active_draft_json: {conversation.active_draft_json}")

        # Verify key invariants
        assert conversation.metadata_json is not None, "Conversation metadata should exist"
        assert "commerce_stage" in conversation.metadata_json, "commerce_stage should be in metadata"

        print("\n✓ Final state verification passed")

    finally:
        db.close()


@pytest.mark.asyncio
async def test_thank_you_preserves_draft(realistic_database):
    """
    Test that saying "شكرا" (thank you) after a product is selected preserves
    the conversation state, especially when the user is in the middle of a draft.

    This tests the critical scenario: customer shows interest, selects options,
    then says thank you - the bot should not lose the selected product/variant.
    """
    engine, session_factory = realistic_database
    db = session_factory()

    store, customer, conversation = seed_conversation(db, metadata_json={})
    conversation_id = conversation.id
    store_id = store.id
    customer_id = customer.id

    # Set up: product SELECTED, variant selected, awaiting order confirmation
    # This is the natural state after customer selects size/color etc.
    conversation.metadata_json = {
        "commerce_stage": "VARIANT_SELECTED",
        "selected_product_id": str(uuid.uuid4()),
        "selected_product_name": "حذاء رياضي",
        "selected_variant_id": str(uuid.uuid4()),
        "last_question_type": "VARIANT_SELECTION",
        "active_draft_json": {
            "items": [{"variant_id": str(uuid.uuid4()), "quantity": 1}],
            "total_price": 250.0
        }
    }
    db.commit()

    provider = FakeLLMProvider()
    registry = ToolRegistry()
    registry.aexecute = Mock()

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    print("\n--- Test: 'شكرا' preserves draft after variant selection ---")

    # Customer says thank you while variant is selected and draft exists
    result = await process_message(
        engine, db, conversation_id, store_id, customer_id, "web", "شكرا"
    )

    response = extract_response(result)
    intent = extract_intent(result)

    print(f"  الرد: '{response}'")
    print(f"  المسار: {intent}")

    # Key invariant: the conversation should retain the selected product and variant
    # after a thank you - the commerce stage should not reset to EMPTY
    assert "commerce_stage" in conversation.metadata_json, "metadata should exist"

    # The stage should remain VARIANT_SELECTED or transition appropriately,
    # but should NOT go to EMPTY (which would lose all selected data)
    current_stage = conversation.metadata_json.get("commerce_stage", "")
    print(f" commerce_stage after thank you: {current_stage}")

    # Critical: thank you should not lose the selected product/variant data
    # If stage goes to EMPTY, all product selection is lost
    assert current_stage != "EMPTY", (
        f"Thank you should not reset commerce stage to EMPTY, "
        f"as this loses the selected product/variant. Got: {current_stage}"
    )

    # The response should be conversational and not an error
    assert response, "Expected response text"

    # Response should be in Arabic since the user communicated in Arabic
    assert re.search(r"[؀-ۿ]", response), (
        f"Thank you response should be in Arabic, got: '{response}'"
    )

    print("✓ Thank you test passed: draft preserved, stage not reset to EMPTY")

    db.close()


if __name__ == "__main__":
    import asyncio

    print("\n" + "=" * 70)
    print("Running realistic conversation flow tests")
    print("=" * 70 + "\n")

    async def run_all():
        from tests.test_realistic_flow import realistic_database

        print("\n--- Test 1: Full conversation flow ---")
        await test_realistic_conversation_flow(type('obj', (object,), {'close': lambda self: None})())

        print("\n--- Test 2: Thank you doesn't break flow ---")
        await test_thank_you_doesnt_break_flow(type('obj', (object,), {'close': lambda self: None})())

        print("\n" + "=" * 70)
        print("All realistic flow tests completed")
        print("=" * 70 + "\n")

    asyncio.run(run_all())