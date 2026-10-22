"""ConversationEngine tests for the resolver-gated tool execution contract."""
import json
import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from app.agent.providers.base import LLMResponse
from app.agent.tools.base import ToolResult
from app.agent.tools.registry import ToolRegistry


class FakeLLMProvider:
    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.call_count = 0
        self.calls = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.call_count += 1
        self.calls.append((messages, tools))
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="{}", finish_reason="stop")


@pytest.fixture
def ids():
    return {
        "store_id": uuid.uuid4(),
        "customer_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
    }


def make_engine(ids, responses, conversation=None):
    from app.agent.conversation_engine import ConversationEngine

    conversation = conversation or SimpleNamespace(
        store_id=ids["store_id"],
        customer_id=ids["customer_id"],
        metadata_json={},
        active_draft_json=None,
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conversation
    provider = FakeLLMProvider(responses)
    registry = ToolRegistry()
    registry.aexecute = AsyncMock()
    return ConversationEngine(provider, registry), provider, registry, db


async def process(engine, db, ids, message="سلام"):
    return await engine.process_message(
        db=db,
        store_id=ids["store_id"],
        customer_id=ids["customer_id"],
        conversation_id=ids["conversation_id"],
        channel="web",
        user_message=message,
    )


@pytest.mark.asyncio
async def test_normal_response_no_tool(ids):
    engine, provider, registry, db = make_engine(
        ids, [LLMResponse(content='{"intent":"greeting"}')]
    )

    result = await process(engine, db, ids)

    assert result["response"] == "وعليكم السلام! كيف نقدر نعاونك؟"
    assert result["tool_calls"] == []
    assert result["handoff"] is False
    assert provider.call_count == 2
    registry.aexecute.assert_not_called()


@pytest.mark.asyncio
async def test_single_tool_call_round(ids):
    engine, provider, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {
                        "name": "search_products",
                        "arguments": {"query": "iPhone"},
                        "id": "call_001",
                    }
                ],
                finish_reason="tool_calls",
            )
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=True,
            data={"products": [{"name": "iPhone 15", "price": 180000}], "count": 1},
        )
    )

    result = await process(engine, db, ids, "شحال الايفون؟")

    assert result["response"] == (
        "وجدت المنتج: iPhone 15. السعر: 180,000 دج. "
        "هل تريد معرفة تفاصيله أو اختيار خيار لإتمام الشراء؟"
    )
    assert provider.call_count == 2
    response_payload = json.loads(provider.calls[1][0][-1].content)
    assert response_payload["verified_products"] == [
        {"name": "iPhone 15", "price": "180,000"}
    ]
    registry.aexecute.assert_awaited_once()
    call = registry.aexecute.await_args.kwargs
    assert call["tool_name"] == "search_products"
    assert call["arguments"] == {"query": "iPhone"}
    assert call["context"]["store_id"] == ids["store_id"]


@pytest.mark.asyncio
async def test_multiple_tool_calls_one_response(ids):
    engine, provider, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "search_products", "arguments": {"query": "Samsung"}},
                    {"name": "search_products", "arguments": {"query": "iPhone"}},
                ],
                finish_reason="tool_calls",
            )
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(success=True, data={"products": [], "count": 0})
    )

    await process(engine, db, ids, "ابحث عن هواتف")

    registry.aexecute.assert_awaited_once()
    assert registry.aexecute.await_args.kwargs["arguments"] == {"query": "Samsung"}
    assert provider.call_count == 1


@pytest.mark.asyncio
async def test_sequential_tool_rounds(ids):
    engine, provider, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "search_products", "arguments": {"query": "phone"}}
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    {"name": "handoff_to_human", "arguments": {"reason": "complex"}}
                ],
                finish_reason="tool_calls",
            ),
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(success=True, data={"products": [], "count": 0})
    )

    result = await process(engine, db, ids, "عندكم phone؟")

    assert provider.call_count == 1
    registry.aexecute.assert_awaited_once()
    assert result["handoff"] is False


@pytest.mark.asyncio
async def test_tool_failure_controlled_error(ids):
    engine, _, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "search_products", "arguments": {"query": "phone"}}
                ],
                finish_reason="tool_calls",
            )
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(
            success=False,
            error="Internal database connection error at /app/db.py:42",
        )
    )

    result = await process(engine, db, ids, "عندكم phone؟")

    assert result["response"] == (
    "تعذر إكمال البحث مؤقتًا. حاول مرة أخرى."
    )
    assert "database" not in result["response"].lower()
    assert "/app/db.py" not in result["response"]


