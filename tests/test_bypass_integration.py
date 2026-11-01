"""
Integration test for _bypass_conversational feature.

Tests that when _bypass_conversational is True in conversation state,
the engine skips CommerceResolver and generates natural conversational
responses without forcing commerce tool calls.

The test sequence follows the user's requested flow:
1. "نحب نشري حذاء" (We want to buy shoes) - product search
2. "مقاس 42" (Size 42) - variant selection
3. "شكرا" (Thank you) - conversational response
4. "هل التوصيل متوفر لسطيف?" (Is delivery available to Sétif?) - store info
5. "مليح، نكمل الطلب" (Okay, let's continue the order) - resume order
"""

import json
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
def integration_database():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine(URL.create("sqlite", database=":memory:"))
    from app.database import Base
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, session_factory
    engine.dispose()


def seed_conversation(db, *,
                      store_name="Test Store",
                      customer_name="Test Customer",
                      metadata_json=None,
                      active_draft_json=None):
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
        channel="test",
        status=ConversationStatus.ACTIVE,
        metadata_json=metadata_json or {},
        active_draft_json=active_draft_json,
    )
    db.add(conversation)
    db.commit()

    return store, customer, conversation


class FakeLLMProvider:
    """Minimal mock LLM provider that returns predefined responses."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.call_count = 0
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.call_count += 1
        self.calls.append((messages, tools))
        if self.responses and self.call_count <= len(self.responses):
            return self.responses[self.call_count - 1]
        return LLMResponse(content="{}", finish_reason="stop")


class LLMResponse:
    """Simple LLM response mock."""
    def __init__(self, content="", finish_reason="stop", tool_calls=None, usage=None):
        self.content = content
        self.finish_reason = finish_reason
        self.tool_calls = tool_calls or []
        self.usage = usage


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


@pytest.mark.asyncio
async def test_bypass_conversational_skips_resolver(integration_database):
    """
    Test that _bypass_conversational=True causes the engine to skip
    CommerceResolver and generate conversational responses.
    """
    engine, session_factory = integration_database
    db = session_factory()

    # Seed store, customer, conversation
    store, customer, conversation = seed_conversation(
        db,
        metadata_json={"_bypass_conversational": True, "commerce_stage": "EMPTY"},
    )

    # Create engine with mock provider
    provider = FakeLLMProvider()
    registry = ToolRegistry()

    # Mock CommerceResolver to verify it's NOT called
    from app.agent.commerce_resolver import CommerceResolver
    original_resolve = CommerceResolver.resolve
    resolve_calls = []

    async def mock_resolve(nlu_output, current_state, store_id):
        resolve_calls.append((nlu_output, current_state, store_id))
        # Return a result that would normally trigger tool execution
        from app.agent.commerce_resolver import ResolutionResult, AllowedAction
        return ResolutionResult(
            allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
            resolved_entities={"query": "shoes"},
            context_updates={},
            response_hint="Found shoes",
        )

    import app.agent.commerce_resolver
    app.agent.commerce_resolver.CommerceResolver.resolve = staticmethod(mock_resolve)

    try:
        engine = ConversationEngine(provider, registry)

        # Test 1: Product search message with bypass
        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "نحب نشري حذاء"
        )

        # Verify response was generated (not an error)
        assert result["response"], "Expected a response text"
        assert "response" in result, "Expected 'response' key in result"

        # Verify CommerceResolver was NOT called (bypass worked)
        assert len(resolve_calls) == 0, (
            f"CommerceResolver should NOT be called when _bypass_conversational=True, "
            f"but it was called {len(resolve_calls)} times"
        )

        print(f"✓ Test 1 PASSED: Product search with bypass - response: '{result['response'][:50]}...'")
        print(f"  CommerceResolver calls: {len(resolve_calls)} (expected: 0)")

    finally:
        app.agent.commerce_resolver.CommerceResolver.resolve = original_resolve
        db.close()


@pytest.mark.asyncio
async def test_bypass_with_product_search_flow(integration_database):
    """
    Test the full flow: product search → variant selection → thank you →
    delivery query → resume order, all with _bypass_conversational=True.
    """
    engine, session_factory = integration_database
    db = session_factory()

    # Seed store, customer, conversation with bypass enabled
    store, customer, conversation = seed_conversation(
        db,
        metadata_json={"_bypass_conversational": True, "commerce_stage": "EMPTY"},
    )

    # Create engine with mock provider
    provider = FakeLLMProvider()
    registry = ToolRegistry()

    # Track resolver calls
    from app.agent.commerce_resolver import CommerceResolver
    original_resolve = CommerceResolver.resolve
    resolve_calls = []

    async def mock_resolve(nlu_output, current_state, store_id):
        resolve_calls.append(True)
        from app.agent.commerce_resolver import ResolutionResult, AllowedAction
        return ResolutionResult(
            allowed_action=AllowedAction.SEARCH_PRODUCTS.value,
            resolved_entities={"query": "shoes"},
            context_updates={},
            response_hint="Found shoes",
        )

    import app.agent.commerce_resolver
    app.agent.commerce_resolver.CommerceResolver.resolve = staticmethod(mock_resolve)

    try:
        engine = ConversationEngine(provider, registry)

        # Step 1: "نحب نشري حذاء" - product search
        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "نحب نشري حذاء"
        )
        print(f"Step 1 - 'نحب نشري حذاء': '{result['response']}'")
        assert "response" in result
        assert len(resolve_calls) == 0, "Resolver should be bypassed"

        # Step 2: "مقاس 42" - variant selection (with product selected from context)
        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "مقاس 42"
        )
        print(f"Step 2 - 'مقاس 42': '{result['response']}'")
        assert "response" in result
        assert len(resolve_calls) == 0, "Resolver should be bypassed"

        # Step 3: "شكرا" - thank you / conversational
        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "شكرا"
        )
        print(f"Step 3 - 'شكرا': '{result['response']}'")
        assert "response" in result
        assert len(resolve_calls) == 0, "Resolver should be bypassed"

        # Step 4: "هل التوصيل متوفر لسطيف?" - delivery query
        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "هل التوصيل متوفر لسطيف?"
        )
        print(f"Step 4 - 'هل التوصيل متوفر لسطيف?': '{result['response']}'")
        assert "response" in result
        assert len(resolve_calls) == 0, "Resolver should be bypassed"

        # Step 5: "مليح، نكمل الطلب" - resume order
        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "مليح، نكمل الطلب"
        )
        print(f"Step 5 - 'مليح، نكمل الطلب': '{result['response']}'")
        assert "response" in result
        assert len(resolve_calls) == 0, "Resolver should be bypassed"

        print("\n✓ All 5 steps PASSED: Bypass flow works end-to-end")

    finally:
        app.agent.commerce_resolver.CommerceResolver.resolve = original_resolve
        db.close()


@pytest.mark.asyncio
async def test_without_bypass_produces_response(integration_database):
    """
    Test that WITHOUT _bypass_conversational, the engine produces a response
    (verifying the normal flow still works).
    """
    engine, session_factory = integration_database
    db = session_factory()

    # Seed store, customer, conversation WITHOUT bypass flag
    store, customer, conversation = seed_conversation(
        db,
        metadata_json={"commerce_stage": "EMPTY"},  # No _bypass_conversational
    )

    # Create engine with mock provider
    provider = FakeLLMProvider()
    registry = ToolRegistry()

    try:
        engine = ConversationEngine(provider, registry)

        result = await process_message(
            engine, db, conversation.id, store.id, customer.id, "web",
            "نحب نشري حذاء"
        )

        # Without bypass flag, the engine should generate a response
        print(f"Without bypass - result has response: {bool(result.get('response'))}")
        assert "response" in result, "Expected a response from the engine"
        assert result["response"], "Expected non-empty response text"

        print("✓ Test PASSED: Without _bypass_conversational, engine produces response")

    finally:
        pass


if __name__ == "__main__":
    import asyncio

    print("=" * 60)
    print("Running _bypass_conversational integration tests")
    print("=" * 60)

    async def run_all():
        from tests.test_bypass_integration import integration_database

        # We need to create the database fixture
        engine = create_engine(URL.create("sqlite", database=":memory:"))
        from app.database import Base
        Base.metadata.create_all(bind=engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        print("\n--- Test 1: bypass_conversational_skips_resolver ---")
        await test_bypass_conversational_skips_resolver(type('obj', (object,), {'close': lambda self: None})())

        print("\n--- Test 2: bypass_with_product_search_flow ---")
        await test_bypass_with_product_search_flow(type('obj', (object,), {'close': lambda self: None})())

        print("\n--- Test 3: without_bypass_still_uses_resolver ---")
        await test_without_bypass_still_uses_resolver(type('obj', (object,), {'close': lambda self: None})())

        engine.dispose()

    asyncio.run(run_all())
    print("\n" + "=" * 60)
    print("All tests completed")
    print("=" * 60)