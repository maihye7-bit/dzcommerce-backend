"""
Real Qwen API verification script.
Does NOT modify any project file.
NEVER prints the API key.
Run: python verify_qwen_real.py
"""
import asyncio
import time


def mask_key(key: str) -> str:
    """Mask API key for safe display."""
    if not key:
        return "<NOT SET>"
    if len(key) <= 8:
        return "<TOO SHORT>"
    return f"{key[:4]}...{key[-4:]} (length={len(key)})"


async def test_1_raw_sdk():
    print("=" * 60)
    print("TEST 1: Raw AsyncOpenAI -> Qwen API")
    print("=" * 60)

    from app.core.config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL, QWEN_TIMEOUT

    print(f"  base_url: {QWEN_BASE_URL}")
    print(f"  model:    {QWEN_MODEL}")
    print(f"  timeout:  {QWEN_TIMEOUT}s")
    print(f"  api_key:  {mask_key(QWEN_API_KEY)}")

    if not QWEN_API_KEY:
        print("  FAIL: QWEN_API_KEY is not set")
        return None

    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("  FAIL: openai package not installed")
        return None

    client = AsyncOpenAI(
        api_key=QWEN_API_KEY,
        base_url=QWEN_BASE_URL,
        timeout=float(QWEN_TIMEOUT),
    )

    start = time.time()
    try:
        response = await client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[{"role": "user", "content": "Say hello in one short sentence."}],
        )
        latency_ms = int((time.time() - start) * 1000)

        print(f"  PASS: Response received in {latency_ms}ms")
        print(f"  finish_reason: {response.choices[0].finish_reason}")
        content = response.choices[0].message.content or ""
        print(f"  content: {content[:120]}")

        if response.usage:
            print(f"  prompt_tokens:     {response.usage.prompt_tokens}")
            print(f"  completion_tokens: {response.usage.completion_tokens}")
            print(f"  total_tokens:      {response.usage.total_tokens}")
        else:
            print("  usage: NOT RETURNED")

        return response
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        print(f"  FAIL after {latency_ms}ms")
        print(f"  Error type: {type(e).__name__}")
        print(f"  Error: {str(e)[:300]}")
        return None


async def test_2_provider():
    print()
    print("=" * 60)
    print("TEST 2: QwenLLMProvider (project class)")
    print("=" * 60)

    try:
        from app.agent.providers.qwen_provider import QwenLLMProvider
        from app.agent.providers.base import LLMMessage
    except Exception as e:
        print(f"  FAIL: Import error: {e}")
        return None

    try:
        provider = QwenLLMProvider()
        print("  Provider initialized")
    except Exception as e:
        print(f"  FAIL on init: {type(e).__name__}: {e}")
        return None

    messages = [LLMMessage(role="user", content="Say hi in Arabic, very short.")]
    start = time.time()
    try:
        response = await provider.chat(messages=messages, tools=None)
        latency_ms = int((time.time() - start) * 1000)

        if response.finish_reason == "error":
            print(f"  FAIL: Provider returned error after {latency_ms}ms")
            print(f"  content: {response.content}")
            return None

        print(f"  PASS in {latency_ms}ms")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  content: {(response.content or '')[:120]}")
        print(f"  tool_calls: {response.tool_calls}")

        usage = getattr(response, "usage", None)
        if usage:
            print(f"  response.usage: {usage}")
        else:
            print("  response.usage: MISSING")

        return response
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        print(f"  FAIL after {latency_ms}ms")
        print(f"  Error type: {type(e).__name__}")
        print(f"  Error: {str(e)[:300]}")
        return None


async def test_3_tool_calling():
    print()
    print("=" * 60)
    print("TEST 3: Tool calling (search_products)")
    print("=" * 60)

    try:
        from app.agent.providers.qwen_provider import QwenLLMProvider
        from app.agent.providers.base import LLMMessage
        from app.agent.tools.search_products import SearchProductsTool
    except Exception as e:
        print(f"  FAIL: Import error: {e}")
        return None

    try:
        provider = QwenLLMProvider()
    except Exception as e:
        print(f"  FAIL on init: {e}")
        return None

    tool = SearchProductsTool()
    tool_def = {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }
    print(f"  Using tool: {tool.name}")

    messages = [
        LLMMessage(role="user", content="Use the search_products tool to find Samsung Galaxy phones")
    ]

    start = time.time()
    try:
        response = await provider.chat(messages=messages, tools=[tool_def])
        latency_ms = int((time.time() - start) * 1000)

        if response.finish_reason == "error":
            print(f"  FAIL: Provider returned error after {latency_ms}ms")
            print(f"  content: {response.content}")
            return None

        print(f"  Response received in {latency_ms}ms")
        print(f"  finish_reason: {response.finish_reason}")
        print(f"  content: {(response.content or '')[:100]}")
        print(f"  tool_calls: {response.tool_calls}")

        if response.tool_calls:
            print("  PASS: Qwen produced a tool call")
        else:
            print("  NOTE: Qwen responded with text only (no tool call)")

        return response
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        print(f"  FAIL after {latency_ms}ms")
        print(f"  Error type: {type(e).__name__}")
        print(f"  Error: {str(e)[:300]}")
        return None


async def main():
    print()
    print("REAL QWEN API VERIFICATION")
    print("Using project's actual configuration")
    print()

    r1 = await test_1_raw_sdk()
    r2 = await test_2_provider()
    r3 = await test_3_tool_calling()

    print()
    print("=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)

    test1_ok = r1 is not None
    test2_ok = r2 is not None and getattr(r2, 'finish_reason', None) != "error"
    test3_ok = r3 is not None and getattr(r3, 'finish_reason', None) != "error"
    tool_ok = test3_ok and bool(getattr(r3, 'tool_calls', None))

    print(f"  Test 1 (raw SDK):       {'PASS' if test1_ok else 'FAIL'}")
    print(f"  Test 2 (provider):      {'PASS' if test2_ok else 'FAIL'}")
    print(f"  Test 3 (tool calling):  {'PASS' if tool_ok else 'PARTIAL' if test3_ok else 'FAIL'}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