@pytest.mark.asyncio
async def test_unknown_tool(ids):
    engine, provider, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "nonexistent_tool", "arguments": {}, "id": "call_X"}
                ],
                finish_reason="tool_calls",
            )
        ],
    )

    result = await process(engine, db, ids, "test")

    assert result["response"] == "ما هو المنتج الذي تبحث عنه؟"
    assert provider.call_count == 1
    registry.aexecute.assert_not_called()


@pytest.mark.asyncio
async def test_malformed_arguments(ids):
    engine, _, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {
                        "name": "search_products",
                        "arguments": {"invalid_key": 123},
                        "id": "call_M",
                    }
                ],
                finish_reason="tool_calls",
            )
        ],
    )

    result = await process(engine, db, ids, "search")

    assert result["response"] == "ما هو المنتج الذي تبحث عنه؟"
    registry.aexecute.assert_not_called()


@pytest.mark.asyncio
async def test_max_tool_rounds(ids):
    engine, provider, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "search_products", "arguments": {"query": "phone"}}
                ],
                finish_reason="tool_calls",
            )
            for _ in range(5)
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(success=True, data={"products": [], "count": 0})
    )

    result = await process(engine, db, ids, "عندكم phone؟")

    assert provider.call_count == 1
    registry.aexecute.assert_awaited_once()
    assert result["response"] is not None


@pytest.mark.asyncio
async def test_repeated_identical_call_protection(ids):
    engine, provider, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "search_products", "arguments": {"query": "phone"}}
                ],
                finish_reason="tool_calls",
            )
            for _ in range(2)
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(success=True, data={"products": [], "count": 0})
    )

    await process(engine, db, ids, "عندكم phone؟")

    assert provider.call_count == 1
    registry.aexecute.assert_awaited_once()


@pytest.mark.asyncio
async def test_tenant_isolation(ids):
    other_tenant_conversation = SimpleNamespace(
        store_id=uuid.uuid4(),
        customer_id=ids["customer_id"],
        metadata_json={},
        active_draft_json=None,
    )
    engine, provider, registry, db = make_engine(
        ids,
        [LLMResponse(content='{"intent":"greeting"}')],
        conversation=other_tenant_conversation,
    )

    result = await process(engine, db, ids)

    assert result == {"error": "Conversation not found"}
    assert provider.call_count == 0
    registry.aexecute.assert_not_called()


@pytest.mark.asyncio
async def test_usage_recorded_for_provider_response(ids):
    engine, _, registry, db = make_engine(
        ids,
        [
            LLMResponse(
                tool_calls=[
                    {"name": "search_products", "arguments": {"query": "phone"}}
                ],
                finish_reason="tool_calls",
                usage={
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "latency_ms": 1000,
                    "model": "test-model",
                },
            )
        ],
    )
    registry.aexecute = AsyncMock(
        return_value=ToolResult(success=True, data={"products": [], "count": 0})
    )
    db.begin_nested.return_value = nullcontext()

    with (
        patch(
            "app.agent.conversation_engine.inspect"
        ) as inspect_database,
        patch(
            "app.agent.conversation_engine.usage_service.record_usage"
        ) as record_usage,
    ):
        inspect_database.return_value.has_table.return_value = True
        await process(engine, db, ids, "عندكم phone؟")

    record_usage.assert_called_once()
    assert record_usage.call_args.kwargs["input_tokens"] == 100
    assert record_usage.call_args.kwargs["output_tokens"] == 20
    assert record_usage.call_args.kwargs["commit"] is False


@pytest.mark.asyncio
async def test_mock_provider_still_works(ids):
    from app.agent.providers.mock_provider import MockLLMProvider
    from app.agent.conversation_engine import ConversationEngine

    conversation = SimpleNamespace(
        store_id=ids["store_id"],
        customer_id=ids["customer_id"],
        metadata_json={},
        active_draft_json=None,
    )
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = conversation
    engine = ConversationEngine(MockLLMProvider(), ToolRegistry())

    result = await process(engine, db, ids, "hello")

    assert result["response"]
