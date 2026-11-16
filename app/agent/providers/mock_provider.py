from app.agent.providers.base import (LLMMessage, LLMProvider, LLMResponse,
                                      ToolDefinition)


class MockLLMProvider(LLMProvider):
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        system_prompt: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        call_index: int | None = None,
    ) -> LLMResponse:
        user_messages = [m for m in messages if m.role in ("user", "customer")]
        last_user_msg = user_messages[-1].content.lower() if user_messages else ""

        tool_messages = [m for m in messages if m.role == "tool"]
        if tool_messages:
            return LLMResponse(
                content="Done. How else can I help?",
                finish_reason="stop",
            )

        if any(kw in last_user_msg for kw in ["search", "product", "find"]):
            return LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_mock_1",
                        "name": "search_products",
                        "arguments": {"query": last_user_msg[:50]},
                    }
                ],
                finish_reason="tool_calls",
            )

        if any(kw in last_user_msg for kw in ["stock", "inventory", "quantity"]):
            return LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_mock_2",
                        "name": "check_inventory",
                        "arguments": {"product_id": "mock-product-id"},
                    }
                ],
                finish_reason="tool_calls",
            )

        if any(kw in last_user_msg for kw in ["human", "person"]):
            return LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "id": "call_mock_3",
                        "name": "handoff_to_human",
                        "arguments": {
                            "reason": "customer_requested_human",
                            "summary": "Customer requested human",
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

        return LLMResponse(content="How can I help you today?", finish_reason="stop")
