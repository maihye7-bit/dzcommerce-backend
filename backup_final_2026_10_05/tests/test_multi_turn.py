"""
Tests for Multi-Turn Tool Loop in ConversationEngine.
Uses mock/fake providers - does NOT require real Qwen API key.
"""
import uuid
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.providers.base import LLMMessage, LLMResponse
from app.agent.tools.registry import ToolRegistry
from app.agent.tools.base import BaseTool, ToolResult


# ============================================================
# FAKE PROVIDERS FOR TESTING
# ============================================================

class FakeLLMProvider:
    """Fake provider that returns pre-configured responses in sequence."""

    def __init__(self, responses: list[LLMResponse]):
        self.responses = list(responses)
        self.call_count = 0
        self.received_messages: list[list[LLMMessage]] = []

    async def chat(self, messages, tools=None, system_prompt=None):
        self.received_messages.append(list(messages))
        self.call_count += 1
        if self.responses:
            return self.responses.pop(0)
        return LLMResponse(content="Default response", finish_reason="stop")


class FakeSearchTool(BaseTool):
    name = "search_products"
    description = "Search for products"
    input_schema = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    async def execute(self, store_id, arguments, context):
        return ToolResult(
            success=True,
            data={"products": [{"name": "iPhone 15", "price": 180000}]},
        )


class FakeFailingTool(BaseTool):
    name = "failing_tool"
    description = "A tool that always fails"
    input_schema = {"type": "object", "properties": {}}

    async def execute(self, store_id, arguments, context):
        raise ValueError("Internal database connection error at /app/db.py:42")


class FakeHandoffTool(BaseTool):
    name = "handoff_to_human"
    description = "Transfer to human agent"
    input_schema = {
        "type": "object",
        "properties": {"reason": {"type": "string"}, "summary": {"type": "string"}},
        "required": ["reason", "summary"],
    }

    async def execute(self, store_id, arguments, context):
        return ToolResult(success=True, data={"handoff_id": str(uuid.uuid4())})


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(FakeSearchTool())
    reg.register(FakeFailingTool())
    reg.register(FakeHandoffTool())
    return reg


@pytest.fixture
def mock_db():
    db = MagicMock()
    # Mock conversation query
    mock_query = MagicMock()
    mock_query.filter.return_value.first.return_value = MagicMock()  # Conversation exists
    db.query.return_value = mock_query
    return db


@pytest.fixture
def store_id():
    return uuid.uuid4()


@pytest.fixture
def customer_id():
    return uuid.uuid4()


@pytest.fixture
def conversation_id():
    return uuid.uuid4()


# ============================================================
# TEST 1: Normal response without tool
# ============================================================

