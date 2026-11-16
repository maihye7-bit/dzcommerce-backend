"""
QwenLLMProvider with Robust Retry Logic for 429/Timeout Errors.
"""
import asyncio
import json
import logging
import time
from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError
from app.agent.providers.base import LLMMessage, LLMProvider, LLMResponse
from app.core.config import QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL, QWEN_TIMEOUT

logger = logging.getLogger(__name__)


class QwenLLMProvider(LLMProvider):
    def __init__(self):
        if not QWEN_API_KEY:
            raise ValueError("QWEN_API_KEY is not set.")
        
        self.client = AsyncOpenAI(
            api_key=QWEN_API_KEY,
            base_url=QWEN_BASE_URL,
            timeout=float(QWEN_TIMEOUT),
        )
        self.model = QWEN_MODEL
        # Max retries for transient errors (429, 500s)
        self.max_retries = 3 

    def _build_openai_messages(self, messages: list[LLMMessage]) -> list[dict]:
        """Convert internal LLMMessage list to OpenAI-compatible format."""
        openai_messages = []
        for m in messages:
            msg: dict = {"role": m.role}
            
            if m.role == "assistant" and m.tool_calls:
                msg["content"] = m.content if m.content else None
                msg["tool_calls"] = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                        },
                    }
                    for tc in m.tool_calls
                ]
            elif m.role == "tool":
                msg["content"] = m.content or ""
                msg["tool_call_id"] = m.tool_call_id or ""
            else:
                msg["content"] = m.content or ""
            
            openai_messages.append(msg)
        return openai_messages

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[dict] | None = None,
        system_prompt: str | None = None,
        session_id: str | None = None,
        turn_id: str | None = None,
        call_index: int | None = None,
    ) -> LLMResponse:
        start_time = time.time()
        openai_messages = self._build_openai_messages(messages)
        
        if system_prompt and not any(m["role"] == "system" for m in openai_messages):
            openai_messages.insert(0, {"role": "system", "content": system_prompt})

        # Map tools to OpenAI format (handling both flat and nested structures)
        openai_tools = None
        if tools:
            openai_tools = []
            for t in tools:
                if "type" in t and t["type"] == "function" and "function" in t:
                    openai_tools.append(t)
                elif "name" in t:
                    openai_tools.append({
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {}),
                        },
                    })

        last_exception = None
        
        # Retry Loop
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=openai_messages,
                    tools=openai_tools,
                    tool_choice="auto" if openai_tools else None,
                )
                
                latency_ms = int((time.time() - start_time) * 1000)
                choice = response.choices[0]
                msg = choice.message
                
                usage_data = response.usage
                input_tokens = usage_data.prompt_tokens if usage_data else 0
                output_tokens = usage_data.completion_tokens if usage_data else 0

                # Handle Tool Calls
                if msg.tool_calls:
                    tool_calls = []
                    for tc in msg.tool_calls:
                        try:
                            args = json.loads(tc.function.arguments)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        tool_calls.append({
                            "name": tc.function.name,
                            "arguments": args,
                            "id": tc.id,
                        })
                    
                    return LLMResponse(
                        content=msg.content,
                        tool_calls=tool_calls,
                        finish_reason="tool_calls",
                        usage={
                            "input_tokens": input_tokens,
                            "output_tokens": output_tokens,
                            "latency_ms": latency_ms,
                            "model": self.model,
                        },
                    )

                # Normal text response
                return LLMResponse(
                    content=msg.content or "",
                    finish_reason=choice.finish_reason,
                    usage={
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "latency_ms": latency_ms,
                        "model": self.model,
                    },
                )

            except (RateLimitError, APITimeoutError, APIError) as e:
                last_exception = e
                error_code = getattr(e, 'status_code', None)
                
                # Only retry on 429 (Rate Limit) or 5xx (Server Error) or Timeout
                should_retry = (
                    isinstance(e, RateLimitError) or 
                    isinstance(e, APITimeoutError) or
                    (isinstance(error_code, int) and error_code >= 500)
                )
                
                if should_retry and attempt < self.max_retries:
                    wait_time = (attempt + 1) * 2  # Simple linear backoff: 2s, 4s, 6s
                    logger.warning(
                        "Qwen request failed; retrying "
                        "(attempt=%s/%s, error_type=%s)",
                        attempt + 1,
                        self.max_retries,
                        type(e).__name__,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Non-retryable error or max retries reached
                    break
            except Exception as e:
                last_exception = e
                break # Unexpected error, don't retry blindly

        # If we reach here, all attempts failed
        logger.error(
            "Qwen request failed after %s attempts (error_type=%s, status_code=%s)",
            self.max_retries + 1,
            type(last_exception).__name__ if last_exception else "unknown",
            getattr(last_exception, "status_code", None),
        )

        return LLMResponse(
            content="عذراً، الخدمة مشغولة حالياً. يرجى المحاولة مرة أخرى بعد قليل.",
            finish_reason="error",
        )