@pytest.mark.asyncio
async def test_normal_response_no_tool(registry, mock_db, store_id, customer_id, conversation_id):
    """Test that a simple response without tool calls works."""
    provider = FakeLLMProvider([
        LLMResponse(content="مرحباً! كيف يمكنني مساعدتك؟", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="system", content="System prompt"),
            LLMMessage(role="user", content="سلام"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="سلام",
        )

    assert result["response"] == "مرحباً! كيف يمكنني مساعدتك؟"
    assert result["tool_calls"] == []
    assert result["handoff"] is False
    assert provider.call_count == 1


# ============================================================
# TEST 2: One tool call → tool result → final response
# ============================================================

@pytest.mark.asyncio
async def test_single_tool_call_round(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Qwen calls tool → tool executes → result sent back → final answer."""
    provider = FakeLLMProvider([
        # First response: Qwen requests tool
        LLMResponse(
            content=None,
            tool_calls=[{"name": "search_products", "arguments": {"query": "iPhone"}, "id": "call_001"}],
            finish_reason="tool_calls",
        ),
        # Second response: Qwen gives final answer
        LLMResponse(content="عندنا iPhone 15 بسعر 180,000 دج", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="شحال الايفون؟"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="شحال الايفون؟",
        )

    assert result["response"] == "عندنا iPhone 15 بسعر 180,000 دج"
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "search_products"
    assert provider.call_count == 2

    # Verify tool result was sent back to Qwen
    second_call_messages = provider.received_messages[1]
    tool_messages = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_001"
    assert "iPhone 15" in tool_messages[0].content


# ============================================================
# TEST 3: Multiple tool calls in one response
# ============================================================

@pytest.mark.asyncio
async def test_multiple_tool_calls_one_response(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Qwen returns multiple tool calls in one response."""
    provider = FakeLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[
                {"name": "search_products", "arguments": {"query": "Samsung"}, "id": "call_A"},
                {"name": "search_products", "arguments": {"query": "iPhone"}, "id": "call_B"},
            ],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="عندنا سامسونج وايفون", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="واش عندكم تليفونات؟"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="واش عندكم تليفونات؟",
        )

    assert result["response"] == "عندنا سامسونج وايفون"
    assert len(result["tool_calls"]) == 2
    assert provider.call_count == 2

    # Verify both tool results were sent
    second_call_messages = provider.received_messages[1]
    tool_messages = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_messages) == 2
    assert tool_messages[0].tool_call_id == "call_A"
    assert tool_messages[1].tool_call_id == "call_B"


# ============================================================
# TEST 4: Sequential tool rounds
# ============================================================

@pytest.mark.asyncio
async def test_sequential_tool_rounds(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Multiple sequential rounds of tool calling."""
    provider = FakeLLMProvider([
        # Round 1: search
        LLMResponse(
            content=None,
            tool_calls=[{"name": "search_products", "arguments": {"query": "phone"}, "id": "call_R1"}],
            finish_reason="tool_calls",
        ),
        # Round 2: handoff
        LLMResponse(
            content=None,
            tool_calls=[{"name": "handoff_to_human", "arguments": {"reason": "complex", "summary": "test"}, "id": "call_R2"}],
            finish_reason="tool_calls",
        ),
        # Final response
        LLMResponse(content="تم تحويلك إلى موظف", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="نحب نهضر مع موظف"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="نحب نهضر مع موظف",
        )

    assert result["response"] == "تم تحويلك إلى موظف"
    assert result["handoff"] is True
    assert len(result["tool_calls"]) == 2
    assert provider.call_count == 3


# ============================================================
# TEST 5: Tool execution failure → controlled error → final response
# ============================================================

@pytest.mark.asyncio
async def test_tool_failure_controlled_error(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Tool fails → safe error sent to Qwen → Qwen generates customer response."""
    provider = FakeLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[{"name": "failing_tool", "arguments": {}, "id": "call_FAIL"}],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="عذراً، لم أتمكن من تنفيذ الطلب", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="do something"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="do something",
        )

    assert result["response"] == "عذراً، لم أتمكن من تنفيذ الطلب"
    assert provider.call_count == 2

    # Verify the error message sent to Qwen does NOT contain internal details
    second_call_messages = provider.received_messages[1]
    tool_messages = [m for m in second_call_messages if m.role == "tool"]
    assert len(tool_messages) == 1
    tool_content = tool_messages[0].content
    assert "database" not in tool_content.lower()
    assert "/app/db.py" not in tool_content
    assert "ValueError" not in tool_content


# ============================================================
# TEST 6: Unknown tool
# ============================================================

@pytest.mark.asyncio
async def test_unknown_tool(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Qwen requests a tool that doesn't exist."""
    provider = FakeLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[{"name": "nonexistent_tool", "arguments": {}, "id": "call_X"}],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="عذراً، لا يمكنني تنفيذ هذا الطلب", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="test"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="test",
        )

    # Should not crash, should get a response
    assert result["response"] == "عذراً، لا يمكنني تنفيذ هذا الطلب"
    assert provider.call_count == 2


# ============================================================
# TEST 7: Malformed arguments
# ============================================================

@pytest.mark.asyncio
async def test_malformed_arguments(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Tool called with invalid arguments doesn't crash."""
    provider = FakeLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[{"name": "search_products", "arguments": {"invalid_key": 123}, "id": "call_M"}],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="لم أتمكن من البحث", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="search"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="search",
        )

    # Should not crash
    assert result["response"] is not None


# ============================================================
# TEST 8: Maximum 3 tool rounds
# ============================================================

@pytest.mark.asyncio
async def test_max_tool_rounds(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Loop stops after MAX_TOOL_ROUNDS."""
    # Create responses that always request tools (infinite loop scenario)
    responses = []
    for i in range(5):  # More than MAX_TOOL_ROUNDS
        responses.append(LLMResponse(
            content=None,
            tool_calls=[{"name": "search_products", "arguments": {"query": f"q{i}"}, "id": f"call_{i}"}],
            finish_reason="tool_calls",
        ))
    responses.append(LLMResponse(content="Should not reach here", finish_reason="stop"))

    provider = FakeLLMProvider(responses)

    from app.agent.conversation_engine import ConversationEngine, MAX_TOOL_ROUNDS
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="loop test"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="loop test",
        )

    # Should stop after MAX_TOOL_ROUNDS (3) + initial call = 4 calls max
    assert provider.call_count <= MAX_TOOL_ROUNDS + 1
    # Should have a safe response
    assert result["response"] is not None
    assert len(result["response"]) > 0


# ============================================================
# TEST 9: Repeated identical tool call protection
# ============================================================

@pytest.mark.asyncio
async def test_repeated_identical_call_protection(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Same tool with same args called repeatedly is detected and stopped."""
    same_call = {"name": "search_products", "arguments": {"query": "iPhone"}, "id": "call_SAME"}
    provider = FakeLLMProvider([
        LLMResponse(content=None, tool_calls=[same_call], finish_reason="tool_calls"),
        LLMResponse(content=None, tool_calls=[same_call], finish_reason="tool_calls"),
        LLMResponse(content="Should not reach here", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="test repeat"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="test repeat",
        )

    # Should stop after detecting repetition (2 calls: initial + first tool round)
    assert provider.call_count <= 2
    assert result["response"] is not None


# ============================================================
# TEST 10: Tenant isolation preserved
# ============================================================

@pytest.mark.asyncio
async def test_tenant_isolation(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: store_id is passed through to tool execution."""
    provider = FakeLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[{"name": "search_products", "arguments": {"query": "test"}, "id": "call_T"}],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="done", finish_reason="stop"),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="test"),
        ])

        with patch.object(registry, "aexecute", new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = ToolResult(success=True, data={"result": "ok"})

            await engine.process_message(
                db=mock_db, store_id=store_id, customer_id=customer_id,
                conversation_id=conversation_id, channel="web", user_message="test",
            )

            # Verify store_id was passed to tool execution
            mock_execute.assert_called_once()
            call_kwargs = mock_execute.call_args
            context = call_kwargs[1]["context"] if "context" in call_kwargs[1] else call_kwargs[0][2]
            assert context["store_id"] == store_id


# ============================================================
# TEST 11: Usage recorded for multiple Qwen calls
# ============================================================

@pytest.mark.asyncio
async def test_usage_recorded_multiple_calls(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: Usage is recorded for each Qwen API call."""
    provider = FakeLLMProvider([
        LLMResponse(
            content=None,
            tool_calls=[{"name": "search_products", "arguments": {"query": "test"}, "id": "call_U1"}],
            finish_reason="tool_calls",
            usage={"input_tokens": 100, "output_tokens": 20, "latency_ms": 1000, "model": "test-model"},
        ),
        LLMResponse(
            content="Final answer",
            finish_reason="stop",
            usage={"input_tokens": 150, "output_tokens": 30, "latency_ms": 800, "model": "test-model"},
        ),
    ])

    from app.agent.conversation_engine import ConversationEngine
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="test"),
        ])

        with patch("app.agent.conversation_engine.usage_service.record_usage") as mock_record:
            result = await engine.process_message(
                db=mock_db, store_id=store_id, customer_id=customer_id,
                conversation_id=conversation_id, channel="web", user_message="test",
            )

            # Usage should be recorded twice (once per Qwen call)
            assert mock_record.call_count == 2


# ============================================================
# TEST 12: MockLLMProvider still works
# ============================================================

@pytest.mark.asyncio
async def test_mock_provider_still_works(registry, mock_db, store_id, customer_id, conversation_id):
    """Test: MockLLMProvider continues to work with the new engine."""
    from app.agent.providers.mock_provider import MockLLMProvider
    from app.agent.conversation_engine import ConversationEngine

    provider = MockLLMProvider()
    engine = ConversationEngine(provider, registry)

    with patch("app.agent.conversation_engine.ConversationContextBuilder") as mock_builder:
        mock_builder.return_value.build = AsyncMock(return_value=[
            LLMMessage(role="user", content="hello"),
        ])

        result = await engine.process_message(
            db=mock_db, store_id=store_id, customer_id=customer_id,
            conversation_id=conversation_id, channel="web", user_message="hello",
        )

    assert result["response"] is not None
    assert len(result["response"]) > 0
